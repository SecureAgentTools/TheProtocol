"""Decorator for custom A2A JSON-RPC methods."""

import asyncio
from typing import Any, Callable, TypeVar

F = TypeVar('F', bound=Callable[..., Any])


def a2a_method(method_name: str) -> Callable[[F], F]:
    """
    Mark an agent method as a handler for a custom A2A JSON-RPC method.

    Example::

        class MyAgent(BaseA2AAgent):
            @a2a_method("custom/analyze")
            async def analyze(self, data: dict) -> dict:
                return {"result": "analyzed"}
    """
    if not isinstance(method_name, str) or not method_name:
        raise ValueError("a2a_method requires a non-empty method name string.")

    def _decorator(func: F) -> F:
        if not asyncio.iscoroutinefunction(func):
            raise TypeError(f"A2A method handler '{func.__name__}' must be async.")
        setattr(func, '_a2a_method_name', method_name)
        return func

    return _decorator
