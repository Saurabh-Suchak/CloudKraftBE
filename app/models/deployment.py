from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Deployment(Base):
    __tablename__ = "deployments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=True)
    workflow_name = Column(String, nullable=True)
    status = Column(String, default="pending")  # pending|running|succeeded|failed|destroying|destroyed
    workspace_path = Column(String, nullable=True)
    terraform_state = Column(Text, nullable=True)
    resource_count = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    owner = relationship("User", foreign_keys=[user_id])
    logs = relationship("DeploymentLog", back_populates="deployment", cascade="all, delete-orphan", order_by="DeploymentLog.id")


class DeploymentLog(Base):
    __tablename__ = "deployment_logs"

    id = Column(Integer, primary_key=True, index=True)
    deployment_id = Column(Integer, ForeignKey("deployments.id"), nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    level = Column(String, default="info")  # info|success|error|warning
    message = Column(Text, nullable=False)

    deployment = relationship("Deployment", back_populates="logs")
