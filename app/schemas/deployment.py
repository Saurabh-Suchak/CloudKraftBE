from pydantic import BaseModel
from typing import List, Optional, Any
from datetime import datetime


class DeployRequest(BaseModel):
    workflow_id: Optional[int] = None
    workflow: Optional[Any] = None   # WorkflowState dict
    workflow_name: Optional[str] = None


class DeploymentLogItem(BaseModel):
    id: int
    level: str
    message: str
    timestamp: datetime

    class Config:
        from_attributes = True


class DeploymentResponse(BaseModel):
    id: int
    status: str
    workflow_name: Optional[str]
    resource_count: Optional[int]
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]

    class Config:
        from_attributes = True


class DeploymentLogsResponse(BaseModel):
    logs: List[DeploymentLogItem]
    has_more: bool
    deployment_status: str
