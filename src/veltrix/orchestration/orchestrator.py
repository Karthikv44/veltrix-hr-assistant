"""Central orchestrator managing intent routing, pipelines, and response assembly."""

from veltrix.api.container import Container
from veltrix.api.schemas import ChatResponse
from veltrix.core.logging import get_logger
from veltrix.domain.models import RequestContext
from veltrix.llm.prompts import load_prompt
from veltrix.orchestration.assembler import Assembler
from veltrix.orchestration.composer import AnswerComposer
from veltrix.orchestration.extractor import ClaimExtractor
from veltrix.orchestration.pipelines.rag import RagPipeline
from veltrix.orchestration.router import Router
from veltrix.retrieval.chroma_store import ChromaVectorStore
from veltrix.retrieval.embedder import FastEmbedEmbedder
from veltrix.retrieval.retriever import HybridRetriever

logger = get_logger("orchestrator")

DEFAULT_REFUSAL_MESSAGE = (
    "I can only assist with Veltrix HR policies and leave management within your permitted scope."
)

DEFAULT_GREETING_MESSAGE = "Hello! I am your Veltrix PeopleOps Assistant. How can I assist you with HR policies or leave today?"


def get_refusal_message() -> str:
    """Load refusal message from prompts or fallback."""
    return load_prompt("refusal_message", default=DEFAULT_REFUSAL_MESSAGE)


def get_greeting_message() -> str:
    """Load greeting message from prompts or fallback."""
    return load_prompt("greeting_message", default=DEFAULT_GREETING_MESSAGE)


REFUSAL_MESSAGE = get_refusal_message()
GREETING_MESSAGE = get_greeting_message()


