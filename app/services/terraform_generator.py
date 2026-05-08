"""
Terraform HCL generator — schema-driven.

Attribute generation is backed by the full AWS provider schema loaded via
:mod:`app.services.aws_schema`.  The schema tells us:

  * which attributes exist for every ``aws_*`` resource
  * whether each attribute is required / optional / computed-only
  * the attribute type (string, number, bool, list, set, map …)

Cross-resource references (e.g. ``vpc_id``, ``subnet_id``) are resolved by
:data:`REFERENCE_ATTRIBUTE_MAP` — a single place that maps terraform attribute
names to the node type they reference, replacing the old per-resource ``elif``
chains.

Adding a new resource to :data:`RESOURCE_MAPPING` is now sufficient — no
generator changes required.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.schemas.workflow import WorkflowNode, WorkflowState
from app.services.aws_schema import get_aws_schema

# ---------------------------------------------------------------------------
# Output definitions per Terraform resource type
#
# Each entry: (output_suffix, terraform_attribute, description)
# The generated output name is  <resource_name>_<output_suffix>
# ---------------------------------------------------------------------------
RESOURCE_OUTPUTS: Dict[str, List[Tuple[str, str, str]]] = {
    "aws_instance": [
        ("id",         "id",          "EC2 instance ID"),
        ("public_ip",  "public_ip",   "Public IP address"),
        ("private_ip", "private_ip",  "Private IP address"),
    ],
    "aws_vpc": [
        ("id",   "id",         "VPC ID"),
        ("cidr", "cidr_block", "VPC CIDR block"),
    ],
    "aws_subnet": [
        ("id", "id", "Subnet ID"),
    ],
    "aws_security_group": [
        ("id", "id", "Security group ID"),
    ],
    "aws_internet_gateway": [
        ("id", "id", "Internet gateway ID"),
    ],
    "aws_route_table": [
        ("id", "id", "Route table ID"),
    ],
    "aws_nat_gateway": [
        ("id", "id", "NAT gateway ID"),
    ],
    "aws_lb": [
        ("dns_name", "dns_name", "Load balancer DNS name"),
        ("arn",      "arn",      "Load balancer ARN"),
    ],
    "aws_s3_bucket": [
        ("name", "id",  "S3 bucket name"),
        ("arn",  "arn", "S3 bucket ARN"),
    ],
    "aws_efs_file_system": [
        ("id",       "id",       "EFS file system ID"),
        ("dns_name", "dns_name", "EFS DNS name"),
    ],
    "aws_ebs_volume": [
        ("id", "id", "EBS volume ID"),
    ],
    "aws_db_instance": [
        ("endpoint", "endpoint", "RDS endpoint"),
        ("port",     "port",     "RDS port"),
    ],
    "aws_dynamodb_table": [
        ("name", "id",  "DynamoDB table name"),
        ("arn",  "arn", "DynamoDB table ARN"),
    ],
    "aws_sns_topic": [
        ("arn", "arn", "SNS topic ARN"),
    ],
    "aws_sqs_queue": [
        ("url", "url", "SQS queue URL"),
        ("arn", "arn", "SQS queue ARN"),
    ],
    "aws_iam_role": [
        ("arn",  "arn",  "IAM role ARN"),
        ("name", "name", "IAM role name"),
    ],
    "aws_lambda_function": [
        ("name", "function_name", "Lambda function name"),
        ("arn",  "arn",           "Lambda function ARN"),
    ],
    "aws_cloudfront_distribution": [
        ("domain_name", "domain_name", "CloudFront domain name"),
        ("id",          "id",          "CloudFront distribution ID"),
    ],
    "aws_autoscaling_group": [
        ("name", "name", "Auto scaling group name"),
        ("arn",  "arn",  "Auto scaling group ARN"),
    ],
}

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Resource type → Terraform resource type
# ---------------------------------------------------------------------------
RESOURCE_MAPPING: Dict[str, str] = {
    "ec2":            "aws_instance",
    "lambda":         "aws_lambda_function",
    "autoscaling":    "aws_autoscaling_group",
    "vpc":            "aws_vpc",
    "subnet":         "aws_subnet",
    "securitygroup":  "aws_security_group",
    "internetgateway":"aws_internet_gateway",
    "routetable":     "aws_route_table",
    "natgateway":     "aws_nat_gateway",
    "eip":            "aws_eip",
    "loadbalancer":   "aws_lb",
    "s3":             "aws_s3_bucket",
    "efs":            "aws_efs_file_system",
    "ebs":            "aws_ebs_volume",
    "rds":            "aws_db_instance",
    "dbsubnetgroup":  "aws_db_subnet_group",
    "dynamodb":       "aws_dynamodb_table",
    "sns":            "aws_sns_topic",
    "sqs":            "aws_sqs_queue",
    "iamrole":        "aws_iam_role",
    "cloudfront":     "aws_cloudfront_distribution",
}

# ---------------------------------------------------------------------------
# Dependency ordering (unchanged — determines topological sort)
# ---------------------------------------------------------------------------
RESOURCE_DEPENDENCIES: Dict[str, List[str]] = {
    "subnet":         ["vpc"],
    "securitygroup":  ["vpc"],
    "internetgateway":["vpc"],
    "routetable":     ["vpc"],
    "natgateway":     ["subnet", "eip"],
    "ec2":            ["subnet", "securitygroup"],
    "loadbalancer":   ["subnet", "securitygroup"],
    "rds":            ["subnet", "securitygroup", "dbsubnetgroup"],
    "efs":            ["subnet", "securitygroup"],
    "ebs":            ["subnet"],
}

# ---------------------------------------------------------------------------
# Reference attribute map
#
# Maps a terraform attribute name to (our_node_type, referenced_attr, is_list).
#
#   our_node_type   — key in RESOURCE_MAPPING (e.g. "vpc", "subnet")
#   referenced_attr — "id" or "arn" or "name"
#   is_list         — True when the attribute expects a list/set of references
#
# When the generator encounters one of these attributes in a resource's schema,
# it searches the workflow for a connected (or available) node of that type and
# emits the proper HCL reference expression instead of a literal value.
# ---------------------------------------------------------------------------
REFERENCE_ATTRIBUTE_MAP: Dict[str, Tuple[str, str, bool]] = {
    "vpc_id":                    ("vpc",            "id",   False),
    "subnet_id":                 ("subnet",          "id",   False),
    "subnet_ids":                ("subnet",          "id",   True),
    "subnets":                   ("subnet",          "id",   True),
    "vpc_zone_identifier":       ("subnet",          "id",   True),
    "db_subnet_group_name":      ("dbsubnetgroup",   "name", False),
    "security_group_ids":        ("securitygroup",   "id",   True),
    "vpc_security_group_ids":    ("securitygroup",   "id",   True),
    "role":                      ("iamrole",         "arn",  False),
    "role_arn":                  ("iamrole",         "arn",  False),
    "execution_role_arn":        ("iamrole",         "arn",  False),
    "iam_instance_profile":      ("iamrole",         "name", False),
    "internet_gateway_id":       ("internetgateway", "id",   False),
    "route_table_id":            ("routetable",      "id",   False),
    "nat_gateway_id":            ("natgateway",      "id",   False),
    "load_balancer_arn":         ("loadbalancer",    "arn",  False),
    "instance_id":               ("ec2",             "id",   False),
    "allocation_id":             ("eip",             "id",   False),
}

# ---------------------------------------------------------------------------
# Config key aliases
#
# Maps a terraform attribute name to an ordered list of frontend config keys
# that might carry its value.  The generator also auto-derives a "nodeXxx"
# camelCase key (e.g. instance_type → nodeInstanceType) and tries the raw
# attribute name, so this table only needs entries for irregular names.
# ---------------------------------------------------------------------------
CONFIG_KEY_ALIASES: Dict[str, List[str]] = {
    "ami":                        ["nodeAmiId", "ami"],
    "availability_zone":          ["nodeAz", "availability_zone"],
    "cidr_block":                 ["nodeCidr", "cidr_block"],
    "instance_class":             ["nodeInstanceClass", "instance_class"],
    "load_balancer_type":         ["nodeLbType", "load_balancer_type"],
    "performance_mode":           ["nodePerformanceMode", "performance_mode"],
    "volume_type":                ["nodeVolumeType", "volume_type"],
    "billing_mode":               ["nodeBillingMode", "billing_mode"],
    "hash_key":                   ["nodeHashKey", "hash_key"],
    "assume_role_policy":         ["nodeAssumeRolePolicy", "assume_role_policy"],
    "identifier":                 ["nodeName", "identifier"],
    "creation_token":             ["nodeName", "creation_token"],
    "function_name":              ["nodeName", "function_name"],
    "display_name":               ["nodeDisplayName", "display_name"],
    "visibility_timeout_seconds": ["nodeVisibilityTimeout"],
    "message_retention_seconds":  ["nodeRetentionPeriod"],
    "min_size":                   ["nodeMinSize", "min_size"],
    "max_size":                   ["nodeMaxSize", "max_size"],
    "desired_capacity":           ["nodeDesiredCapacity", "desired_capacity"],
    "price_class":                ["nodePriceClass", "price_class"],
    "engine":                     ["nodeEngine", "engine"],
    "runtime":                    ["nodeRuntime", "runtime"],
    "handler":                    ["nodeHandler", "handler"],
    "domain_name":                ["nodeOrigin", "origin", "domain_name"],
}

# Special value transformations applied after the raw config value is found.
CONFIG_TRANSFORMS: Dict[str, Any] = {
    # SQS: frontend stores days, Terraform expects seconds
    "message_retention_seconds": lambda v: int(v) * 86400,
    # LB: frontend stores "internal"/"internet-facing", TF expects bool
    "internal": lambda v: v == "internal",
}

# ---------------------------------------------------------------------------
# Resource defaults
#
# HCL value strings (already formatted, ready to insert) for required
# attributes that cannot be resolved from config or references.
# ---------------------------------------------------------------------------
RESOURCE_DEFAULTS: Dict[str, Dict[str, str]] = {
    "aws_instance": {
        "ami":           "data.aws_ami.amazon_linux_2.id",
        "instance_type": '"t2.micro"',
    },
    "aws_vpc": {
        "cidr_block": '"10.0.0.0/16"',
    },
    "aws_subnet": {
        "cidr_block": '"10.0.1.0/24"',
    },
    "aws_db_instance": {
        "allocated_storage": "20",
        "storage_type":      '"gp2"',
        "username":          '"admin"',
        "password":          '"changeme"',
        "engine":            '"mysql"',
        "instance_class":    '"db.t2.micro"',
    },
    "aws_lambda_function": {
        "filename": '"lambda_function.zip"',
        "runtime":  '"python3.9"',
        "handler":  '"index.handler"',
        "role":     "aws_iam_role.lambda_role.arn",
    },
    "aws_lb": {
        "load_balancer_type": '"application"',
        "internal":           "false",
    },
    "aws_dynamodb_table": {
        "billing_mode": '"PAY_PER_REQUEST"',
    },
    "aws_efs_file_system": {
        "performance_mode": '"generalPurpose"',
    },
    "aws_ebs_volume": {
        "size":        "100",
        "volume_type": '"gp3"',
    },
    "aws_autoscaling_group": {
        "min_size":         "1",
        "max_size":         "10",
        "desired_capacity": "2",
    },
    "aws_security_group": {
        "description": '"Security group"',
    },
    "aws_iam_role": {
        "assume_role_policy": (
            'jsonencode({\n'
            '    Version = "2012-10-17"\n'
            '    Statement = [{\n'
            '      Action    = "sts:AssumeRole"\n'
            '      Effect    = "Allow"\n'
            '      Principal = { Service = "lambda.amazonaws.com" }\n'
            '    }]\n'
            '  })'
        ),
    },
}

# ---------------------------------------------------------------------------
# Block templates
#
# Default content for nested blocks that either are required by the schema
# (min_items > 0) or are practically always needed.
# Keys: terraform_type → block_name → list of inner HCL lines.
# ---------------------------------------------------------------------------
BLOCK_TEMPLATES: Dict[str, Dict[str, List[str]]] = {
    # aws_security_group ingress/egress handled dynamically in _generate_nested_blocks
    # so CIDR can be taken from user config or defaulted to 0.0.0.0/0
    "aws_cloudfront_distribution": {
        "restrictions": [
            "geo_restriction {",
            '  restriction_type = "none"',
            "}",
        ],
        "viewer_certificate": [
            "cloudfront_default_certificate = true",
        ],
        # default_cache_behavior emitted dynamically in _generate_nested_blocks
        # so target_origin_id matches the origin block's origin_id
    },
}

# Attributes to always skip (computed system fields)
_SKIP_ATTRS = frozenset({"id", "tags_all", "arn"})

# Node types that require a subnet (and thus trigger scaffold injection)
_SUBNET_DEPENDENT_TYPES = frozenset({"ec2", "rds", "loadbalancer", "efs", "ebs"})

# Synthetic node IDs injected when no VPC/subnet exists in the workflow
_SCAFFOLD_IDS = frozenset({
    "__scaffold_vpc__",
    "__scaffold_subnet__",
    "__scaffold_subnet_2__",
    "__scaffold_eip__",
    "__scaffold_db_subnet_group__",
})


class TerraformGenerator:
    """Generate Terraform HCL code from a workflow state using the AWS provider schema."""

    def __init__(self, suffix: str = "") -> None:
        self.nodes: Dict[str, WorkflowNode] = {}
        self._schema = get_aws_schema()
        self._suffix = suffix  # appended to nodeName values to ensure unique AWS resource names

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def generate_files(self, workflow_state: WorkflowState) -> Dict[str, str]:
        """
        Generate all Terraform project files.

        Returns an ordered dict of filename → content:
            versions.tf     – terraform{} block + provider block
            variables.tf    – variable declarations
            main.tf         – resource blocks only
            outputs.tf      – output blocks for every resource
            terraform.tfvars – concrete variable values
        """
        self.nodes = {n.id: n for n in workflow_state.nodes}
        self._inject_scaffold_nodes()
        dependency_order = self._get_dependency_order()

        return {
            "versions.tf":      self._generate_versions_tf(),
            "variables.tf":     self._generate_variables_tf(workflow_state),
            "main.tf":          self._generate_main_tf(dependency_order),
            "outputs.tf":       self._generate_outputs_tf(),
            "terraform.tfvars": self._generate_tfvars(workflow_state),
        }

    def generate(self, workflow_state: WorkflowState) -> str:
        """
        Return all files concatenated as one string.
        Used by the validation endpoint which expects a single HCL string.
        """
        files = self.generate_files(workflow_state)
        # versions + variables + main is enough for `terraform validate`
        parts = []
        for name in ("versions.tf", "variables.tf", "main.tf"):
            parts.append(f"# === {name} ===\n{files[name]}")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Per-file generators
    # ------------------------------------------------------------------

    def _generate_versions_tf(self) -> str:
        return (
            '# Terraform configuration generated by CloudKraft\n\n'
            'terraform {\n'
            '  required_version = ">= 1.0"\n'
            '  required_providers {\n'
            '    aws = {\n'
            '      source  = "hashicorp/aws"\n'
            '      version = "~> 5.0"\n'
            '    }\n'
            '  }\n'
            '}\n\n'
            'provider "aws" {\n'
            '  region = var.aws_region\n'
            '}\n'
        )

    def _generate_variables_tf(self, workflow_state: WorkflowState) -> str:
        # Detect the region from any node config that has nodeRegion set
        region = "us-east-1"
        for node in workflow_state.nodes:
            r = (node.config or {}).get("nodeRegion")
            if r:
                region = r
                break

        lines: List[str] = [
            'variable "aws_region" {',
            '  description = "AWS region to deploy resources"',
            '  type        = string',
            f'  default     = "{region}"',
            '}',
            '',
        ]
        return "\n".join(lines)

    def _generate_main_tf(self, dependency_order: List[str]) -> str:
        blocks: List[str] = []

        # Prepend data source for latest Amazon Linux 2 AMI when any EC2 instance
        # is present and has no explicit AMI ID configured by the user.
        needs_ami_data = any(
            self.nodes[nid].type == "ec2"
            and not self._get_config_value("ami", self.nodes[nid].config)
            for nid in dependency_order
            if nid in self.nodes
        )
        if needs_ami_data:
            blocks.append(
                'data "aws_ami" "amazon_linux_2" {\n'
                "  most_recent = true\n"
                '  owners      = ["amazon"]\n'
                "\n"
                "  filter {\n"
                '    name   = "name"\n'
                '    values = ["amzn2-ami-hvm-*-x86_64-gp2"]\n'
                "  }\n"
                "}\n"
            )

        # Scaffold VPC block (auto-generated when no VPC exists in workflow)
        if "__scaffold_vpc__" in self.nodes:
            blocks.append(
                'resource "aws_vpc" "cloudkraft_vpc" {\n'
                '  cidr_block           = "10.0.0.0/16"\n'
                '  enable_dns_hostnames = true\n'
                '  enable_dns_support   = true\n'
                '  tags = { Name = "cloudkraft-vpc" }\n'
                '}\n'
            )

        # Scaffold Subnet block (auto-generated when no subnet exists in workflow)
        if "__scaffold_subnet__" in self.nodes:
            vpc_ref = (
                self._find_resource_reference("vpc", self.nodes["__scaffold_subnet__"], "id")
                or "aws_vpc.cloudkraft_vpc.id"
            )
            blocks.append(
                'resource "aws_subnet" "cloudkraft_subnet" {\n'
                f'  vpc_id                  = {vpc_ref}\n'
                '  cidr_block              = "10.0.1.0/24"\n'
                '  map_public_ip_on_launch = true\n'
                '  tags = { Name = "cloudkraft-subnet" }\n'
                '}\n'
            )

        # Scaffold EIP block (auto-generated when NAT Gateway exists but no EIP on canvas)
        if "__scaffold_eip__" in self.nodes:
            blocks.append(
                'resource "aws_eip" "nat_eip" {\n'
                '  domain = "vpc"\n'
                '  tags   = { Name = "nat-eip" }\n'
                '}\n'
            )

        # Scaffold second subnet (auto-generated when ALB exists with only 1 subnet)
        if "__scaffold_subnet_2__" in self.nodes:
            vpc_ref = (
                self._find_resource_reference("vpc", self.nodes["__scaffold_subnet_2__"], "id")
                or "aws_vpc.cloudkraft_vpc.id"
            )
            blocks.append(
                'resource "aws_subnet" "cloudkraft_subnet_2" {\n'
                f'  vpc_id                  = {vpc_ref}\n'
                '  cidr_block              = "10.0.2.0/24"\n'
                '  availability_zone       = "us-east-1b"\n'
                '  map_public_ip_on_launch = true\n'
                '  tags = { Name = "cloudkraft-subnet-2" }\n'
                '}\n'
            )

        # Scaffold DB Subnet Group (auto-generated when RDS exists without one on canvas)
        if "__scaffold_db_subnet_group__" in self.nodes:
            # Collect all subnet references in the workflow
            subnet_refs = [
                self._ref_expr(n, "id")
                for n in self.nodes.values()
                if n.type == "subnet"
            ]
            if not subnet_refs:
                subnet_refs = ["aws_subnet.cloudkraft_subnet.id"]
            subnet_ids_hcl = ", ".join(subnet_refs)
            blocks.append(
                'resource "aws_db_subnet_group" "rds_subnet_group" {\n'
                '  name       = "rds-subnet-group"\n'
                f'  subnet_ids = [{subnet_ids_hcl}]\n'
                '  tags       = { Name = "rds-subnet-group" }\n'
                '}\n'
            )

        for node_id in dependency_order:
            if node_id in _SCAFFOLD_IDS:
                continue  # already emitted above
            node = self.nodes[node_id]
            block = self._generate_resource_block(node)
            if block:
                blocks.append(block)
                blocks.append("\n")
        return "\n".join(blocks)

    def _generate_outputs_tf(self) -> str:
        lines: List[str] = []
        found_any = False

        for node_id in self._get_dependency_order():
            node = self.nodes[node_id]
            terraform_type = RESOURCE_MAPPING.get(node.type)
            if not terraform_type or terraform_type not in RESOURCE_OUTPUTS:
                continue

            resource_name = self._get_resource_name(node)
            for suffix, attr, desc in RESOURCE_OUTPUTS[terraform_type]:
                output_name = f"{resource_name}_{suffix}"
                ref = f"{terraform_type}.{resource_name}.{attr}"
                lines += [
                    f'output "{output_name}" {{',
                    f'  description = "{desc} ({resource_name})"',
                    f'  value       = {ref}',
                    "}",
                    "",
                ]
                found_any = True

        if not found_any:
            lines.append("")

        return "\n".join(lines)

    def _generate_tfvars(self, workflow_state: WorkflowState) -> str:
        region = "us-east-1"
        for node in workflow_state.nodes:
            r = (node.config or {}).get("nodeRegion")
            if r:
                region = r
                break

        return f'aws_region = "{region}"\n'

    # ------------------------------------------------------------------
    # Scaffold injection
    # ------------------------------------------------------------------

    def _inject_scaffold_nodes(self) -> None:
        """
        Inject synthetic nodes so reference resolution produces valid HCL
        when expected resources are absent from the workflow.
        """
        # VPC + Subnet scaffold: needed when compute nodes exist but no subnet
        has_subnet = any(n.type == "subnet" for n in self.nodes.values())
        needs_subnet = any(n.type in _SUBNET_DEPENDENT_TYPES for n in self.nodes.values())

        if needs_subnet and not has_subnet:
            has_vpc = any(n.type == "vpc" for n in self.nodes.values())

            if not has_vpc:
                self.nodes["__scaffold_vpc__"] = WorkflowNode(
                    id="__scaffold_vpc__",
                    type="vpc",
                    position={"x": 0, "y": 0},
                    config={"nodeName": "cloudkraft_vpc"},
                    connections=[],
                )

            self.nodes["__scaffold_subnet__"] = WorkflowNode(
                id="__scaffold_subnet__",
                type="subnet",
                position={"x": 0, "y": 0},
                config={"nodeName": "cloudkraft_subnet"},
                connections=[],
            )

        # EIP scaffold: public NAT Gateways require allocation_id (Elastic IP).
        # Inject a synthetic EIP so the reference resolves without user placing one on canvas.
        # Skip if user manually provided allocation_id in the NAT gateway config.
        has_natgateway = any(n.type == "natgateway" for n in self.nodes.values())
        has_eip = any(n.type == "eip" for n in self.nodes.values())
        has_manual_allocation = any(
            n.type == "natgateway" and (
                (n.config or {}).get("allocation_id") or (n.config or {}).get("nodeAllocationId")
            )
            for n in self.nodes.values()
        )
        if has_natgateway and not has_eip and not has_manual_allocation:
            self.nodes["__scaffold_eip__"] = WorkflowNode(
                id="__scaffold_eip__",
                type="eip",
                position={"x": 0, "y": 0},
                config={"nodeName": "nat_eip", "domain": "vpc"},
                connections=[],
            )

        # Second subnet scaffold: ALB requires ≥2 subnets in different AZs.
        has_lb = any(n.type == "loadbalancer" for n in self.nodes.values())
        subnet_count = sum(1 for n in self.nodes.values() if n.type == "subnet")
        if has_lb and subnet_count == 1:
            self.nodes["__scaffold_subnet_2__"] = WorkflowNode(
                id="__scaffold_subnet_2__",
                type="subnet",
                position={"x": 0, "y": 0},
                config={"nodeName": "cloudkraft_subnet_2", "nodeAz": "us-east-1b"},
                connections=[],
            )

        # DB Subnet Group scaffold: RDS requires aws_db_subnet_group, not a raw subnet ID.
        has_rds = any(n.type == "rds" for n in self.nodes.values())
        has_db_subnet_group = any(n.type == "dbsubnetgroup" for n in self.nodes.values())
        if has_rds and not has_db_subnet_group:
            self.nodes["__scaffold_db_subnet_group__"] = WorkflowNode(
                id="__scaffold_db_subnet_group__",
                type="dbsubnetgroup",
                position={"x": 0, "y": 0},
                config={"nodeName": "rds_subnet_group"},
                connections=[],
            )

    # ------------------------------------------------------------------
    # Dependency ordering (topological sort)
    # ------------------------------------------------------------------

    def _get_dependency_order(self) -> List[str]:
        graph: Dict[str, List[str]] = {nid: [] for nid in self.nodes}
        in_degree: Dict[str, int] = {nid: 0 for nid in self.nodes}

        for node_id, node in self.nodes.items():
            for dep_type in RESOURCE_DEPENDENCIES.get(node.type, []):
                for other_id, other in self.nodes.items():
                    if other.type == dep_type and other_id != node_id:
                        if node_id not in graph[other_id]:
                            graph[other_id].append(node_id)
                            in_degree[node_id] += 1

            for conn_id in node.connections:
                if conn_id in self.nodes and node_id not in graph[conn_id]:
                    graph[conn_id].append(node_id)
                    in_degree[node_id] += 1

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        result: List[str] = []
        while queue:
            nid = queue.pop(0)
            result.append(nid)
            for dep in graph[nid]:
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    queue.append(dep)

        # any remaining (cycles / isolated)
        for nid in self.nodes:
            if nid not in result:
                result.append(nid)

        return result

    # ------------------------------------------------------------------
    # Resource block generation
    # ------------------------------------------------------------------

    def _generate_resource_block(self, node: WorkflowNode) -> Optional[str]:
        terraform_type = RESOURCE_MAPPING.get(node.type)
        if not terraform_type:
            return None

        resource_name = self._get_resource_name(node)
        config = dict(node.config or {})
        if self._suffix and config.get("nodeName"):
            config["nodeName"] = str(config["nodeName"]) + self._suffix

        lines = [f'resource "{terraform_type}" "{resource_name}" {{']

        # Schema-driven flat attributes
        for attr_line in self._generate_flat_attributes(terraform_type, config, node):
            lines.append(f"  {attr_line}")

        # Nested block types
        for block_line in self._generate_nested_blocks(terraform_type, config, node):
            lines.append(f"  {block_line}")

        lines.append("}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Flat attribute generation (schema-driven)
    # ------------------------------------------------------------------

    def _generate_flat_attributes(
        self,
        terraform_type: str,
        config: Dict[str, Any],
        node: WorkflowNode,
    ) -> List[str]:
        """
        Iterate the schema attributes for *terraform_type* and emit HCL lines.

        Resolution order for each attribute
        ------------------------------------
        1. Reference resolution via REFERENCE_ATTRIBUTE_MAP
        2. Config value (CONFIG_KEY_ALIASES + auto-derived camelCase key)
        3. RESOURCE_DEFAULTS
        4. Placeholder comment for required attributes with no value
        """
        lines: List[str] = []
        schema = self._schema

        if not schema.is_known_resource(terraform_type):
            # Schema unavailable — emit whatever the frontend sent
            return self._generate_attributes_from_config_only(config)

        attrs = schema.attributes(terraform_type)
        defaults = RESOURCE_DEFAULTS.get(terraform_type, {})

        for attr_name, attr_def in attrs.items():
            if attr_name in _SKIP_ATTRS:
                continue
            if schema.is_computed_only(terraform_type, attr_name):
                continue

            # 1. Reference attribute
            if attr_name in REFERENCE_ATTRIBUTE_MAP:
                # subnets / vpc_zone_identifier for ALB/ASG: collect ALL subnet refs
                if attr_name in ("subnets", "vpc_zone_identifier", "subnet_ids"):
                    all_refs = self._find_all_resource_references("subnet", node, "id")
                    if all_refs:
                        lines.append(f'{attr_name} = [{", ".join(all_refs)}]')
                        continue
                ref_line = self._resolve_reference_attr(attr_name, node)
                if ref_line:
                    lines.append(ref_line)
                    continue
                # If unresolvable but in defaults, fall through to step 3

            # 2. Config value
            value = self._get_config_value(attr_name, config)
            if value is not None:
                attr_type = schema.attr_type(terraform_type, attr_name)
                lines.append(f"{attr_name} = {self._format_hcl_value(value, attr_type)}")
                continue

            # 3. Default
            if attr_name in defaults:
                lines.append(f"{attr_name} = {defaults[attr_name]}")
                continue

            # 4. Required with no value → placeholder
            if attr_def.get("required"):
                lines.append(f'# {attr_name} = "" # REQUIRED')

        # Tags: emit if nodeName is set and resource supports tags
        if "tags" in attrs and not schema.is_computed_only(terraform_type, "tags"):
            name = config.get("nodeName") or config.get("name")
            if name:
                lines.append(f'tags = {{ Name = "{name}" }}')

        return lines

    # ------------------------------------------------------------------
    # Nested block generation
    # ------------------------------------------------------------------

    def _generate_nested_blocks(
        self,
        terraform_type: str,
        config: Dict[str, Any],
        node: WorkflowNode,
    ) -> List[str]:
        """
        Emit required / templated nested blocks (block_types in the schema).

        Priority
        --------
        1. Block template from BLOCK_TEMPLATES (opinionated defaults)
        2. Resource-specific dynamic blocks built from config
        3. Placeholder comment for schema-required blocks with no template
        """
        lines: List[str] = []
        schema = self._schema
        templates = BLOCK_TEMPLATES.get(terraform_type, {})
        block_type_defs = schema.block_types(terraform_type) if schema.is_known_resource(terraform_type) else {}

        # Emit templated blocks first
        for block_name, inner_lines in templates.items():
            lines.append(f"{block_name} {{")
            for inner in inner_lines:
                # inner lines may already be multi-line (e.g. nested geo_restriction)
                for sub in inner.split("\n"):
                    lines.append(f"  {sub}")
            lines.append("}")

        # Resource-specific dynamic blocks not covered by templates
        if terraform_type == "aws_dynamodb_table":
            hash_key = self._get_config_value("hash_key", config) or "id"
            lines += [
                "attribute {",
                f'  name = "{hash_key}"',
                '  type = "S"',
                "}",
            ]

        if terraform_type == "aws_security_group":
            import ipaddress
            # Resolve ingress CIDR: user config → validate → fallback 0.0.0.0/0
            raw_cidr = (
                config.get("nodeIngressCidr")
                or config.get("nodeCidr")
                or config.get("cidr_blocks")
                or config.get("ingressCidr")
            )
            if raw_cidr:
                try:
                    ipaddress.ip_network(str(raw_cidr), strict=False)
                    ingress_cidr = str(raw_cidr)
                except ValueError:
                    ingress_cidr = "0.0.0.0/0"
            else:
                ingress_cidr = "0.0.0.0/0"

            lines += [
                "ingress {",
                '  description = "HTTP"',
                "  from_port   = 80",
                "  to_port     = 80",
                '  protocol    = "tcp"',
                f'  cidr_blocks = ["{ingress_cidr}"]',
                "}",
                "ingress {",
                '  description = "HTTPS"',
                "  from_port   = 443",
                "  to_port     = 443",
                '  protocol    = "tcp"',
                f'  cidr_blocks = ["{ingress_cidr}"]',
                "}",
                "ingress {",
                '  description = "SSH"',
                "  from_port   = 22",
                "  to_port     = 22",
                '  protocol    = "tcp"',
                f'  cidr_blocks = ["{ingress_cidr}"]',
                "}",
                "egress {",
                "  from_port   = 0",
                "  to_port     = 0",
                '  protocol    = "-1"',
                '  cidr_blocks = ["0.0.0.0/0"]',
                "}",
            ]

        if terraform_type == "aws_cloudfront_distribution":
            # Prefer connected S3 bucket's regional domain, fallback to config/placeholder
            s3_domain_ref = self._find_resource_reference("s3", node, "bucket_regional_domain_name")
            if s3_domain_ref:
                origin_domain_hcl = s3_domain_ref  # Terraform reference, no quotes
            else:
                raw_domain = (
                    config.get("nodeOrigin")
                    or config.get("origin")
                    or "example.com"
                )
                origin_domain_hcl = f'"{raw_domain}"'
            origin_id = config.get("nodeName") or f"cf-{node.id}"
            lines += [
                "default_cache_behavior {",
                '  viewer_protocol_policy = "redirect-to-https"',
                '  allowed_methods        = ["GET", "HEAD"]',
                '  cached_methods         = ["GET", "HEAD"]',
                f'  target_origin_id       = "{origin_id}"',
                "  forwarded_values {",
                "    query_string = false",
                '    cookies { forward = "none" }',
                "  }",
                "}",
                "origin {",
                f'  domain_name = {origin_domain_hcl}',
                f'  origin_id   = "{origin_id}"',
                "}",
            ]
            # enabled is a flat attribute but required — add here if not emitted above
            lines.append("enabled = true")

        # Schema-required blocks that have no template yet
        already_emitted = set(templates.keys()) | {
            "attribute",              # dynamodb handled above
            "ingress",                # security_group handled above
            "egress",                 # security_group handled above
            "origin",                 # cloudfront handled above
            "default_cache_behavior", # cloudfront handled above
            "restrictions",           # cloudfront template
            "viewer_certificate",     # cloudfront template
        }
        for block_name, block_def in block_type_defs.items():
            if block_name in already_emitted:
                continue
            if block_def.get("min_items", 0) > 0:
                lines += [
                    f"# {block_name} {{",
                    f"#   # Required block — please configure",
                    f"# }}",
                ]

        return lines

    # ------------------------------------------------------------------
    # Reference resolution
    # ------------------------------------------------------------------

    def _resolve_reference_attr(
        self, attr_name: str, node: WorkflowNode
    ) -> Optional[str]:
        """Return an HCL assignment line if a matching node exists in the workflow."""
        ref_info = REFERENCE_ATTRIBUTE_MAP.get(attr_name)
        if not ref_info:
            return None

        node_type, ref_attr, is_list = ref_info
        ref_expr = self._find_resource_reference(node_type, node, ref_attr)
        if not ref_expr:
            return None

        if is_list:
            return f"{attr_name} = [{ref_expr}]"
        return f"{attr_name} = {ref_expr}"

    def _find_resource_reference(
        self, resource_type: str, node: WorkflowNode, attr: str = "id"
    ) -> Optional[str]:
        """
        Search for a node of *resource_type* reachable from *node*.

        Checks direct connections first, then all nodes in the workflow.
        Returns a Terraform reference expression such as ``aws_vpc.my_vpc.id``.
        """
        # Direct connections take priority
        for conn_id in node.connections:
            connected = self.nodes.get(conn_id)
            if connected and connected.type == resource_type:
                return self._ref_expr(connected, attr)

        # Fall back to any node of that type
        for other_id, other in self.nodes.items():
            if other.type == resource_type and other_id != node.id:
                return self._ref_expr(other, attr)

        return None

    def _find_all_resource_references(
        self, resource_type: str, node: WorkflowNode, attr: str = "id"
    ) -> List[str]:
        """Return HCL reference expressions for ALL nodes of *resource_type* in the workflow."""
        seen: set = set()
        refs: List[str] = []

        # Direct connections first
        for conn_id in node.connections:
            connected = self.nodes.get(conn_id)
            if connected and connected.type == resource_type and conn_id not in seen:
                refs.append(self._ref_expr(connected, attr))
                seen.add(conn_id)

        # All other nodes of that type
        for other_id, other in self.nodes.items():
            if other.type == resource_type and other_id != node.id and other_id not in seen:
                refs.append(self._ref_expr(other, attr))
                seen.add(other_id)

        return refs

    def _ref_expr(self, node: WorkflowNode, attr: str) -> str:
        """Build a HCL reference expression, e.g. ``aws_vpc.main_vpc.id``."""
        terraform_type = RESOURCE_MAPPING.get(node.type, "")
        resource_name = self._get_resource_name(node)
        return f"{terraform_type}.{resource_name}.{attr}"

    # ------------------------------------------------------------------
    # Config value lookup
    # ------------------------------------------------------------------

    def _get_config_value(self, attr_name: str, config: Dict[str, Any]) -> Optional[Any]:
        """
        Try to find a config value for *attr_name*.

        Lookup order
        ------------
        1. Explicit aliases from CONFIG_KEY_ALIASES
        2. Auto-derived camelCase key  (``instance_type`` → ``nodeInstanceType``)
        3. Exact attribute name        (``instance_type``)
        """
        # Build candidate key list
        aliases = list(CONFIG_KEY_ALIASES.get(attr_name, []))
        auto_key = "node" + "".join(p.capitalize() for p in attr_name.split("_"))
        for candidate in ([auto_key, attr_name] if auto_key not in aliases else [attr_name]):
            if candidate not in aliases:
                aliases.append(candidate)

        for key in aliases:
            if key in config and config[key] is not None:
                value = config[key]
                transform = CONFIG_TRANSFORMS.get(attr_name)
                return transform(value) if transform else value

        return None

    # ------------------------------------------------------------------
    # HCL value formatting
    # ------------------------------------------------------------------

    def _format_hcl_value(self, value: Any, attr_type: Any = "string") -> str:
        """
        Convert a Python value to an HCL literal, guided by the schema type.

        Handles ``string``, ``number``, ``bool``, ``["list","string"]``,
        ``["set","string"]``, ``["map","string"]``.
        """
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, list):
            inner = ", ".join(self._format_hcl_value(v) for v in value)
            return f"[{inner}]"
        if isinstance(value, dict):
            pairs = ", ".join(
                f"{k} = {self._format_hcl_value(v)}" for k, v in value.items()
            )
            return f"{{ {pairs} }}"

        # Determine whether the schema type expects a non-string primitive
        type_str = str(attr_type).lower()
        if "number" in type_str or "int" in type_str:
            try:
                return str(int(value))
            except (TypeError, ValueError):
                pass
        if "bool" in type_str:
            return "true" if str(value).lower() in ("true", "1", "yes") else "false"

        return f'"{value}"'

    # ------------------------------------------------------------------
    # Fallback: config-only generation (no schema)
    # ------------------------------------------------------------------

    def _generate_attributes_from_config_only(
        self, config: Dict[str, Any]
    ) -> List[str]:
        """Emit whatever key/value pairs the frontend provided as HCL comments."""
        lines: List[str] = []
        skip = {"nodeName", "nodePosition"}
        for key, val in config.items():
            if key in skip or val is None:
                continue
            lines.append(f"# {key} = {self._format_hcl_value(val)}")
        return lines

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_resource_name(self, node: WorkflowNode) -> str:
        config = node.config or {}
        raw = (
            config.get("nodeName")
            or config.get("name")
            or node.id.replace("node-", "")
        )
        # Terraform identifiers: alphanumeric + underscores only
        return "".join(c if c.isalnum() or c == "_" else "_" for c in str(raw))


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

def generate_terraform(workflow_state: WorkflowState) -> str:
    """Return all files concatenated — used by validation endpoint."""
    return TerraformGenerator().generate(workflow_state)


def generate_terraform_files(workflow_state: WorkflowState, suffix: str = "") -> Dict[str, str]:
    """Return a dict of filename → content for all Terraform project files."""
    return TerraformGenerator(suffix=suffix).generate_files(workflow_state)
