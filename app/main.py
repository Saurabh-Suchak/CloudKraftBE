from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import engine, Base
from app import models
from app.api import auth, workflows, codegen, validation, ai
from app.services.terraform_runner import prewarm_plugin_cache

# Create database tables
Base.metadata.create_all(bind=engine)


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

