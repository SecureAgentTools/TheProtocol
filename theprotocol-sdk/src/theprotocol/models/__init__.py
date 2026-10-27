"""A2A protocol Pydantic models."""

from typing import Union

from .a2a_protocol import (
    TaskState,
    TextPart, FilePart, DataPart, Part,
    Artifact, Message, Task,
    TaskSendParams, TaskSendResult,
    TaskGetParams, GetTaskResult,
    TaskCancelParams, TaskCancelResult,
    TaskStatusUpdateEvent, TaskMessageEvent, TaskArtifactUpdateEvent,
)
from .agent_card import (
    AgentProvider, AgentSkill, AgentAuthentication,
    AgentCapabilities, TeeDetails, AgentCard,
    SupportedInterface, AgentExtension,  # Q-C W6 (2026-05-12) A2A v1.0 §4.4-§4.5
)

A2AEvent = Union[TaskStatusUpdateEvent, TaskMessageEvent, TaskArtifactUpdateEvent]

__all__ = [
    "TaskState", "TextPart", "FilePart", "DataPart", "Part",
    "Artifact", "Message", "Task",
    "TaskSendParams", "TaskSendResult", "TaskGetParams", "GetTaskResult",
    "TaskCancelParams", "TaskCancelResult",
    "TaskStatusUpdateEvent", "TaskMessageEvent", "TaskArtifactUpdateEvent",
    "A2AEvent",
    "AgentProvider", "AgentSkill", "AgentAuthentication",
    "AgentCapabilities", "TeeDetails", "AgentCard",
    "SupportedInterface", "AgentExtension",
]
