"""
Static Terraform HCL validator.

Checks syntax, required attributes, and security best practices without
requiring a live Terraform binary. Covers the most common CIS/Checkov rules
for AWS resources.
"""

import re
from typing import List, Dict, Any, Optional
from app.schemas.codegen import ValidationError


class TerraformValidator:
    """Validate Terraform HCL code for syntax, schema, and security compliance."""

    def __init__(self):
        self.errors: List[ValidationError] = []
        self.warnings: List[ValidationError] = []

    def validate(self, terraform_code: str) -> Dict[str, Any]:
        self.errors = []
        self.warnings = []

        self._validate_syntax(terraform_code)
        self._validate_schema(terraform_code)
        self._validate_security(terraform_code)

        return {
            "valid": len(self.errors) == 0,
            "errors": self.errors,
            "warnings": self.warnings,
        }

    # ------------------------------------------------------------------
    # Syntax
    # ------------------------------------------------------------------

    def _validate_syntax(self, code: str):
        lines = code.split("\n")

        # Balanced braces
        brace_count = 0
        for i, line in enumerate(lines, 1):
            # Skip string literals to avoid counting braces inside them
            stripped = re.sub(r'"[^"]*"', '""', line)
            brace_count += stripped.count("{") - stripped.count("}")
            if brace_count < 0:
                self.errors.append(ValidationError(
                    type="syntax", severity="error",
                    message="Unmatched closing brace",
                    line=i, column=0,
                ))

        if brace_count != 0:
            self.errors.append(ValidationError(
                type="syntax", severity="error",
                message=f"Unmatched braces: {abs(brace_count)} {'unclosed' if brace_count > 0 else 'extra closing'}",
                line=len(lines), column=0,
            ))

        # Must have at least one resource block
        if not re.search(r'resource\s+"[^"]+"\s+"[^"]+"', code):
            self.warnings.append(ValidationError(
                type="syntax", severity="warning",
                message="No resource blocks found in Terraform code",
                line=0, column=0,
            ))

        # Provider block check
        if not re.search(r'provider\s+"aws"', code):
            self.warnings.append(ValidationError(
                type="syntax", severity="warning",
                message='No AWS provider block found — ensure provider "aws" is configured',
                line=0, column=0,
            ))

    # ------------------------------------------------------------------
    # Required attribute checks per resource type
    # ------------------------------------------------------------------

    def _validate_schema(self, code: str):
        resource_pattern = r'resource\s+"([^"]+)"\s+"([^"]+)"'
        for i, line in enumerate(code.split("\n"), 1):
            m = re.search(resource_pattern, line)
            if not m:
                continue
            rtype, rname = m.group(1), m.group(2)
            block = self._extract_block(code, rtype, rname)

            dispatch = {
                "aws_instance":              self._check_ec2,
                "aws_vpc":                   self._check_vpc,
                "aws_subnet":                self._check_subnet,
                "aws_security_group":        self._check_security_group,
                "aws_s3_bucket":             self._check_s3,
                "aws_db_instance":           self._check_rds,
                "aws_lambda_function":       self._check_lambda,
                "aws_iam_role":              self._check_iam_role,
                "aws_lb":                    self._check_alb,
                "aws_dynamodb_table":        self._check_dynamodb,
                "aws_autoscaling_group":     self._check_autoscaling_group,
            }
            if rtype in dispatch:
                dispatch[rtype](block, rname, i)

    def _check_ec2(self, block: str, name: str, line: int):
        ref = f"aws_instance.{name}"
        if "instance_type" not in block:
            self.errors.append(ValidationError(
                type="schema", severity="error", line=line, resource=ref,
                message=f"EC2 instance '{name}' is missing required attribute 'instance_type'",
            ))
        if "ami" not in block:
            self.warnings.append(ValidationError(
                type="schema", severity="warning", line=line, resource=ref,
                message=f"EC2 instance '{name}' has no 'ami' — a default placeholder will be used",
            ))

    def _check_vpc(self, block: str, name: str, line: int):
        if "cidr_block" not in block:
            self.errors.append(ValidationError(
                type="schema", severity="error", line=line,
                resource=f"aws_vpc.{name}",
                message=f"VPC '{name}' is missing required attribute 'cidr_block'",
            ))

    def _check_subnet(self, block: str, name: str, line: int):
        ref = f"aws_subnet.{name}"
        if "cidr_block" not in block:
            self.errors.append(ValidationError(
                type="schema", severity="error", line=line, resource=ref,
                message=f"Subnet '{name}' is missing required attribute 'cidr_block'",
            ))
        if "vpc_id" not in block:
            self.errors.append(ValidationError(
                type="schema", severity="error", line=line, resource=ref,
                message=f"Subnet '{name}' is missing required attribute 'vpc_id'",
            ))

    def _check_security_group(self, block: str, name: str, line: int):
        if "name" not in block and "name_prefix" not in block:
            self.warnings.append(ValidationError(
                type="schema", severity="warning", line=line,
                resource=f"aws_security_group.{name}",
                message=f"Security group '{name}' should specify 'name' or 'name_prefix'",
            ))

    def _check_s3(self, block: str, name: str, line: int):
        if "bucket" not in block:
            self.warnings.append(ValidationError(
                type="schema", severity="warning", line=line,
                resource=f"aws_s3_bucket.{name}",
                message=f"S3 bucket '{name}' does not specify a 'bucket' name — AWS will auto-generate one",
            ))

    def _check_rds(self, block: str, name: str, line: int):
        ref = f"aws_db_instance.{name}"
        for attr in ("engine", "instance_class", "allocated_storage"):
            if attr not in block:
                self.errors.append(ValidationError(
                    type="schema", severity="error", line=line, resource=ref,
                    message=f"RDS instance '{name}' is missing required attribute '{attr}'",
                ))

    def _check_lambda(self, block: str, name: str, line: int):
        ref = f"aws_lambda_function.{name}"
        for attr in ("runtime", "handler", "role"):
            if attr not in block:
                self.errors.append(ValidationError(
                    type="schema", severity="error", line=line, resource=ref,
                    message=f"Lambda function '{name}' is missing required attribute '{attr}'",
                ))

    def _check_iam_role(self, block: str, name: str, line: int):
        if "assume_role_policy" not in block:
            self.errors.append(ValidationError(
                type="schema", severity="error", line=line,
                resource=f"aws_iam_role.{name}",
                message=f"IAM role '{name}' is missing required attribute 'assume_role_policy'",
            ))

    def _check_alb(self, block: str, name: str, line: int):
        if "load_balancer_type" not in block:
            self.warnings.append(ValidationError(
                type="schema", severity="warning", line=line,
                resource=f"aws_lb.{name}",
                message=f"Load balancer '{name}' should specify 'load_balancer_type' (application/network/gateway)",
            ))

    def _check_dynamodb(self, block: str, name: str, line: int):
        ref = f"aws_dynamodb_table.{name}"
        if "hash_key" not in block:
            self.errors.append(ValidationError(
                type="schema", severity="error", line=line, resource=ref,
                message=f"DynamoDB table '{name}' is missing required attribute 'hash_key'",
            ))
        if "billing_mode" not in block:
            self.warnings.append(ValidationError(
                type="schema", severity="warning", line=line, resource=ref,
                message=f"DynamoDB table '{name}' does not specify 'billing_mode' — defaults to PROVISIONED which requires capacity units",
            ))

    def _check_autoscaling_group(self, block: str, name: str, line: int):
        ref = f"aws_autoscaling_group.{name}"
        has_launch = (
            "launch_configuration" in block
            or "launch_template" in block
            or "mixed_instances_policy" in block
        )
        if not has_launch:
            self.errors.append(ValidationError(
                type="schema", severity="error", line=line, resource=ref,
                message=(
                    f"Auto Scaling group '{name}' must specify one of "
                    "'launch_configuration', 'launch_template', or 'mixed_instances_policy'"
                ),
            ))

    # ------------------------------------------------------------------
    # Security best practices (CIS / Checkov-style)
    # ------------------------------------------------------------------

    def _validate_security(self, code: str):
        self._check_hardcoded_secrets(code)
        self._check_sg_unrestricted(code)
        self._check_s3_public_acl(code)
        self._check_rds_public(code)
        self._check_ec2_public_ip(code)
        self._check_iam_wildcard(code)
        self._check_naming_conventions(code)
        self._check_default_vpc_cidr(code)

    def _check_hardcoded_secrets(self, code: str):
        patterns = [
            (r'password\s*=\s*"[^$][^"]{3,}"', "Hardcoded password detected"),
            (r'secret\s*=\s*"[^$][^"]{3,}"',   "Hardcoded secret detected"),
            (r'aws_secret_access_key\s*=\s*"[^"]{16,}"', "Hardcoded AWS secret key detected"),
        ]
        for pattern, msg in patterns:
            if re.search(pattern, code, re.IGNORECASE):
                self.warnings.append(ValidationError(
                    type="security", severity="warning", line=0,
                    message=f"{msg} — use variables or AWS Secrets Manager instead",
                ))

    def _check_sg_unrestricted(self, code: str):
        """Flag security group ingress rules open to 0.0.0.0/0 on sensitive ports."""
        sensitive_ports = {22: "SSH", 3389: "RDP", 3306: "MySQL", 5432: "PostgreSQL", 1433: "MSSQL"}
        sg_blocks = re.finditer(
            r'resource\s+"aws_security_group"\s+"([^"]+)"\s*\{(.*?)\n\}',
            code, re.DOTALL,
        )
        for sg in sg_blocks:
            sg_name = sg.group(1)
            ingress_blocks = re.finditer(
                r'ingress\s*\{([^}]*)\}', sg.group(2), re.DOTALL
            )
            for ingress in ingress_blocks:
                content = ingress.group(1)
                if "0.0.0.0/0" not in content and "::/0" not in content:
                    continue
                ports = re.findall(r'(?:from_port|to_port)\s*=\s*(\d+)', content)
                reported = set()
                for p in ports:
                    port = int(p)
                    if port in sensitive_ports and port not in reported:
                        reported.add(port)
                        self.warnings.append(ValidationError(
                            type="security", severity="warning", line=0,
                            resource=f"aws_security_group.{sg_name}",
                            message=(
                                f"Security group '{sg_name}' allows unrestricted {sensitive_ports[port]} "
                                f"access (port {port}) from 0.0.0.0/0 — restrict to known CIDRs"
                            ),
                        ))

    def _check_s3_public_acl(self, code: str):
        if re.search(r'acl\s*=\s*"public-read"', code):
            self.warnings.append(ValidationError(
                type="security", severity="warning", line=0,
                message='S3 bucket uses acl = "public-read" — ensure this is intentional and add bucket policies',
            ))
        if re.search(r'block_public_acls\s*=\s*false', code):
            self.warnings.append(ValidationError(
                type="security", severity="warning", line=0,
                message="S3 bucket has block_public_acls = false — consider enabling S3 Block Public Access",
            ))

    def _check_rds_public(self, code: str):
        if re.search(r'publicly_accessible\s*=\s*true', code):
            self.warnings.append(ValidationError(
                type="security", severity="warning", line=0,
                message="RDS instance has publicly_accessible = true — databases should not be internet-facing",
            ))
        rds_blocks = re.finditer(
            r'resource\s+"aws_db_instance"\s+"([^"]+)"\s*\{(.*?)\n\}',
            code, re.DOTALL,
        )
        for rds in rds_blocks:
            if "storage_encrypted" not in rds.group(2):
                self.warnings.append(ValidationError(
                    type="security", severity="warning", line=0,
                    resource=f"aws_db_instance.{rds.group(1)}",
                    message=f"RDS instance '{rds.group(1)}' does not enable storage_encrypted — enable encryption at rest",
                ))

    def _check_ec2_public_ip(self, code: str):
        if re.search(r'associate_public_ip_address\s*=\s*true', code):
            self.warnings.append(ValidationError(
                type="security", severity="warning", line=0,
                message="EC2 instance assigns a public IP — consider using a NAT gateway for outbound-only access",
            ))

    def _check_iam_wildcard(self, code: str):
        if re.search(r'"Action"\s*:\s*"\*"', code) or re.search(r"Action\s*=\s*\"\*\"", code):
            self.warnings.append(ValidationError(
                type="security", severity="warning", line=0,
                message="IAM policy uses wildcard Action '*' — apply least-privilege and restrict to required actions",
            ))

    def _check_naming_conventions(self, code: str):
        for name in re.findall(r'resource\s+"[^"]+"\s+"([^"]+)"', code):
            if not re.match(r'^[a-z0-9_]+$', name):
                self.warnings.append(ValidationError(
                    type="convention", severity="warning", line=0, resource=name,
                    message=f"Resource name '{name}' should use lowercase letters, numbers, and underscores only",
                ))

    def _check_default_vpc_cidr(self, code: str):
        for cidr in re.findall(r'cidr_block\s*=\s*"([^"]+)"', code):
            if cidr == "172.31.0.0/16":
                self.warnings.append(ValidationError(
                    type="convention", severity="warning", line=0,
                    message=f"CIDR '{cidr}' is the AWS default VPC range — use a custom CIDR to avoid conflicts",
                ))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_block(self, code: str, resource_type: str, resource_name: str) -> str:
        pattern = (
            rf'resource\s+"{re.escape(resource_type)}"\s+"{re.escape(resource_name)}"\s*'
            rf'\{{(.*?)\n\}}'
        )
        m = re.search(pattern, code, re.DOTALL)
        return m.group(1) if m else ""


def validate_terraform(terraform_code: str) -> Dict[str, Any]:
    return TerraformValidator().validate(terraform_code)
