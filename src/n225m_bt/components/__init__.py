"""Reusable research library. Decorators are metadata, not registration gates."""
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def component(*, id: str, kind: str, summary: str, tags: list[str] | None = None,
              uses: list[str] | None = None) -> Callable[[T], T]:
    """Attach discoverable literal metadata to a class/function without changing it."""
    def decorate(value: T) -> T:
        return value
    return decorate
