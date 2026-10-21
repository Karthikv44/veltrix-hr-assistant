"""Application composition root and dependency injection container."""

from dataclasses import dataclass, field

from veltrix.core.clock import AppClock, Clock
from veltrix.core.config import Settings, get_settings


@dataclass
class Container:
    """Central dependency injection container for Veltrix PeopleOps Assistant."""

    settings: Settings = field(default_factory=get_settings)
    clock: Clock = field(init=False)

    def __post_init__(self) -> None:
        self.clock = AppClock(fixed_today=self.settings.APP_TODAY)


# Global container instance
_container: Container | None = None


def get_container() -> Container:
    """Return the global application container singleton."""
    global _container
    if _container is None:
        _container = Container()
    return _container


def reset_container(settings: Settings | None = None) -> Container:
    """Reset the container, useful for tests with customized settings."""
    global _container
    _container = Container(settings=settings) if settings is not None else Container()
    return _container
