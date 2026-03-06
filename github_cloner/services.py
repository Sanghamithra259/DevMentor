import os
import shutil
import time
import asyncio
import httpx
from git import Repo
from config import settings

def validate_github_url(url: str) -> bool:
    """
    Validates a GitHub URL using the GitHub API.
    Returns True if the repository exists and is accessible.
    """
    url_str = str(url)
    if not url_str.startswith("https://github.com/"):
        return False
        
    parts = url_str.rstrip("/").split("/")
    if len(parts) < 5:
        return False
    
    owner = parts[-2]
    repo = parts[-1]
    
    if repo.endswith(".git"):
        repo = repo[:-4]
    
    api_url = f"https://api.github.com/repos/{owner}/{repo}"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "FastAPI-GitHub-Cloner"
    }
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"
        
    try:
        response = httpx.get(api_url, headers=headers, timeout=10.0)
        return response.status_code == 200
    except httpx.RequestError as e:
        print(f"Request error while validating GitHub URL: {e}")
        return False

def clone_repository(url: str, dest_dir: str):
    """
    Clones the GitHub repository into the destination directory.
    Uses GitPython under the hood.
    """
    if not os.path.exists(dest_dir):
        os.makedirs(dest_dir)
        
    Repo.clone_from(str(url), dest_dir)

async def cleanup_task(directory: str, ttl_seconds: int):
    """
    Background task to delete the cloned directory after its initial TTL expires.
    """
    await asyncio.sleep(ttl_seconds)
    if os.path.exists(directory):
        try:
            shutil.rmtree(directory)
            print(f"Successfully cleaned up: {directory}")
        except Exception as e:
            print(f"Failed to clean up {directory}: {e}")

async def cleanup_stale_directories_worker():
    """
    A long-running periodic worker that cleans up stale clones from disk in case 
    the server restarts or cleanup_task was preempted.
    """
    while True:
        try:
            base_dir = settings.CLONE_BASE_DIR
            default_ttl = settings.DEFAULT_TTL_SECONDS
            
            if os.path.exists(base_dir):
                current_time = time.time()
                for item in os.listdir(base_dir):
                    item_path = os.path.join(base_dir, item)
                    if os.path.isdir(item_path):
                        mtime = os.path.getmtime(item_path)
                        # Check if it has outlived its TTL
                        if current_time - mtime > default_ttl:
                            try:
                                shutil.rmtree(item_path)
                                print(f"Worker cleaned up stale directory: {item_path}")
                            except Exception as cleanup_err:
                                print(f"Worker error cleaning up {item_path}: {cleanup_err}")
        except Exception as e:
            print(f"Error in background cleanup worker: {e}")
            
        await asyncio.sleep(300) # Check every 5 minutes
