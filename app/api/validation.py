import logging

from fastapi import APIRouter, Depends

from app.api.auth import get_current_user
from app.models.user import User
from app.schemas.codegen import ValidationRequest, ValidationResponse
from app.services.terraform_runner import (
    is_terraform_available,
    run_terraform_validate,
    terraform_version,
)
from app.services.terraform_validator import validate_terraform

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/validation", tags=["validation"])


@router.post("/validate", response_model=ValidationResponse)
def validate_code(
    request: ValidationRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Validate Terraform code.

    If the request includes `files[]` AND the terraform binary is available,
    runs real `terraform validate`. Otherwise falls back to the static
    regex-based validator.
    """
    # ── Real terraform validate ───────────────────────────────────────────────
    if request.files and is_terraform_available():
        try:
            files_dict = {f.filename: f.content for f in request.files}
            result = run_terraform_validate(files_dict)
            return ValidationResponse(
                valid=result["valid"],
                errors=result["errors"],
                warnings=result["warnings"],
                method=result.get("method", "terraform"),
                validator_version=result.get("validator_version"),
            )
        except Exception as exc:
            logger.warning(
                "Real terraform validate failed (%s), falling back to static validator",
                exc,
            )

    # ── Static fallback ───────────────────────────────────────────────────────
    code = request.terraform_code
    if not code and request.files:
        # Combine files into one string for static validator
        code = "\n".join(f.content for f in request.files)

    result = validate_terraform(code)
    return ValidationResponse(
        valid=result["valid"],
        errors=result["errors"],
        warnings=result["warnings"],
        method="static",
        validator_version=None,
    )


@router.get("/status")
def validator_status(_: User = Depends(get_current_user)):
    """Return which validator is active and its version."""
    tf_available = is_terraform_available()
    return {
        "terraform_available": tf_available,
        "terraform_version": terraform_version() if tf_available else None,
        "static_validator": True,
        "active_method": "terraform" if tf_available else "static",
    }
