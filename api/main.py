"""mX API — Week 1 skeleton.

Run:  uvicorn api.main:app --reload
Docs: http://127.0.0.1:8000/docs
"""
from fastapi import Depends, FastAPI, Header, HTTPException

from api.config import settings

app = FastAPI(title="mX API", version="0.1.0")


def require_key(x_mx_key: str = Header(default="")) -> None:
    """Every protected route requires the X-mX-Key header."""
    if x_mx_key != settings.mx_api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing X-mX-Key")


@app.get("/health")
def health() -> dict:
    """Public liveness check."""
    return {"status": "ok", "version": app.version}


@app.get("/whoami", dependencies=[Depends(require_key)])
def whoami() -> dict:
    """Protected route to confirm auth works. Replaced by /chat in Week 2."""
    return {
        "assistant": "mX",
        "provider": settings.primary_provider,
        "model": settings.primary_model,
        "provider_key_set": bool(settings.anthropic_api_key or settings.openai_api_key),
    }
