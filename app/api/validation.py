from fastapi import APIRouter, Depends
from app.schemas.codegen import ValidationRequest, ValidationResponse
from app.services.terraform_validator import validate_terraform
from app.api.auth import get_current_user
from app.models.user import User

router = APIRouter(prefix="/api/validation", tags=["validation"])


@router.post("/validate", response_model=ValidationResponse)
def validate_code(
    request: ValidationRequest,
    current_user: User = Depends(get_current_user)
):
    """Validate Terraform code"""
    result = validate_terraform(request.terraform_code)
    
    return ValidationResponse(
        valid=result["valid"],
        errors=result["errors"],
        warnings=result["warnings"]
    )

