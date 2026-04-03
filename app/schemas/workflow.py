from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from datetime import datetime


class WorkflowNode(BaseModel):
    id: str
    type: str  # ec2, vpc, s3, etc.
    position: Dict[str, int]  # { x: int, y: int }
    config: Dict[str, Any]  # Resource-specific configuration
    connections: List[str] = []  # IDs of directly connected nodes (bidirectional)


class ConnectionItem(BaseModel):
    id: str
    fromNodeId: str
    toNodeId: str


class WorkflowState(BaseModel):
    nodes: List[WorkflowNode]
    connections: List[ConnectionItem] = []  # Canvas connection edges
    metadata: Dict[str, Any] = {}


class WorkflowBase(BaseModel):
    name: str
    description: Optional[str] = None
    workflow_state: WorkflowState


class WorkflowCreate(WorkflowBase):
    pass


class WorkflowUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    workflow_state: Optional[WorkflowState] = None


class WorkflowResponse(WorkflowBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

