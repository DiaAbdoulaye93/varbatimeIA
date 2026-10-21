"""Serve the built Angular app with a fallback to index.html for client-side routes."""

from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse

INDEX = "index.html"
# Paths owned by the API: never answered with the SPA.
API_PREFIXES = ("api/", "health", "docs", "redoc", "openapi.json")
# Angular emits content-hashed file names (chunk-ABC123.js): safe to cache for a year.
IMMUTABLE = "public, max-age=31536000, immutable"
NO_CACHE = "no-cache"


def mount_spa(app: FastAPI, static_dir: Path) -> None:
    root = static_dir.resolve()
    index = root / INDEX

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith(API_PREFIXES):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
        candidate = (root / path).resolve()
        # Real file inside the build folder (no path traversal), else the app shell.
        if path and candidate.is_file() and candidate.is_relative_to(root):
            cache = NO_CACHE if candidate.name == INDEX else IMMUTABLE
            return FileResponse(candidate, headers={"Cache-Control": cache})
        return FileResponse(index, headers={"Cache-Control": NO_CACHE})
