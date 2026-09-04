"""Compatibility entrypoint. Prefer: uvicorn app.main:app --app-dir backend"""

from app.main import app

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True, app_dir="backend")
