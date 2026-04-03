"""
Lightweight AWS cost estimator.

Uses us-east-1 on-demand pricing ranges (as of 2025) to give approximate
monthly costs without requiring an external API like Infracost.
All figures are estimates — actual costs depend on usage patterns.
"""

from typing import List, Dict, Any
from app.schemas.codegen import CostLineItem, CostEstimateResponse
from app.schemas.workflow import WorkflowState

# (monthly_low_usd, monthly_high_usd, notes)
# Ranges capture common instance sizes / usage levels
_COST_TABLE: Dict[str, tuple] = {
    # Compute
    "ec2": (
        8.0, 150.0,
        "t3.micro ~$8/mo, t3.medium ~$30/mo, m5.large ~$70/mo (on-demand, us-east-1)",
    ),
    "lambda": (
        0.0, 20.0,
        "First 1M requests free; $0.20 per 1M thereafter. Cost depends heavily on invocation frequency.",
    ),
    "autoscaling": (
        16.0, 500.0,
        "Cost is driven by the underlying EC2 instances in the group (min × instance price).",
    ),
    # Networking
    "vpc":            (0.0,   0.0,  "VPC itself is free; charges apply to NAT Gateways, VPN, data transfer."),
    "subnet":         (0.0,   0.0,  "Subnets are free."),
    "securitygroup":  (0.0,   0.0,  "Security groups are free."),
    "internetgateway":(0.0,   0.0,  "Internet Gateway is free; data transfer out costs ~$0.09/GB."),
    "routetable":     (0.0,   0.0,  "Route tables are free."),
    "natgateway":     (32.0, 50.0,  "$0.045/hr (~$32/mo) + $0.045/GB data processed."),
    "loadbalancer":   (16.0, 25.0,  "ALB: ~$0.022/LCU-hr + $0.008/hr. Estimated for low-moderate traffic."),
    # Storage
    "s3":     (0.5,  23.0,  "$0.023/GB/mo (Standard). Free tier: 5 GB. Cost scales with data volume."),
    "efs":    (3.0,  30.0,  "$0.30/GB/mo (Standard). Scales with stored data."),
    "ebs":    (8.0,  80.0,  "gp3: $0.08/GB/mo. 100 GB ~$8/mo, 1 TB ~$80/mo."),
    # Database
    "rds":      (13.0, 200.0, "db.t3.micro ~$13/mo, db.m5.large ~$120/mo (single-AZ, MySQL/PostgreSQL)."),
    "dynamodb": (0.0,  25.0,  "On-demand: $1.25 per million writes, $0.25 per million reads. Free tier: 25 GB."),
    # Messaging
    "sns": (0.0, 5.0,  "First 1M publishes free; $0.50/M thereafter. Email delivery $2/100K."),
    "sqs": (0.0, 5.0,  "First 1M requests/mo free; $0.40/M thereafter."),
    # Security & IAM
    "iamrole":    (0.0, 0.0, "IAM roles are free."),
    # CDN
    "cloudfront": (0.0, 50.0, "First 1 TB/mo free. $0.0085/GB thereafter (us-east-1). Scales with traffic."),
}


def estimate_cost(workflow_state: WorkflowState) -> CostEstimateResponse:
    line_items: List[CostLineItem] = []
    total_low = 0.0
    total_high = 0.0

    from app.services.terraform_generator import RESOURCE_MAPPING

    for node in workflow_state.nodes:
        entry = _COST_TABLE.get(node.type)
        if entry is None:
            continue
        low, high, notes = entry
        resource_name = (node.config or {}).get("nodeName") or node.id
        terraform_type = RESOURCE_MAPPING.get(node.type, node.type)

        line_items.append(CostLineItem(
            resource=resource_name,
            resource_type=terraform_type,
            monthly_usd_low=low,
            monthly_usd_high=high,
            notes=notes,
        ))
        total_low += low
        total_high += high

    return CostEstimateResponse(
        total_monthly_low=round(total_low, 2),
        total_monthly_high=round(total_high, 2),
        line_items=line_items,
        disclaimer=(
            "Estimates are based on us-east-1 on-demand pricing and typical usage. "
            "Actual costs depend on instance sizes, data transfer, storage volume, "
            "and request rates. Use the AWS Pricing Calculator for precise quotes."
        ),
    )
