"""
Pydantic models for the Agent-to-Agent (A2A) protocol.
Native A2A v1.0 specification. Backward compatible with v0.3 input.
"""

import datetime
from enum import Enum
from typing import List, Optional, Dict, Any, Union, Literal
from pydantic import BaseModel, Field, HttpUrl, ConfigDict


class TaskState(str, Enum):
    """A2A v1.0 task states."""
    SUBMITTED = "TASK_STATE_SUBMITTED"
    WORKING = "TASK_STATE_WORKING"
    INPUT_REQUIRED = "TASK_STATE_INPUT_REQUIRED"
    COMPLETED = "TASK_STATE_COMPLETED"
    FAILED = "TASK_STATE_FAILED"
    CANCELED = "TASK_STATE_CANCELED"
    REJECTED = "TASK_STATE_REJECTED"
    AUTH_REQUIRED = "TASK_STATE_AUTH_REQUIRED"


# ── Message Parts ──

class TextPart(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal['text'] = "text"
    content: str = Field(..., description="Plain text content.")


class FilePart(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal['file'] = "file"
    url: HttpUrl = Field(..., description="URL pointing to the file.")
    media_type: Optional[str] = Field(None, alias="mediaType")
    filename: Optional[str] = None


class DataPart(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal['data'] = "data"
    content: Dict[str, Any] = Field(..., description="Structured data (JSON).")
    media_type: str = Field("application/json", alias="mediaType")


Part = Union[TextPart, FilePart, DataPart]


# ── Artifacts ──

class Artifact(BaseModel):
    id: str = Field(..., description="Unique artifact ID within the task.")
    type: str = Field(..., description="Artifact type (e.g., 'file', 'log').")
    content: Optional[Any] = None
    url: Optional[HttpUrl] = None
    media_type: Optional[str] = Field(None, alias="mediaType")
    metadata: Optional[Dict[str, Any]] = None


# ── Messages ──

class Message(BaseModel):
    model_config = ConfigDict(frozen=True)
    role: Literal['user', 'agent', 'assistant'] = Field(...)  # v1.0: user/agent. assistant accepted for backward compat.
    parts: List[Part] = Field(..., min_length=1)
    metadata: Optional[Dict[str, Any]] = None


# ── Task ──

class Task(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    state: TaskState
    created_at: datetime.datetime = Field(..., alias="createdAt")
    updated_at: datetime.datetime = Field(..., alias="updatedAt")
    messages: List[Message] = Field(default_factory=list)
    artifacts: List[Artifact] = Field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = None


# ── JSON-RPC Params & Results ──

class TaskSendParams(BaseModel):
    id: Optional[str] = None
    message: Message


class TaskSendResult(BaseModel):
    id: str


class TaskGetParams(BaseModel):
    id: str


GetTaskResult = Task


class TaskCancelParams(BaseModel):
    id: str


class TaskCancelResult(BaseModel):
    success: bool = True
    message: Optional[str] = None


# ── SSE Events ──

class TaskStatusUpdateEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    task_id: str = Field(..., alias="taskId")
    state: TaskState
    timestamp: datetime.datetime
    message: Optional[str] = None


class TaskMessageEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    task_id: str = Field(..., alias="taskId")
    message: Message
    timestamp: datetime.datetime


class TaskArtifactUpdateEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    task_id: str = Field(..., alias="taskId")
    artifact: Artifact
    timestamp: datetime.datetime
