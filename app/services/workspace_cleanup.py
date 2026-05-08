"""F-023: Periodic cleanup of stale Terraform workspaces.

Called from the lifespan startup hook so it runs once on server boot.
Workspaces older than WORKSPACE_MAX_AGE_DAYS that belong to terminal
deployments (succeeded/failed/destroyed) are removed from disk.
"""

import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

WORKSPACE_MAX_AGE_DAYS = 7


def cleanup_stale_workspaces() -> None:
    """Delete workspace directories for terminal deployments older than the max age."""
    from app.database import SessionLocal
    from app.models.deployment import Deployment
    from app.services.terraform_deployer import WORKSPACES_DIR

    if not WORKSPACES_DIR.exists():
        return

    cutoff = datetime.now(timezone.utc) - timedelta(days=WORKSPACE_MAX_AGE_DAYS)

    db = SessionLocal()
    try:
        stale = (
            db.query(Deployment)
            .filter(
                Deployment.status.in_(["succeeded", "failed", "destroyed"]),
                Deployment.completed_at < cutoff,
                Deployment.workspace_path.isnot(None),
            )
            .all()
        )

        removed = 0
        for deployment in stale:
            workspace = Path(deployment.workspace_path)
            if workspace.exists() and workspace.is_dir():
                try:
                    shutil.rmtree(workspace)
                    deployment.workspace_path = None
                    removed += 1
                    logger.info("Cleaned up workspace for deployment %d", deployment.id)
                except Exception as exc:
                    logger.warning("Failed to remove workspace %s: %s", workspace, exc)

        if removed:
            db.commit()
            logger.info("Workspace cleanup: removed %d stale workspace(s)", removed)

    except Exception as exc:
        logger.exception("Workspace cleanup failed: %s", exc)
    finally:
        db.close()
