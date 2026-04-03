#!/usr/bin/env python3
"""
Pre-generate and cache the AWS provider schema.

Run once (or after upgrading the AWS provider version) to populate
app/data/aws_provider_schema.json.  The backend loads this file on startup
to drive schema-aware Terraform code generation.

Usage
-----
    cd /path/to/CloudKraftBE
    python scripts/generate_aws_schema.py

Requirements
------------
* terraform >= 1.0 must be on PATH
* Internet access (to download the hashicorp/aws provider)

The generated file is ~50 MB; add it to .gitignore unless you want
to commit it.
"""

import sys
import os

# Allow running from the repo root without installing the package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from app.services.aws_schema import AwsProviderSchema, _SCHEMA_CACHE_PATH

def main() -> None:
    # Force regeneration even if cache exists
    if os.path.exists(_SCHEMA_CACHE_PATH):
        print(f"Removing existing cache: {_SCHEMA_CACHE_PATH}")
        os.remove(_SCHEMA_CACHE_PATH)

    print("Generating AWS provider schema (this will run terraform init + providers schema)…")
    schema = AwsProviderSchema()

    if schema.total_resources() == 0:
        print("ERROR: Schema generation failed — no resources loaded.", file=sys.stderr)
        sys.exit(1)

    print(f"Done. {schema.total_resources()} resources cached at:\n  {_SCHEMA_CACHE_PATH}")

if __name__ == "__main__":
    main()
