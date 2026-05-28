from enum import Enum
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field


class MessageType(Enum):
    HELLO = "hello"
    HEARTBEAT = "heartbeat"
    TASK_REQUEST = "task_request"
    TASK_RESPONSE = "task_response"
    DISCUSSION_MESSAGE = "discussion_message"
    DISCUSSION_SUMMARY = "discussion_summary"
    COORDINATION_COMMAND = "coordination_command"
    KNOWLEDGE_QUERY = "knowledge_query"
    KNOWLEDGE_RESPONSE = "knowledge_response"
    ERROR = "error"


class NodeInfo(BaseModel):
    node_id: str
    node_name: str
    specialty: str
    capabilities: List[str] = Field(default_factory=list)
    status: str = "active"


class BaseMessage(BaseModel):
    message_id: str
    message_type: MessageType
    sender_id: str
    timestamp: float
    payload: Dict[str, Any] = Field(default_factory=dict)


class HelloMessage(BaseModel):
    node_info: NodeInfo


class TaskRequest(BaseModel):
    task_id: str
    task_description: str
    task_type: str
    context: Optional[Dict[str, Any]] = None
    requirements: Optional[List[str]] = None
    timeout: Optional[float] = None


class TaskResponse(BaseModel):
    task_id: str
    responder_id: str
    status: str
    result: Optional[Any] = None
    confidence: Optional[float] = None
    sources: Optional[List[str]] = None
    error: Optional[str] = None


class DiscussionMessage(BaseModel):
    discussion_id: str
    message_index: int
    content: str
    references: Optional[List[str]] = None
    agreement: Optional[float] = None


class CoordinationCommand(BaseModel):
    command_type: str
    target_node_ids: Optional[List[str]] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)
