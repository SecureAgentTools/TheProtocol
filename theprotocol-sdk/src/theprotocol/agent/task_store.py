"""Task state management for A2A agents."""

import asyncio
import datetime
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Union, Any

from ..models import (
    TaskState, Message, Artifact, A2AEvent,
    TaskStatusUpdateEvent, TaskMessageEvent, TaskArtifactUpdateEvent,
)
from ..exceptions import InvalidStateTransitionError

logger = logging.getLogger(__name__)

ALLOWED_TRANSITIONS = {
    TaskState.SUBMITTED.value: {TaskState.WORKING.value, TaskState.CANCELED.value, TaskState.REJECTED.value},
    TaskState.WORKING.value: {TaskState.INPUT_REQUIRED.value, TaskState.COMPLETED.value, TaskState.FAILED.value, TaskState.CANCELED.value},
    TaskState.INPUT_REQUIRED.value: {TaskState.WORKING.value, TaskState.CANCELED.value, TaskState.AUTH_REQUIRED.value},
    TaskState.AUTH_REQUIRED.value: {TaskState.WORKING.value, TaskState.CANCELED.value},
    TaskState.COMPLETED.value: {TaskState.COMPLETED.value},
    TaskState.FAILED.value: {TaskState.FAILED.value},
    TaskState.CANCELED.value: {TaskState.CANCELED.value},
    TaskState.REJECTED.value: {TaskState.REJECTED.value},
}
TERMINAL_STATES = {TaskState.COMPLETED.value, TaskState.FAILED.value, TaskState.CANCELED.value, TaskState.REJECTED.value}


@dataclass
class TaskContext:
    """Holds state for a single task."""
    task_id: str
    current_state: Union[TaskState, str]
    created_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    messages: List[Any] = field(default_factory=list)
    artifacts: Dict[str, Any] = field(default_factory=dict)

    def update_state(self, new_state: Union[TaskState, str]):
        current_str = self.current_state.value if isinstance(self.current_state, TaskState) else str(self.current_state)
        new_str = new_state.value if isinstance(new_state, TaskState) else str(new_state)

        if new_str == current_str:
            self.updated_at = datetime.datetime.now(datetime.timezone.utc)
            return

        if current_str in TERMINAL_STATES:
            self.updated_at = datetime.datetime.now(datetime.timezone.utc)
            return

        allowed = ALLOWED_TRANSITIONS.get(current_str)
        if allowed is None or new_str not in allowed:
            raise InvalidStateTransitionError(self.task_id, current_str, new_str)

        self.current_state = new_state
        self.updated_at = datetime.datetime.now(datetime.timezone.utc)

    def add_message(self, message: Message):
        self.messages.append(message)
        self.updated_at = datetime.datetime.now(datetime.timezone.utc)

    def add_or_update_artifact(self, artifact: Artifact):
        self.artifacts[artifact.id] = artifact
        self.updated_at = datetime.datetime.now(datetime.timezone.utc)


class BaseTaskStore(ABC):
    """Abstract base for task storage backends."""

    @abstractmethod
    async def get_task(self, task_id: str) -> Optional[TaskContext]: ...

    @abstractmethod
    async def create_task(self, task_id: str) -> TaskContext: ...

    @abstractmethod
    async def update_task_state(self, task_id: str, new_state: Union[TaskState, str], message: Optional[str] = None) -> Optional[TaskContext]: ...

    @abstractmethod
    async def delete_task(self, task_id: str) -> bool: ...

    @abstractmethod
    async def add_listener(self, task_id: str, queue: asyncio.Queue): ...

    @abstractmethod
    async def remove_listener(self, task_id: str, queue: asyncio.Queue): ...

    @abstractmethod
    async def get_listeners(self, task_id: str) -> List[asyncio.Queue]: ...

    @abstractmethod
    async def notify_status_update(self, task_id: str, new_state: Union[TaskState, str], message: Optional[str] = None): ...

    @abstractmethod
    async def notify_message_event(self, task_id: str, message: Message): ...

    @abstractmethod
    async def notify_artifact_event(self, task_id: str, artifact: Artifact): ...


