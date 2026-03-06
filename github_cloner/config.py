import os

class Settings:
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", None)
    CLONE_BASE_DIR = os.getenv("CLONE_BASE_DIR", "/tmp/github_clones")
    DEFAULT_TTL_SECONDS = int(os.getenv("DEFAULT_TTL_SECONDS", 3600))

settings = Settings()
