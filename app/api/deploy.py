import asyncio
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database import get_db
from app.models.deployment import Deployment, DeploymentLog
from app.models.user import User
from app.models.workflow import Workflow
from app.schemas.deployment import (
    DeployRequest,
    DeploymentLogsResponse,
    DeploymentLogItem,
    DeploymentResponse,
)
from app.schemas.workflow import WorkflowState
from app.services.terraform_deployer import run_deployment, run_destroy

router = APIRouter(prefix="/api/deploy", tags=["deployment"])

_TERMINAL_STATUSES = {"succeeded", "failed", "destroyed"}


def _to_response(d: Deployment) -> DeploymentResponse:
    return DeploymentResponse(
        id=d.id,
        status=d.status,
        workflow_name=d.workflow_name,
        resource_count=d.resource_count,
        created_at=d.created_at,
        started_at=d.started_at,
        completed_at=d.completed_at,
    )


@router.post("/apply", response_model=DeploymentResponse, status_code=status.HTTP_202_ACCEPTED)
async def deploy_apply(
    request: DeployRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start a deployment. Returns immediately with deployment_id; runs terraform in background."""
    workflow_state_dict: Optional[dict] = None
    workflow_name = request.workflow_name or "Unnamed Workflow"

    if request.workflow_id:
        wf = db.query(Workflow).filter(
            Workflow.id == request.workflow_id,
            Workflow.user_id == current_user.id,
        ).first()
        if not wf:
            raise HTTPException(status_code=404, detail="Workflow not found")
        workflow_state_dict = wf.workflow_state
        workflow_name = wf.name
    elif request.workflow:
        workflow_state_dict = request.workflow if isinstance(request.workflow, dict) else request.workflow.model_dump()
    else:
        raise HTTPException(status_code=400, detail="Provide workflow_id or workflow")

    # Validate workflow state parses correctly before queuing
    try:
        WorkflowState(**workflow_state_dict)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid workflow state: {e}")

    # Create deployment record
    deployment = Deployment(
        user_id=current_user.id,
        workflow_id=request.workflow_id,
        workflow_name=workflow_name,
        status="pending",
    )
    db.add(deployment)
    db.commit()
    db.refresh(deployment)

    # Run in thread pool — doesn't block the event loop
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, run_deployment, deployment.id, workflow_state_dict, current_user.id)

    return _to_response(deployment)


@router.get("/", response_model=List[DeploymentResponse])
def list_deployments(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    deployments = (
        db.query(Deployment)
        .filter(Deployment.user_id == current_user.id)
        .order_by(Deployment.created_at.desc())
        .limit(50)
        .all()
    )
    return [_to_response(d) for d in deployments]


@router.get("/{deployment_id}", response_model=DeploymentResponse)
def get_deployment(
    deployment_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    d = db.query(Deployment).filter(
        Deployment.id == deployment_id,
        Deployment.user_id == current_user.id,
    ).first()
    if not d:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return _to_response(d)


@router.get("/{deployment_id}/logs", response_model=DeploymentLogsResponse)
def get_deployment_logs(
    deployment_id: int,
    after_id: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    deployment = db.query(Deployment).filter(
        Deployment.id == deployment_id,
        Deployment.user_id == current_user.id,
    ).first()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    logs = (
        db.query(DeploymentLog)
        .filter(
            DeploymentLog.deployment_id == deployment_id,
            DeploymentLog.id > after_id,
        )
        .order_by(DeploymentLog.id.asc())
        .limit(200)
        .all()
    )

    return DeploymentLogsResponse(
        logs=[DeploymentLogItem.model_validate(l) for l in logs],
        has_more=False,
        deployment_status=deployment.status,
    )


@router.post("/destroy-all", status_code=status.HTTP_202_ACCEPTED)
async def destroy_all_deployments(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Destroy all active (succeeded/failed) deployments for the current user."""
    active = (
        db.query(Deployment)
        .filter(
            Deployment.user_id == current_user.id,
            Deployment.status.in_(["succeeded", "failed"]),
        )
        .all()
    )
    if not active:
        return {"message": "No active deployments to destroy", "count": 0}

    loop = asyncio.get_event_loop()
    for deployment in active:
        deployment.status = "destroying"
        db.commit()
        loop.run_in_executor(None, run_destroy, deployment.id, current_user.id)

    return {"message": f"Destroying {len(active)} deployment(s)", "count": len(active)}


@router.post("/{deployment_id}/destroy", response_model=DeploymentResponse, status_code=status.HTTP_202_ACCEPTED)
async def destroy_deployment(
    deployment_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    deployment = db.query(Deployment).filter(
        Deployment.id == deployment_id,
        Deployment.user_id == current_user.id,
    ).first()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    if deployment.status not in {"succeeded", "failed"}:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot destroy deployment with status '{deployment.status}'"
        )

    deployment.status = "destroying"
    db.commit()
    db.refresh(deployment)

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, run_destroy, deployment.id, current_user.id)

    return _to_response(deployment)
