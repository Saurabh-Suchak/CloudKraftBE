"""
Real Terraform validation using the terraform binary.

Strategy:
  1. A "warm workspace" at app/data/terraform_warm_workspace/ is initialised once
     (at server startup via prewarm_plugin_cache()).  This downloads the AWS provider
     (~200 MB) into app/data/terraform_plugin_cache/ and leaves a valid .terraform/
     directory behind.
  2. For every validation request, we copy .terraform/ + .terraform.lock.hcl from
     the warm workspace into a fresh temp dir, then run only `terraform validate -json`.
     No provider download → typically <2 s per validation.
  3. If the warm workspace is not yet ready (first boot, still downloading), we fall
     back to running `terraform init` in the temp dir with a generous timeout.

Falls back gracefully to the static validator if the binary is not available.
"""

import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.schemas.codegen import ValidationError

logger = logging.getLogger(__name__)

# Persistent plugin cache — provider binaries live here after first download
PLUGIN_CACHE_DIR = Path(__file__).parent.parent / "data" / "terraform_plugin_cache"

# Pre-initialised workspace — .terraform/ is copied from here for each validation
WARM_WORKSPACE_DIR = Path(__file__).parent.parent / "data" / "terraform_warm_workspace"

# Minimal config that pulls in the AWS provider (same major version users get)
_MINIMAL_VERSIONS_TF = """\
terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region                      = "us-east-1"
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
  access_key                  = "mock_access_key"
  secret_key                  = "mock_secret_key"
}
"""

# Resolved once at import time
_TERRAFORM_BIN: Optional[str] = shutil.which("terraform")

# Lock so only one prewarm runs at a time
_prewarm_lock = threading.Lock()


def is_terraform_available() -> bool:
    return _TERRAFORM_BIN is not None


def terraform_version() -> Optional[str]:
    if not is_terraform_available():
        return None
    try:
        r = subprocess.run(
            [_TERRAFORM_BIN, "version", "-json"],
            capture_output=True, text=True, timeout=10,
        )
        data = json.loads(r.stdout)
        return data.get("terraform_version")
    except Exception:
        return None


def _warm_workspace_ready() -> bool:
    """True if the warm workspace has been successfully initialised."""
    return (WARM_WORKSPACE_DIR / ".terraform").exists()


def _build_tf_env() -> Dict[str, str]:
    env = os.environ.copy()
    env["TF_PLUGIN_CACHE_DIR"] = str(PLUGIN_CACHE_DIR)
    env["TF_INPUT"] = "false"
    env["TF_CLI_ARGS"] = ""
    env["TF_LOG"] = ""
    env["CHECKPOINT_DISABLE"] = "1"
    return env


def prewarm_plugin_cache() -> None:
    """
    Initialise the warm workspace in a background thread so the AWS provider
    is cached before the first real validation request arrives.

    Safe to call multiple times — subsequent calls are no-ops if the workspace
    is already ready.
    """
    if not is_terraform_available():
        logger.info("Terraform binary not found — skipping prewarm")
        return

    def _run() -> None:
        with _prewarm_lock:
            if _warm_workspace_ready():
                logger.info("Warm workspace already initialised — skipping prewarm")
                return

            logger.info("Prewarming Terraform plugin cache (AWS provider download may take a few minutes)…")
            WARM_WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
            PLUGIN_CACHE_DIR.mkdir(parents=True, exist_ok=True)

            versions_file = WARM_WORKSPACE_DIR / "versions.tf"
            versions_file.write_text(_MINIMAL_VERSIONS_TF, encoding="utf-8")

            # Remove any stale .terraform dir so init starts clean
            stale = WARM_WORKSPACE_DIR / ".terraform"
            if stale.exists():
                shutil.rmtree(stale)

            env = _build_tf_env()
            result = subprocess.run(
                [
                    _TERRAFORM_BIN, "init",
                    "-backend=false",
                    "-no-color",
                    "-input=false",
                ],
                cwd=str(WARM_WORKSPACE_DIR),
                capture_output=True,
                text=True,
                timeout=600,   # 10 minutes — generous for first download
                env=env,
            )

            if result.returncode == 0:
                logger.info("Terraform warm workspace ready ✓")
            else:
                err = _strip_ansi((result.stderr or result.stdout or "").strip())
                logger.error("Terraform prewarm failed: %s", err)
                # Remove partial .terraform so we retry next time
                if stale.exists():
                    shutil.rmtree(stale, ignore_errors=True)

    thread = threading.Thread(target=_run, daemon=True, name="tf-prewarm")
    thread.start()


