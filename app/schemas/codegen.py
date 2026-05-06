from pydantic import BaseModel
from typing import List, Optional, Dict, Any


class TerraformFile(BaseModel):
    filename: str
    content: str


class CodeGenerationRequest(BaseModel):
    workflow_id: Optional[int] = None
    workflow: Optional[Dict[str, Any]] = None  # WorkflowState as dict


class CodeGenerationResponse(BaseModel):
    terraform_code: str
    files: List[TerraformFile] = []


class CostLineItem(BaseModel):
    resource: str
    resource_type: str
    monthly_usd_low: float
    monthly_usd_high: float
    notes: str


class CostEstimateResponse(BaseModel):
    total_monthly_low: float
    total_monthly_high: float
    line_items: List[CostLineItem]
    disclaimer: str


class ValidationError(BaseModel):
    type: str  # "syntax", "schema", "policy"
    severity: str  # "error", "warning"
    message: str
    line: Optional[int] = None
    column: Optional[int] = None
    resource: Optional[str] = None


class ValidationRequest(BaseModel):
    terraform_code: str = ""
    # Optional: pass the full set of generated files for real terraform validate
    files: List[TerraformFile] = []


class ValidationResponse(BaseModel):
    valid: bool
    errors: List[ValidationError] = []
    warnings: List[ValidationError] = []
    # Which validator was used and its version
    method: str = "static"               # "terraform" | "static"
    validator_version: Optional[str] = None

