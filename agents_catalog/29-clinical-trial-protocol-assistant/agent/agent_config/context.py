"""Session context holder for the Clinical Trial Protocol Assistant."""

from contextvars import ContextVar
from typing import Optional, TYPE_CHECKING
import asyncio

if TYPE_CHECKING:
    from .agent import ClinicalTrialAgent


class ClinicalTrialContext:
    """Context manager for the Clinical Trial Protocol Assistant."""

    # Global state for persistence across agent calls
    _response_queue: Optional[asyncio.Queue] = None
    _agent = None

    _response_queue_ctx: ContextVar[Optional[asyncio.Queue]] = ContextVar(
        "response_queue", default=None
    )
    _agent_ctx: ContextVar = ContextVar("agent", default=None)

    @classmethod
    def get_response_queue_ctx(cls) -> Optional[asyncio.Queue]:
        if cls._response_queue:
            return cls._response_queue
        try:
            return cls._response_queue_ctx.get()
        except LookupError:
            return None

    @classmethod
    def set_response_queue_ctx(cls, queue: asyncio.Queue) -> None:
        cls._response_queue = queue
        cls._response_queue_ctx.set(queue)

    @classmethod
    def get_agent_ctx(cls):
        if cls._agent:
            return cls._agent
        try:
            return cls._agent_ctx.get()
        except LookupError:
            return None

    @classmethod
    def set_agent_ctx(cls, agent) -> None:
        cls._agent = agent
        cls._agent_ctx.set(agent)
