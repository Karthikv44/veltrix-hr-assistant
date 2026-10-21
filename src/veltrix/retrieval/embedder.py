"""Text embedding interfaces and FastEmbed implementation."""

from typing import Protocol

from fastembed import TextEmbedding

from veltrix.core.logging import get_logger

logger = get_logger("embedder")


class Embedder(Protocol):
    """Protocol for embedding generation."""

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate dense vector embeddings for a list of strings."""
        ...


class FastEmbedEmbedder:
    """CPU-optimized ONNX FastEmbed embedding generator."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        self.model_name = model_name
        self._model: TextEmbedding | None = None

    def _get_model(self) -> TextEmbedding:
        if self._model is None:
            logger.info("Initializing FastEmbed model", model=self.model_name)
            self._model = TextEmbedding(self.model_name)
        return self._model

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._get_model()
        # FastEmbed returns a generator of numpy arrays
        embeddings = list(model.embed(texts))
        return [e.tolist() for e in embeddings]


class FakeEmbedder:
    """Deterministic fake embedder for tests returning fixed-dimension vectors."""

    def __init__(self, dimension: int = 384) -> None:
        self.dimension = dimension

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        results: list[list[float]] = []
        for text in texts:
            # Deterministic pseudo-embedding from text length and ascii sum
            val = float(len(text) % 100) / 100.0
            vec = [val] * self.dimension
            results.append(vec)
        return results
