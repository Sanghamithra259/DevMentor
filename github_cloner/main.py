import os
import uuid
import asyncio
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, HTTPException, BackgroundTasks
from contextlib import asynccontextmanager

from config import settings
from models import CloneRequest, CloneResponse
from services import (
    validate_github_url,
    clone_repository,
    cleanup_task,
    cleanup_stale_directories_worker
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure base clone directory exists before starting
    os.makedirs(settings.CLONE_BASE_DIR, exist_ok=True)
    # Start the periodic background cleanup worker
    worker_task = asyncio.create_task(cleanup_stale_directories_worker())
    yield
    # Safely cancel the worker when shutting down
    worker_task.cancel()

app = FastAPI(
    title="GitHub Repo Cloner Service",
    description="A service to temporarily clone GitHub repositories for isolated execution/analysis.",
    version="1.0.0",
    lifespan=lifespan
)

@app.post("/clone", response_model=CloneResponse)
async def clone_repo_endpoint(request: CloneRequest, background_tasks: BackgroundTasks):
    url_str = str(request.github_url)
    
    # 1. Validate the GitHub URL
    is_valid = validate_github_url(url_str)
    if not is_valid:
        raise HTTPException(
            status_code=400, 
            detail="Invalid GitHub URL or repository is inaccessible."
        )
        
    # 2. Determine TTL
    ttl_seconds = request.ttl_seconds if request.ttl_seconds is not None else settings.DEFAULT_TTL_SECONDS
    
    # 3. Create unique isolated directory
    clone_id = str(uuid.uuid4())
    dest_dir = os.path.join(settings.CLONE_BASE_DIR, clone_id)
    os.makedirs(dest_dir, exist_ok=True)
    
    # 4. Clone repository
    try:
        # Run synchronous clone operation in a threadpool to prevent blocking the event loop
        await asyncio.to_thread(clone_repository, url_str, dest_dir)
    except Exception as e:
        # Cleanup if clone fails
        import shutil
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to clone repository: {str(e)}"
        )
        
    # 5. Schedule specific cleanup task for this directory
    background_tasks.add_task(cleanup_task, dest_dir, ttl_seconds)
    
    # 6. Prepare response
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    
    return CloneResponse(
        message="Repository cloned successfully.",
        repo_path=dest_dir,
        expires_at=expires_at.isoformat()
    )
