from pydantic import BaseModel, field_validator
from typing import List, Dict, Any, Optional
from datetime import datetime

_MAX_CONFIG_KEYS = 50
_MAX_STRING_LEN = 512
_MAX_NODES = 50
_MAX_CONNECTIONS = 200
_MAX_NAME_LEN = 100


class WorkflowNode(BaseModel):
    id: str
    type: str
    position: Dict[str, int]
    config: Dict[str, Any]
    connections: List[str] = []

    @field_validator("id", "type")
    @classmethod
    def _cap_short_strings(cls, v: str) -> str:
        if len(v) > _MAX_NAME_LEN:
            raise ValueError(f"Value too long (max {_MAX_NAME_LEN} characters)")
        return v

    @field_validator("config")
    @classmethod
    def _validate_config(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        # F-015: cap config size to prevent disk-exhaustion via huge HCL files
        if len(v) > _MAX_CONFIG_KEYS:
            raise ValueError(f"Node config may not have more than {_MAX_CONFIG_KEYS} keys")
        for key, val in v.items():
            if isinstance(val, str) and len(val) > _MAX_STRING_LEN:
                raise ValueError(
                    f"Config value for '{key}' exceeds {_MAX_STRING_LEN} characters"
                )
        return v

    @field_validator("connections")
    @classmethod
    def _validate_connections(cls, v: List[str]) -> List[str]:
        if len(v) > _MAX_CONNECTIONS:
            raise ValueError(f"A node may not have more than {_MAX_CONNECTIONS} connections")
        return v


class ConnectionItem(BaseModel):
    id: str
    fromNodeId: str
    toNodeId: str


class WorkflowState(BaseModel):
    nodes: List[WorkflowNode]
    connections: List[ConnectionItem] = []
    metadata: Dict[str, Any] = {}

    @field_validator("nodes")
    @classmethod
    def _validate_nodes(cls, v: List[WorkflowNode]) -> List[WorkflowNode]:
        # F-015: cap total node count
        if len(v) > _MAX_NODES:
            raise ValueError(f"Workflow may not contain more than {_MAX_NODES} nodes")
        return v


class WorkflowBase(BaseModel):
    name: str
    description: Optional[str] = None
    workflow_state: WorkflowState

    @field_validator("name")
    @classmethod
    def _cap_name(cls, v: str) -> str:
        if len(v) > 200:
            raise ValueError("Workflow name may not exceed 200 characters")
        return v


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