class InMemoryTaskStore(BaseTaskStore):
    """In-memory task store. Suitable for development and single-process agents.

    Bounded: keeps at most ``_MAX_TASKS`` tasks, evicting oldest-first (FIFO) on
    insert so long-running agents don't leak memory over time.
    """

    _MAX_TASKS = 2000

    def __init__(self):
        self._tasks: Dict[str, TaskContext] = {}
        self._listeners: Dict[str, List[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def get_task(self, task_id: str) -> Optional[TaskContext]:
        async with self._lock:
            return self._tasks.get(task_id)

    async def create_task(self, task_id: str) -> TaskContext:
        async with self._lock:
            if task_id in self._tasks:
                return self._tasks[task_id]
            ctx = TaskContext(task_id=task_id, current_state=TaskState.SUBMITTED)
            self._tasks[task_id] = ctx
            self._listeners[task_id] = []
            # Bounded GC: evict oldest entries (FIFO) to cap memory.
            while len(self._tasks) > self._MAX_TASKS:
                old_id = next(iter(self._tasks))
                if old_id == task_id:
                    break
                self._tasks.pop(old_id, None)
                self._listeners.pop(old_id, None)
        await self.notify_status_update(task_id, TaskState.SUBMITTED)
        return ctx

    async def update_task_state(self, task_id: str, new_state: Union[TaskState, str], message: Optional[str] = None) -> Optional[TaskContext]:
        async with self._lock:
            ctx = self._tasks.get(task_id)
            if not ctx:
                return None
            old_state = ctx.current_state
            try:
                ctx.update_state(new_state)
            except InvalidStateTransitionError:
                return None

        old_str = old_state.value if isinstance(old_state, TaskState) else str(old_state)
        new_str = ctx.current_state.value if isinstance(ctx.current_state, TaskState) else str(ctx.current_state)
        if old_str != new_str:
            await self.notify_status_update(task_id, ctx.current_state, message=message)
        return ctx

    async def delete_task(self, task_id: str) -> bool:
        async with self._lock:
            deleted = self._tasks.pop(task_id, None) is not None
            self._listeners.pop(task_id, None)
            return deleted

    async def add_listener(self, task_id: str, queue: asyncio.Queue):
        async with self._lock:
            if task_id not in self._listeners:
                self._listeners[task_id] = []
            if queue not in self._listeners[task_id]:
                self._listeners[task_id].append(queue)

    async def remove_listener(self, task_id: str, queue: asyncio.Queue):
        async with self._lock:
            if task_id in self._listeners:
                try:
                    self._listeners[task_id].remove(queue)
                except ValueError:
                    pass

    async def get_listeners(self, task_id: str) -> List[asyncio.Queue]:
        async with self._lock:
            return list(self._listeners.get(task_id, []))

    async def _notify(self, task_id: str, event: A2AEvent):
        listeners = await self.get_listeners(task_id)
        for listener in listeners:
            try:
                await listener.put(event)
            except Exception as e:
                logger.error(f"Failed to notify listener for task {task_id}: {e}")

    async def notify_status_update(self, task_id: str, new_state: Union[TaskState, str], message: Optional[str] = None):
        state = TaskState(new_state) if isinstance(new_state, str) else new_state
        event = TaskStatusUpdateEvent(
            taskId=task_id, state=state,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
            message=message,
        )
        await self._notify(task_id, event)

    async def notify_message_event(self, task_id: str, message: Message):
        async with self._lock:
            ctx = self._tasks.get(task_id)
            if ctx:
                ctx.add_message(message)
        event = TaskMessageEvent(
            taskId=task_id, message=message,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        await self._notify(task_id, event)

    async def notify_artifact_event(self, task_id: str, artifact: Artifact):
        async with self._lock:
            ctx = self._tasks.get(task_id)
            if ctx:
                ctx.add_or_update_artifact(artifact)
        event = TaskArtifactUpdateEvent(
            taskId=task_id, artifact=artifact,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        await self._notify(task_id, event)
