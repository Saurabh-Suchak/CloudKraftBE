from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.models.workflow import Workflow
from app.schemas.codegen import (
    CodeGenerationRequest,
    CodeGenerationResponse,
    CostEstimateResponse,
    TerraformFile,
)
from app.schemas.workflow import WorkflowState
from app.services.terraform_generator import generate_terraform, generate_terraform_files
from app.services.cost_estimator import estimate_cost
from app.api.auth import get_current_user

router = APIRouter(prefix="/api/codegen", tags=["code-generation"])


@router.post("/generate", response_model=CodeGenerationResponse)
def generate_code(
    request: CodeGenerationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Generate Terraform code from workflow"""
    workflow_state = None
    
    if request.workflow_id:
        # Get workflow from database
        workflow = db.query(Workflow).filter(
            Workflow.id == request.workflow_id,
            Workflow.user_id == current_user.id
        ).first()
        
        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workflow not found"
            )
        
        # Convert workflow_state dict to WorkflowState model
        workflow_state = WorkflowState(**workflow.workflow_state)
    
    elif request.workflow:
        # Use provided workflow state
        workflow_state = WorkflowState(**request.workflow)
    
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either workflow_id or workflow must be provided"
        )
    
    # Generate all Terraform project files
    tf_files = generate_terraform_files(workflow_state)

    files = [
        TerraformFile(filename=name, content=content)
        for name, content in tf_files.items()
    ]

    # terraform_code = main.tf content (used by validation endpoint)
    return CodeGenerationResponse(
        terraform_code=tf_files.get("main.tf", ""),
        files=files
    )


@router.post("/estimate", response_model=CostEstimateResponse)
def estimate_workflow_cost(
    request: CodeGenerationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return a rough monthly cost estimate for the workflow resources."""
    if request.workflow_id:
        workflow = db.query(Workflow).filter(
            Workflow.id == request.workflow_id,
            Workflow.user_id == current_user.id,
        ).first()
        if not workflow:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
        workflow_state = WorkflowState(**workflow.workflow_state)
    elif request.workflow:
        workflow_state = WorkflowState(**request.workflow)
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Either workflow_id or workflow must be provided")

    return estimate_cost(workflow_state)

