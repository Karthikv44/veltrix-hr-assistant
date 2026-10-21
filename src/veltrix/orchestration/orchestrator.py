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

    async def handle_message(
        self,
        session_id: str,
        message: str,
        ctx: RequestContext,
    ) -> ChatResponse:
        """Route and execute a user message, assembling a compliant ChatResponse."""
        reference_date = self.clock.today()

        # 1. Intent classification
        intent = Router.classify_intent(message, ctx)

        # 2. Handle Refuse
        if intent == "refuse":
            return Assembler.assemble_response(
                answer=REFUSAL_MESSAGE,
                intended_route="refuse",
            )

        # 3. Handle Greeting (counted as refuse/conversational without tools/docs)
        if intent == "greeting":
            return Assembler.assemble_response(
                answer=GREETING_MESSAGE,
                intended_route="refuse",
            )

        # 4. Handle RAG
        if intent == "rag":
            answer, citations, route = await self.rag_pipeline.execute(
                query=message,
                ctx=ctx,
                reference_date=reference_date,
            )
            return Assembler.assemble_response(
                answer=answer,
                intended_route=route,  # "rag" or "no_answer"
                citations=citations,
            )

        # Fallback for leave_tool and hybrid (to be fully connected in M5/M6)
        return Assembler.assemble_response(
            answer="Leave management tools will process your request.",
            intended_route="tool",
            tool_calls=[],
        )
