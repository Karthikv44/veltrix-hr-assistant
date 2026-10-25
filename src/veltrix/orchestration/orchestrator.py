"""Central orchestrator managing intent routing, pipelines, and response assembly."""

from veltrix.api.container import Container
from veltrix.api.schemas import ChatResponse
from veltrix.core.logging import get_logger
from veltrix.domain.models import RequestContext
from veltrix.orchestration.assembler import Assembler
from veltrix.orchestration.composer import AnswerComposer
from veltrix.orchestration.extractor import ClaimExtractor
from veltrix.orchestration.pipelines.rag import RagPipeline
from veltrix.orchestration.router import Router
from veltrix.retrieval.chroma_store import ChromaVectorStore
from veltrix.retrieval.embedder import FastEmbedEmbedder
from veltrix.retrieval.retriever import HybridRetriever

logger = get_logger("orchestrator")

REFUSAL_MESSAGE = (
    "I can only assist with Veltrix HR policies and leave management within your permitted scope."
)

GREETING_MESSAGE = "Hello! I am your Veltrix PeopleOps Assistant. How can I assist you with HR policies or leave today?"


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
        if pending is not None:
            # Route directly to tool confirmation state machine
            return await self.tool_pipeline.execute_or_propose(
                session_id=session_id,
                message=message,
                ctx=ctx,
                today=reference_date,
            )

        # 1. Intent classification via LLM-driven classifier (Dual-LLM Security Pattern)
        classification = await Router.classify(message, ctx, gateway=self.gateway)
        route = classification.route

        # 2. Handle Refuse
        if route == "refuse":
            return Assembler.assemble_response(
                answer=REFUSAL_MESSAGE,
                intended_route="refuse",
            )

        # 3. Handle Greeting
        if route == "greeting":
            return Assembler.assemble_response(
                answer=GREETING_MESSAGE,
                intended_route="refuse",
            )

        # 4. Handle Clarify (Dynamic question formulated by Intent Classifier LLM)
        if route == "clarify":
            clarification_text = classification.clarification_question or (
                "Could you please clarify your request? For leave applications, please specify whether you need 'annual' or 'sick' leave and the dates."
            )
            return Assembler.assemble_response(
                answer=clarification_text,
                intended_route="clarify",
            )

        # 5. Handle Hybrid (Both documents and tools)
        if route == "hybrid":
            answer, citations, tool_calls = await self.hybrid_pipeline.execute(
                query=message,
                ctx=ctx,
                today=reference_date,
                leave_type=classification.leave_type,
                target_month=classification.target_month,
            )
            return Assembler.assemble_response(
                answer=answer,
                intended_route="hybrid",
                citations=citations,
                tool_calls=tool_calls,
            )

        # 6. Handle Leave Tools (Action driven directly from classified intent)
        if route == "leave_tool":
            return await self.tool_pipeline.execute_or_propose(
                session_id=session_id,
                message=message,
                ctx=ctx,
                today=reference_date,
                action=classification.action,
                extracted_leave_type=classification.leave_type,
                extracted_dates=classification.dates_referenced,
                extracted_request_id=classification.request_id,
            )

        # 6. Handle RAG
        if route == "rag":
            answer, citations, rag_route = await self.rag_pipeline.execute(
                query=message,
                ctx=ctx,
                reference_date=reference_date,
            )
            return Assembler.assemble_response(
                answer=answer,
                intended_route=rag_route,  # "rag" or "no_answer"
                citations=citations,
            )

        # Fallback to tool pipeline
        return await self.tool_pipeline.execute_or_propose(
            session_id=session_id,
            message=message,
            ctx=ctx,
            today=reference_date,
            action=classification.action,
            extracted_leave_type=classification.leave_type,
            extracted_dates=classification.dates_referenced,
            extracted_request_id=classification.request_id,
        )
