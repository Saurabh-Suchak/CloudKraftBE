from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.sql import func
from app.database import Base


class RevokedToken(Base):
    """JTI blocklist — tokens added here are rejected even before expiry.

    Inserted when a user changes their password.  Rows older than the token
    TTL can be purged by a maintenance job.
    """
    __tablename__ = "revoked_tokens"

    jti = Column(String, primary_key=True)
    revoked_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)


class AuditLog(Base):
    """Append-only record of security-relevant operations."""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action = Column(String, nullable=False)      # e.g. "login", "aws_connect", "deploy_apply"
    resource_type = Column(String, nullable=True)  # e.g. "deployment", "workflow"
    resource_id = Column(Integer, nullable=True)
    ip_address = Column(String, nullable=True)
    details = Column(Text, nullable=True)        # JSON-encoded extra context
    created_at = Column(DateTime(timezone=True), server_default=func.now())