class Orchestrator:
    """Master orchestrator for processing chat messages through privilege-separated pipelines."""

    def __init__(self, container: Container) -> None:
        self.container = container
        self.settings = container.settings
        self.clock = container.clock

        # Initialize retrieval components
        self.vector_store = ChromaVectorStore(self.settings.CHROMA_DIR)
        self.embedder = FastEmbedEmbedder(model_name=self.settings.FAST_EMBED_MODEL)
        self.retriever = HybridRetriever(
            vector_store=self.vector_store,
            embedder=self.embedder,
            app_db_path=self.settings.APP_DB_PATH,
        )

        # Initialize LLM Gateway and orchestration
        from veltrix.llm.gateway import LLMGateway
        from veltrix.llm.providers.gemini import GeminiClient

        # Wire client based on config
        api_key = self.settings.GEMINI_API_KEY or self.settings.GOOGLE_API_KEY
        client = GeminiClient(api_key=api_key, model=self.settings.LLM_MODEL)
        self.gateway = LLMGateway(
            client=client,
            max_corpus_tokens=self.settings.MAX_CORPUS_TOKENS,
            timeout_seconds=self.settings.REQUEST_TIMEOUT_SECONDS,
            cache_enabled=self.settings.LLM_CACHE_ENABLED,
        )

        self.extractor = ClaimExtractor(self.gateway)
        self.composer = AnswerComposer(self.gateway)
        self.rag_pipeline = RagPipeline(
            retriever=self.retriever,
            extractor=self.extractor,
            composer=self.composer,
        )

        from veltrix.data.sessions import SessionManager
        from veltrix.orchestration.pipelines.hybrid import HybridPipeline
        from veltrix.orchestration.pipelines.tool import ToolPipeline
        from veltrix.tools.leave import LeaveTools

        self.session_manager = SessionManager(str(self.settings.APP_DB_PATH))
        self.leave_tools = LeaveTools(
            db_path=str(self.settings.DB_PATH),
            app_db_path=str(self.settings.APP_DB_PATH),
        )
        self.tool_pipeline = ToolPipeline(
            leave_tools=self.leave_tools,
            session_manager=self.session_manager,
        )
        self.hybrid_pipeline = HybridPipeline(
            rag_pipeline=self.rag_pipeline,
            leave_tools=self.leave_tools,
            db_path=str(self.settings.DB_PATH),
        )

    async def handle_message(
        self,
        session_id: str,
        message: str,
        ctx: RequestContext,
    ) -> ChatResponse:
        """Route and execute a user message, assembling a compliant ChatResponse."""
        reference_date = self.clock.today()

        # Check if there is an active proposal in the confirmation state machine
        pending = self.session_manager.get_proposal(session_id)

        # Retrieve conversation history for context continuity across turns
        history = self.session_manager.get_recent_messages(session_id, limit=6)

        # 1. Intent classification via LLM-driven classifier (Dual-LLM Security Pattern)
        classification = await Router.classify(
            message=message,
            ctx=ctx,
            gateway=self.gateway,
            reference_date=reference_date.isoformat(),
            history=history,
            pending_proposal=pending,
        )
        route = classification.route

        # Record user message in session history
        self.session_manager.append_message(session_id, "user", message)

        # Handle pending confirmation if active
        if pending is not None:
            if classification.action == "confirm":
                res = await self.tool_pipeline.execute_or_propose(
                    session_id=session_id,
                    message=message,
                    ctx=ctx,
                    today=reference_date,
                    action="confirm",
                )
                self.session_manager.append_message(session_id, "assistant", res.answer)
                return res
            elif classification.action == "cancel_proposal":
                self.session_manager.clear_proposal(session_id)
                res = Assembler.assemble_response(
                    answer="Your pending action has been cancelled.",
                    intended_route="tool",
                    tool_calls=[],
                    pending_confirmation=False,
                )
                self.session_manager.append_message(session_id, "assistant", res.answer)
                return res
            else:
                # Any other prompt discards the proposal and continues dynamically
                logger.info(
                    "Discarding unconfirmed proposal due to new intent",
                    session_id=session_id,
                    new_action=classification.action,
                    new_route=classification.route,
                )
                self.session_manager.clear_proposal(session_id)

        # 2. Handle Refuse
        if route == "refuse":
            res = Assembler.assemble_response(
                answer=REFUSAL_MESSAGE,
                intended_route="refuse",
            )
            self.session_manager.append_message(session_id, "assistant", res.answer)
            return res

        # 3. Handle Greeting
        if route == "greeting":
            res = Assembler.assemble_response(
                answer=GREETING_MESSAGE,
                intended_route="clarify",
            )
            self.session_manager.append_message(session_id, "assistant", res.answer)
            return res

        # 4. Handle Clarify (Dynamic question formulated by Intent Classifier LLM)
        if route == "clarify":
            clarification_text = classification.clarification_question or (
                "Could you please clarify your request? For leave applications, please specify whether you need 'annual' or 'sick' leave and the dates."
            )
            res = Assembler.assemble_response(
                answer=clarification_text,
                intended_route="clarify",
            )
            self.session_manager.append_message(session_id, "assistant", res.answer)
            return res

        # 5. Handle Hybrid (Both documents and tools)
        if route == "hybrid":
            answer, citations, tool_calls = await self.hybrid_pipeline.execute(
                query=message,
                ctx=ctx,
                today=reference_date,
                leave_type=classification.leave_type,
                target_month=classification.target_month,
            )
            res = Assembler.assemble_response(
                answer=answer,
                intended_route="hybrid",
                citations=citations,
                tool_calls=tool_calls,
            )
            self.session_manager.append_message(session_id, "assistant", res.answer)
            return res

        # 6. Handle Leave Tools (Action driven directly from classified intent)
        if route == "leave_tool":
            res = await self.tool_pipeline.execute_or_propose(
                session_id=session_id,
                message=message,
                ctx=ctx,
                today=reference_date,
                action=classification.action,
                extracted_leave_type=classification.leave_type,
                start_date=classification.start_date,
                end_date=classification.end_date,
                extracted_request_id=classification.request_id,
            )
            self.session_manager.append_message(session_id, "assistant", res.answer)
            return res

        # 7. Handle RAG
        if route == "rag":
            answer, citations, rag_route = await self.rag_pipeline.execute(
                query=message,
                ctx=ctx,
                reference_date=reference_date,
            )
            res = Assembler.assemble_response(
                answer=answer,
                intended_route=rag_route,  # "rag" or "no_answer"
                citations=citations,
            )
            self.session_manager.append_message(session_id, "assistant", res.answer)
            return res

        # Fallback to tool pipeline
        res = await self.tool_pipeline.execute_or_propose(
            session_id=session_id,
            message=message,
            ctx=ctx,
            today=reference_date,
            action=classification.action,
            extracted_leave_type=classification.leave_type,
            start_date=classification.start_date,
            end_date=classification.end_date,
            extracted_request_id=classification.request_id,
        )
        self.session_manager.append_message(session_id, "assistant", res.answer)
        return res
