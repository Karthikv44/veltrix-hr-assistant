"""Loader registry for mapping document file extensions to loader classes."""

from collections.abc import Callable
from pathlib import Path

from veltrix.api.errors import VeltrixError
from veltrix.core.logging import get_logger
from veltrix.ingestion.loaders.base import BaseLoader

logger = get_logger("loader_registry")


class UnsupportedFormatError(VeltrixError):
    """Raised when encountering a file extension without a registered loader."""


class LoaderRegistry:
    """Registry maintaining document loaders keyed by file extension."""

    def __init__(self) -> None:
        self._loaders: dict[str, type[BaseLoader] | Callable[[], BaseLoader]] = {}

    def register(self, extension: str, loader: type[BaseLoader] | Callable[[], BaseLoader]) -> None:
        """Register a loader for a given file extension (e.g. '.pdf' or 'pdf')."""
        ext = extension.lower().strip()
        if not ext.startswith("."):
            ext = f".{ext}"
        self._loaders[ext] = loader
        logger.debug("Registered loader for extension", extension=ext, loader=str(loader))

    def get(self, file_path_or_ext: str | Path) -> BaseLoader:
        """Retrieve an instantiated loader for the specified file path or extension."""
        path = (
            Path(file_path_or_ext)
            if isinstance(file_path_or_ext, Path)
            else Path(str(file_path_or_ext).strip())
        )
        ext = path.suffix.lower()
        if not ext:
            # Handle if just "pdf" or ".pdf" was passed
            s = str(file_path_or_ext).lower().strip()
            ext = f".{s}" if not s.startswith(".") else s

        loader_cls_or_factory = self._loaders.get(ext)
        if not loader_cls_or_factory:
            raise UnsupportedFormatError(f"No loader registered for file extension '{ext}'")

        if isinstance(loader_cls_or_factory, type):
            return loader_cls_or_factory()
        return loader_cls_or_factory()


# Global default registry
loader_registry = LoaderRegistry()


def register_loader(extension: str, loader: type[BaseLoader] | Callable[[], BaseLoader]) -> None:
    """Convenience function to register a loader in the global registry."""
    loader_registry.register(extension, loader)
