"""
AI Video Service — Interface utama untuk divisi backend.

Ini adalah satu-satunya class yang perlu diketahui backend dev.
Backend tidak perlu tahu tentang LTX, Runway, routing, atau retry logic.

Cara pakai (dari sisi backend):

    service = AIVideoService()

    # Submit job → dapat job_id
    job = service.submit(prompt="...", duration=10, ratio="16:9")
    print(job.job_id)  # → "550e8400-e29b-41d4-a716-446655440000"

    # Cek status
    status = service.get_status(job.job_id)
    print(status)  # → { "job_id": ..., "status": "processing" }

    # Ambil result setelah done
    result = service.get_result(job.job_id)
    print(result)  # → { "job_id": ..., "video_url": "outputs/videos/xxx.mp4" }
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from typing import Dict, Optional

# Add parent directory to Python path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from models.job import InMemoryJobStore, JobStatus, VideoJob, new_job_id
from providers import VideoRequest, build_provider, enrich_routing
from providers.http_client import APIError

logger = logging.getLogger(__name__)


class AIVideoService:
    """
    Service layer antara Backend API dan AI inference engine.

    Backend hanya perlu memanggil 3 method:
      - submit()     → POST /generate
      - get_status() → GET  /status/{job_id}
      - get_result() → GET  /result/{job_id}
    """

    def __init__(self, store: Optional[InMemoryJobStore] = None):
        self._store = store or InMemoryJobStore()
        self._video_dir = os.getenv("VIDEO_OUTPUT_DIR", "outputs/videos")
        self._base_url = os.getenv("VIDEO_BASE_URL", "")
        os.makedirs(self._video_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API — 3 method ini yang dipakai backend
    # ------------------------------------------------------------------

    def submit(
        self,
        prompt: str,
        duration: int = 10,
        ratio: str = "16:9",
        task_type: str = "text_to_video",
    ) -> VideoJob:
        """
        Submit job baru ke AI engine.
        Return langsung dengan job_id — TIDAK menunggu video selesai.

        Ini untuk endpoint: POST /generate
        """
        if not prompt or not prompt.strip():
            raise ValueError("Prompt tidak boleh kosong")
        if duration < 1 or duration > 12:
            raise ValueError("Duration harus antara 1-12 detik (max 12s untuk kualitas audio native)")
        if ratio not in ("16:9", "9:16", "1:1", "4:3"):
            raise ValueError(f"Ratio '{ratio}' tidak valid")

        job_id = new_job_id()
        job = VideoJob(
            id=job_id,
            prompt=prompt.strip(),
            duration=duration,
            ratio=ratio,
        )
        self._store.save(job)
        logger.info("[SERVICE] Job created job_id=%s", job_id)

        # Jalankan inference di background thread
        # Di production: ganti dengan Celery task / message queue
        thread = threading.Thread(
            target=self._run_inference,
            args=(job_id, prompt, duration, ratio, task_type),
            daemon=True,
        )
        thread.start()

        return job

    def get_status(self, job_id: str) -> Dict:
        """
        Cek status job.

        Return dict:
        {
            "job_id": "...",
            "status": "pending" | "processing" | "done" | "failed",
            "created_at": "...",
            "updated_at": "..."
        }

        Ini untuk endpoint: GET /status/{job_id}
        """
        job = self._get_job_or_raise(job_id)
        return {
            "job_id": job.job_id,
            "status": job.status.value,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "error": job.error if job.status == JobStatus.FAILED else None,
        }

    def get_result(self, job_id: str) -> Dict:
        """
        Ambil hasil video setelah job done.

        Return dict:
        {
            "job_id": "...",
            "status": "done",
            "video_url": "https://cdn.example.com/videos/xxx.mp4",
            "prompt": "...",
            "meta": { "provider": ..., "model": ..., "duration": ..., "ratio": ... }
        }

        Ini untuk endpoint: GET /result/{job_id}
        """
        job = self._get_job_or_raise(job_id)

        if job.status == JobStatus.FAILED:
            return {
                "job_id": job.job_id,
                "status": "failed",
                "error": job.error,
            }

        if job.status != JobStatus.DONE:
            return {
                "job_id": job.job_id,
                "status": job.status.value,
                "message": f"Video belum selesai. Status saat ini: {job.status.value}",
            }

        return {
            "job_id": job.job_id,
            "status": "done",
            "video_url": job.video_url,
            "prompt": job.prompt,
            "meta": {
                "provider": job.provider,
                "model": job.model,
                "duration": job.duration,
                "ratio": job.ratio,
            },
        }

    # ------------------------------------------------------------------
    # Internal — background inference
    # ------------------------------------------------------------------

    def _run_inference(
        self,
        job_id: str,
        prompt: str,
        duration: int,
        ratio: str,
        task_type: str,
    ) -> None:
        """
        Jalankan AI inference di background.
        Update job status di store saat selesai.
        """
        job = self._store.get(job_id)
        if not job:
            logger.error("[SERVICE] Job not found saat inference job_id=%s", job_id)
            return

        # FIX: Ganti bare 'except Exception' dengan exception spesifik
        # yang mungkin terjadi di inference pipeline
        try:
            request = VideoRequest(
                instruction=task_type,
                input=prompt,
                context={"job_id": job_id},
                constraints={
                    "duration": duration,
                    "ratio": ratio,
                    "resolution": os.getenv("LTX_RESOLUTION", "1920x1080"),
                    "fps": int(os.getenv("LTX_FPS", "25")),
                },
                routing={
                    "task_type": task_type,
                    "fallback": "ltx:ltx-2-3-fast",
                },
            )
            request = enrich_routing(request)

            provider_name = request.routing.get("resolved_provider")
            model_name = request.routing.get("resolved_model")
            provider = build_provider(provider_name, model_name)

            job.mark_processing(provider=provider.name, model=provider.name.split(":")[1])
            self._store.update(job)
            logger.info(
                "[SERVICE] Inference started job_id=%s provider=%s",
                job_id, provider.name,
            )

            safe_provider = provider.name.replace(":", "_")
            filename = f"{job_id}__{safe_provider}.mp4"
            output_path = os.path.join(self._video_dir, filename)

            response = provider.generate(request=request, output_path=output_path)

            if response.status == "success":
                video_url = (
                    f"{self._base_url}/{filename}"
                    if self._base_url
                    else output_path
                )
                job.mark_done(video_url=video_url)
                self._store.update(job)
                logger.info(
                    "[SERVICE] Job done job_id=%s video_url=%s",
                    job_id, video_url,
                )
            else:
                job.mark_failed(error=response.error or "Unknown error")
                self._store.update(job)
                logger.error(
                    "[SERVICE] Job failed job_id=%s error=%s",
                    job_id, response.error,
                )

        # FIX: Exception spesifik yang mungkin terjadi di inference
        except (APIError, TimeoutError) as exc:
            logger.error(
                "[SERVICE] Inference error job_id=%s error=%s",
                job_id, exc,
            )
            job.mark_failed(error=str(exc))
            self._store.update(job)

        except ValueError as exc:
            # ValueError: parameter tidak valid
            logger.error(
                "[SERVICE] Config error job_id=%s error=%s",
                job_id, exc,
            )
            job.mark_failed(error=str(exc))
            self._store.update(job)

        except OSError as exc:
            # OSError: gagal simpan file video
            logger.error(
                "[SERVICE] File I/O error job_id=%s error=%s",
                job_id, exc,
            )
            job.mark_failed(error=f"Gagal simpan file: {exc}")
            self._store.update(job)

    def _get_job_or_raise(self, job_id: str) -> VideoJob:
        job = self._store.get(job_id)
        if not job:
            raise KeyError(f"Job '{job_id}' tidak ditemukan")
        return job