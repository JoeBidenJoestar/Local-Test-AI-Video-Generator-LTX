"""
FastAPI App — AI Video Generator Service.

Endpoint yang disepakati dengan divisi backend:

  POST /generate          → submit job, return job_id
  GET  /status/{job_id}   → cek status: pending/processing/done/failed
  GET  /result/{job_id}   → ambil video_url setelah done
  GET  /health            → health check (untuk load balancer / monitoring)

Backend (Go/FastAPI lain) tinggal hit endpoint ini.
Tidak perlu tahu apapun tentang LTX, Runway, atau routing.
"""

import sys
import os
import logging

# Add current directory to Python path for imports
sys.path.insert(0, os.path.dirname(__file__))

# FIX 1: load_dotenv() dipanggil SEBELUM import local
# agar env vars sudah ter-load saat module diinisialisasi
from dotenv import load_dotenv
load_dotenv()

# FIX 2: Import local SETELAH load_dotenv() — urutan ini penting
from logging_config import setup_logging
from services.ai_video_service import AIVideoService

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

setup_logging(
    log_dir=os.getenv("LOG_DIR", "outputs/logs"),
    log_level=os.getenv("LOG_LEVEL", "INFO"),
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI Video Generator — ITS Marketing",
    description="Service untuk generate video promosi kampus menggunakan LTX / Runway ML.",
    version="1.0.0",
)

service = AIVideoService()


# ---------------------------------------------------------------------------
# Request / Response Schema
# ---------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    """Request body untuk POST /generate."""
    prompt: str = Field(
        ...,
        min_length=10,
        description="Deskripsi video yang ingin digenerate",
    )
    duration: int = Field(
        default=10,
        ge=1,
        le=12,
        description="Durasi video dalam detik (1-12). Max 12s untuk kualitas audio native LTX.",
    )
    ratio: str = Field(
        default="16:9",
        description="Aspect ratio: 16:9 | 9:16 | 1:1 | 4:3",
    )
    task_type: str = Field(
        default="text_to_video",
        description="Jenis task: text_to_video | text_to_video_hq | image_to_video",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "prompt": "Cinematic video of Institut Teknologi Sepuluh Nopember Surabaya campus at golden hour, drone shot",
                "duration": 10,
                "ratio": "16:9",
                "task_type": "text_to_video_hq",
            }
        }
    }


class GenerateResponse(BaseModel):
    """Response dari POST /generate."""
    job_id: str
    status: str
    message: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health_check():
    """Health check endpoint untuk monitoring."""
    return {"status": "ok", "service": "ai-video-generator"}


@app.post("/generate", response_model=GenerateResponse, status_code=202)
def generate_video(body: GenerateRequest):
    """
    Submit job generate video.

    - Return langsung dengan job_id (async, tidak menunggu video selesai)
    - Status awal: pending → processing → done / failed
    - Gunakan GET /status/{job_id} untuk polling status
    """
    # FIX 3: Ganti f-string logger dengan lazy % formatting
    logger.info("[API] POST /generate prompt_preview=%.60s", body.prompt)
    try:
        job = service.submit(
            prompt=body.prompt,
            duration=body.duration,
            ratio=body.ratio,
            task_type=body.task_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return GenerateResponse(
        job_id=job.job_id,
        status=job.status.value,
        message="Job diterima. Gunakan GET /status/{job_id} untuk cek progress.",
    )


@app.get("/status/{job_id}")
def get_status(job_id: str):
    """
    Cek status job.

    Response:
    {
        "job_id": "...",
        "status": "pending" | "processing" | "done" | "failed",
        "created_at": "...",
        "updated_at": "...",
        "error": null
    }
    """
    logger.debug("[API] GET /status/%s", job_id)
    try:
        return service.get_status(job_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Job '{job_id}' tidak ditemukan",
        ) from exc


@app.get("/result/{job_id}")
def get_result(job_id: str):
    """
    Ambil hasil video setelah status done.

    Response saat done:
    {
        "job_id": "...",
        "status": "done",
        "video_url": "http://127.0.0.1:8000/video/xxx.mp4",
        "prompt": "...",
        "meta": { "provider": ..., "model": ..., "duration": ..., "ratio": ... }
    }
    """
    logger.debug("[API] GET /result/%s", job_id)
    try:
        return service.get_result(job_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Job '{job_id}' tidak ditemukan",
        ) from exc


@app.get("/video/{filename}")
def serve_video(filename: str):
    """
    Serve file video langsung (untuk development).
    Di production: serve via Nginx / CDN.
    """
    video_dir = os.getenv("VIDEO_OUTPUT_DIR", "outputs/videos")
    filepath = os.path.join(video_dir, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File tidak ditemukan")
    return FileResponse(filepath, media_type="video/mp4")


# ===== RUN SERVER =====
if __name__ == "__main__":
    import uvicorn
    
    host = os.getenv("AI_SERVICE_HOST", "127.0.0.1")
    port = int(os.getenv("AI_SERVICE_PORT", "8000"))
    
    logger.info(f"Starting AI Video Service on {host}:{port}...")
    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=False,  # Disable reload for direct script execution
        log_level="info",
    )