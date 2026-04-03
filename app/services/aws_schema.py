"""
AWS Terraform Provider Schema Loader

Loads the full AWS provider schema (10 000+ resources) from a local cache.
If no cache exists it generates one via `terraform providers schema -json`.

Usage
-----
    from app.services.aws_schema import get_aws_schema

    schema = get_aws_schema()
    attrs  = schema.attributes("aws_instance")   # dict of attr_name → definition
    blocks = schema.block_types("aws_instance")   # dict of block_name → definition
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from typing import Any, Dict, Optional, Set

logger = logging.getLogger(__name__)

# The schema JSON is cached here after the first `terraform providers schema` run.
# Committed path is app/data/ — the JSON file itself should be git-ignored (large).
_SCHEMA_CACHE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "aws_provider_schema.json"
)

_TERRAFORM_MAIN_TF = """\
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}
"""

# Module-level singleton
_instance: Optional[AwsProviderSchema] = None


def get_aws_schema() -> "AwsProviderSchema":
    """Return the module-level singleton, initialising it on first call."""
    global _instance
    if _instance is None:
        _instance = AwsProviderSchema()
    return _instance


class AwsProviderSchema:
    """
    Thin wrapper around the JSON produced by `terraform providers schema -json`.

    The schema is loaded from *_SCHEMA_CACHE_PATH*.  If the cache file does not
    exist the class tries to generate it automatically using the Terraform CLI.
    """

    def __init__(self, schema_path: str = _SCHEMA_CACHE_PATH) -> None:
        self._schema_path = schema_path
        self._resource_schemas: Dict[str, Any] = {}
        self._load()

    # ------------------------------------------------------------------
    # Initialisation helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if os.path.exists(self._schema_path):
            try:
                with open(self._schema_path) as fh:
                    raw = json.load(fh)
                self._resource_schemas = self._extract_resources(raw)
                logger.info(
                    "AWS provider schema loaded from cache: %d resources",
                    len(self._resource_schemas),
                )
                return
            except Exception as exc:
                logger.warning("Could not read cached schema (%s), regenerating…", exc)

        # Cache miss — try to generate via Terraform CLI
        try:
            raw = self._generate_via_terraform()
            self._resource_schemas = self._extract_resources(raw)
            logger.info(
                "AWS provider schema generated: %d resources",
                len(self._resource_schemas),
            )
        except Exception as exc:
            logger.warning(
                "Could not generate AWS provider schema: %s. "
                "Code generation will use config-only fallback.",
                exc,
            )

    def _extract_resources(self, raw: Dict) -> Dict[str, Any]:
        for key, val in raw.get("provider_schemas", {}).items():
            if "aws" in key:
                return val.get("resource_schemas", {})
        return {}

    def _generate_via_terraform(self) -> Dict:
        """Run `terraform init` + `terraform providers schema -json` in a temp dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "main.tf"), "w") as fh:
                fh.write(_TERRAFORM_MAIN_TF)

            logger.info("Running terraform init (this may take a minute)…")
            subprocess.run(
                ["terraform", "init", "-backend=false", "-no-color"],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                check=True,
                timeout=300,
            )

            logger.info("Running terraform providers schema -json…")
            result = subprocess.run(
                ["terraform", "providers", "schema", "-json"],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                check=True,
                timeout=60,
            )

        schema = json.loads(result.stdout)

        # Persist cache
        os.makedirs(os.path.dirname(self._schema_path), exist_ok=True)
        with open(self._schema_path, "w") as fh:
            json.dump(schema, fh)
        logger.info("Schema cached at %s", self._schema_path)

        return schema

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_known_resource(self, terraform_type: str) -> bool:
        """True if *terraform_type* exists in the loaded schema."""
        return terraform_type in self._resource_schemas

    def attributes(self, terraform_type: str) -> Dict[str, Any]:
        """
        Return the flat *attributes* dict for a resource.

        Each value is a dict with keys such as ``type``, ``required``,
        ``optional``, ``computed``, ``description``.
        """
        return (
            self._resource_schemas.get(terraform_type, {})
            .get("block", {})
            .get("attributes", {})
        )

    def block_types(self, terraform_type: str) -> Dict[str, Any]:
        """
        Return the *block_types* dict for a resource.

        Each value describes a nested block with its own ``block.attributes``
        and ``nesting_mode`` / ``min_items`` / ``max_items``.
        """
        return (
            self._resource_schemas.get(terraform_type, {})
            .get("block", {})
            .get("block_types", {})
        )

    def required_attributes(self, terraform_type: str) -> Set[str]:
        """Return the set of attribute names that are marked *required*."""
        return {
            name
            for name, defn in self.attributes(terraform_type).items()
            if defn.get("required")
        }

    def is_computed_only(self, terraform_type: str, attr_name: str) -> bool:
        """
        True when an attribute is *computed* but neither *optional* nor
        *required* — i.e. it is a read-only value populated by AWS.
        """
        defn = self.attributes(terraform_type).get(attr_name, {})
        return (
            defn.get("computed", False)
            and not defn.get("optional", False)
            and not defn.get("required", False)
        )

    def attr_type(self, terraform_type: str, attr_name: str) -> Any:
        """Return the type annotation from the schema (e.g. ``"string"``, ``["list","string"]``)."""
        return self.attributes(terraform_type).get(attr_name, {}).get("type", "string")

    def total_resources(self) -> int:
        return len(self._resource_schemas)
