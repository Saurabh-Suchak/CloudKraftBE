from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text
from app.config import settings
from app.database import engine, Base
from app import models
from app.api import auth, workflows, codegen, validation, ai, deploy
from app.services.terraform_runner import prewarm_plugin_cache

# Create database tables
Base.metadata.create_all(bind=engine)


def _run_column_migrations() -> None:
    """Add new columns to existing tables without dropping data."""
    inspector = inspect(engine)
    with engine.connect() as conn:
        user_cols = {c["name"] for c in inspector.get_columns("users")}
        new_user_cols = [
            ("auth_method", "VARCHAR"),
            ("role_arn",    "VARCHAR"),
            ("external_id", "TEXT"),
        ]
        for col, col_type in new_user_cols:
            if col not in user_cols:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {col_type}"))
        conn.commit()


_run_column_migrations()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Kick off terraform provider download in background so first validation is fast
    prewarm_plugin_cache()
    yield


app = FastAPI(
    title="CloudKraft API",
    description="Backend API for CloudKraft - Visual workflow designer for AWS infrastructure",
    version="1.0.0",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router)
app.include_router(workflows.router)
app.include_router(codegen.router)
app.include_router(validation.router)
app.include_router(ai.router)
app.include_router(deploy.router)


@app.get("/")
def root():
    """Root endpoint"""
    return {
        "message": "CloudKraft API",
        "version": "1.0.0",
        "docs": "/docs"
    }


@app.get("/health")
def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