def run_terraform_validate(files: Dict[str, str]) -> Dict[str, Any]:
    """
    Validate a set of Terraform files using the real terraform binary.

    Args:
        files: mapping of filename → HCL content, e.g.
               {"main.tf": "...", "versions.tf": "...", ...}

    Returns:
        dict with keys: valid, errors, warnings, method, validator_version
    """
    if not is_terraform_available():
        raise RuntimeError("terraform binary not found")

    PLUGIN_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    tmpdir = tempfile.mkdtemp(prefix="cloudkraft_validate_")
    try:
        # Write user files into the temp directory
        for filename, content in files.items():
            (Path(tmpdir) / filename).write_text(content, encoding="utf-8")

        env = _build_tf_env()

        # ── Fast path: copy warm workspace so we can skip terraform init ─────
        if _warm_workspace_ready():
            try:
                warm_tf = WARM_WORKSPACE_DIR / ".terraform"
                dest_tf = Path(tmpdir) / ".terraform"
                shutil.copytree(str(warm_tf), str(dest_tf), symlinks=True)

                warm_lock = WARM_WORKSPACE_DIR / ".terraform.lock.hcl"
                if warm_lock.exists():
                    shutil.copy2(str(warm_lock), str(Path(tmpdir) / ".terraform.lock.hcl"))

                logger.debug("Copied warm workspace — skipping terraform init")
                # Jump straight to validate
                return _run_validate_only(tmpdir, env)
            except Exception as copy_err:
                logger.warning("Failed to copy warm workspace (%s) — falling back to init", copy_err)
                # Clean up any partial copy and fall through to the slow path
                dest = Path(tmpdir) / ".terraform"
                if dest.exists():
                    shutil.rmtree(dest, ignore_errors=True)

        # ── Slow path: run terraform init (first boot or copy failed) ────────
        logger.info("Running terraform init in temp dir (provider may download)")
        init = subprocess.run(
            [
                _TERRAFORM_BIN, "init",
                "-backend=false",
                "-no-color",
                "-input=false",
            ],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=600,   # 10 minutes
            env=env,
        )

        if init.returncode != 0:
            error_text = _strip_ansi((init.stderr or init.stdout or "unknown init error").strip())
            return {
                "valid": False,
                "errors": [ValidationError(
                    type="syntax", severity="error",
                    message=f"terraform init failed: {error_text}",
                    line=0,
                )],
                "warnings": [],
                "method": "terraform",
                "validator_version": terraform_version(),
            }

        return _run_validate_only(tmpdir, env)

    except subprocess.TimeoutExpired as exc:
        logger.error("Terraform validation timed out: %s", exc)
        return {
            "valid": False,
            "errors": [ValidationError(
                type="syntax", severity="error",
                message=(
                    "Terraform validation timed out while downloading the AWS provider. "
                    "The download is running in the background — please retry in a minute."
                ),
                line=0,
            )],
            "warnings": [],
            "method": "terraform",
            "validator_version": None,
        }
    except Exception:
        logger.exception("Unexpected error during terraform validation")
        raise
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _run_validate_only(tmpdir: str, env: Dict[str, str]) -> Dict[str, Any]:
    """Run `terraform validate -json` in an already-initialised tmpdir."""
    validate = subprocess.run(
        [_TERRAFORM_BIN, "validate", "-json", "-no-color"],
        cwd=tmpdir,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )

    raw = validate.stdout.strip() or validate.stderr.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "valid": False,
            "errors": [ValidationError(
                type="syntax", severity="error",
                message=f"Could not parse terraform validate output: {raw[:300]}",
                line=0,
            )],
            "warnings": [],
            "method": "terraform",
            "validator_version": terraform_version(),
        }

    errors: List[ValidationError] = []
    warnings: List[ValidationError] = []

    for diag in data.get("diagnostics", []):
        severity = diag.get("severity", "error")
        summary  = diag.get("summary", "")
        detail   = diag.get("detail", "")
        rng      = diag.get("range") or {}
        start    = rng.get("start") or {}
        line     = start.get("line", 0)
        filename = rng.get("filename", "")

        message = f"{summary}: {detail}" if detail else summary

        resource: Optional[str] = None
        snippet = diag.get("snippet") or {}
        context = snippet.get("context", "")
        if context:
            resource = context

        item = ValidationError(
            type="schema",
            severity=severity,
            message=message,
            line=line,
            resource=resource or (filename if filename else None),
        )
        if severity == "error":
            errors.append(item)
        else:
            warnings.append(item)

    return {
        "valid": data.get("valid", len(errors) == 0),
        "errors": errors,
        "warnings": warnings,
        "method": "terraform",
        "validator_version": terraform_version(),
    }


def _strip_ansi(text: str) -> str:
    import re
    return re.sub(r"\x1b\[[0-9;]*m", "", text)
