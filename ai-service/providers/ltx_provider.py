"""
LTX Video Provider — refactored sesuai ticket PM.

CATATAN AUDIO:
- ltx-2-fast, ltx-2-pro  : TIDAK support audio native (model lama)
- ltx-2-3-fast, ltx-2-3-pro : SUPPORT audio native (model baru, recommended)

Gunakan ltx-2-3-pro atau ltx-2-3-fast untuk video dengan audio.

FIX AUDIO CUTOFF:
- Payload WAJIB menyertakan 'audio_length' yang sama nilainya dengan 'duration'
- Tanpa audio_length, LTX akan memotong audio lebih awal dari durasi video
- Max duration dibatasi 12 detik untuk menjaga kualitas audio native
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from .base import VideoProvider, VideoRequest, VideoResponse
from .http_client import APIError, build_http_session, safe_post

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Konstanta
# ---------------------------------------------------------------------------

LTX_BASE_URL = "https://api.ltx.video/v1"

SUPPORTED_MODELS = {
    "ltx-2-fast":  {"max_duration": 12, "max_fps": 30, "audio_native": False},
    "ltx-2-pro":   {"max_duration": 12, "max_fps": 30, "audio_native": False},
    "ltx-2-3-fast":{"max_duration": 12, "max_fps": 30, "audio_native": True},
    "ltx-2-3-pro": {"max_duration": 12, "max_fps": 30, "audio_native": True},
}

# Durasi maksimum global — batas atas untuk semua model
MAX_DURATION_GLOBAL = 12

RATIO_MAP = {
    "16:9":  "1920x1080",
    "9:16":  "1080x1920",
    "1:1":   "1080x1080",
    "4:3":   "1440x1080",
}


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

class LTXProvider(VideoProvider):
    """
    LTX Video generation provider.

    Ticket PM — LTX Client Setup:
    - HTTP session dengan retry dan timeout dikonfigurasi via build_http_session()
    - API key divalidasi saat init
    - Payload ditransformasi ke structured format
    """

    def __init__(
        self,
        api_key: str,
        model: str = "ltx-2-fast",
        resolution: Optional[str] = None,
        fps: int = 25,
        generate_audio: bool = True,
        request_timeout: int = 300,
    ):
        if not api_key or not api_key.strip():
            raise ValueError("LTX_API_KEY tidak boleh kosong")

        model = model.strip().lower()
        if model not in SUPPORTED_MODELS:
            logger.warning(
                "Model '%s' tidak ada di daftar supported models %s. Melanjutkan.",
                model, list(SUPPORTED_MODELS.keys())
            )

        self._api_key = api_key
        self._model = model
        self._fps = fps
        self._generate_audio = generate_audio
        self._timeout = request_timeout
        self._session = build_http_session()

        # Resolusi: dari parameter atau default berdasarkan constraint nanti
        self._default_resolution = resolution or "1920x1080"

    # ------------------------------------------------------------------
    # Contract implementation
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return f"ltx:{self._model}"

    def generate(self, request: VideoRequest, output_path: str) -> VideoResponse:
        """
        Main entry point. Transformasi VideoRequest → LTX payload → kirim → simpan.

        Ticket PM — Payload Mapping:
          instruction → digunakan untuk validasi task_type
          input       → prompt teks
          context     → metadata tambahan
          constraints → duration, resolution, fps
          routing     → task_type dan fallback
        """
        logger.info("[LTX] START route=%s output=%s", self.name, output_path)
        logger.debug("[LTX] Request: instruction=%s routing=%s", request.instruction, request.routing)

        # Validasi task type
        task_type = request.routing.get("task_type", request.instruction)
        if task_type != "text_to_video":
            logger.warning(
                "[LTX] task_type='%s' tidak optimal untuk LTX, akan dilanjutkan sebagai text_to_video",
                task_type
            )

        # Bangun payload LTX dari structured request
        ltx_payload = self._build_payload(request)
        logger.info("[LTX] Payload built model=%s duration=%s", ltx_payload["model"], ltx_payload.get("duration"))

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            resp = safe_post(
                session=self._session,
                url=f"{LTX_BASE_URL}/text-to-video",
                headers=headers,
                payload=ltx_payload,
                timeout=self._timeout,
            )
        except APIError as e:
            logger.error("[LTX] API call failed: %s", e)
            return VideoResponse.failure(route_used=self.name, error=str(e))

        # Simpan binary response
        try:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(resp.content)
            logger.info("[LTX] Video saved path=%s size=%d bytes", output_path, len(resp.content))
        except OSError as e:
            return VideoResponse.failure(route_used=self.name, error=f"Gagal simpan file: {e}")

        return VideoResponse.success(
            route_used=self.name,
            result={
                "output_path": output_path,
                "model": self._model,
                "duration": ltx_payload.get("duration"),
                "resolution": ltx_payload.get("resolution"),
                "fps": ltx_payload.get("fps"),
                "audio": self._generate_audio,
                "file_size_bytes": len(resp.content),
            },
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_payload(self, request: VideoRequest) -> Dict[str, Any]:
        """
        Ticket PM — Core Implementation: transformasi VideoRequest ke LTX payload.

        Mengambil nilai dari constraints, bukan dari flat attribute,
        sesuai structured format yang ditentukan.

        FIX AUDIO CUTOFF:
        'audio_length' HARUS sama dengan 'duration' agar audio tidak terpotong.
        LTX API menggunakan audio_length secara terpisah untuk menentukan panjang
        audio yang di-generate; tanpa ini audio akan dipotong lebih awal.
        """
        constraints = request.constraints

        # Resolusi: dari constraints atau default
        ratio = constraints.get("ratio", "16:9")
        resolution = constraints.get("resolution") or RATIO_MAP.get(ratio, self._default_resolution)

        duration = int(constraints.get("duration", 10))
        fps = int(constraints.get("fps", self._fps))

        # Klip duration ke batas model
        model_info = SUPPORTED_MODELS.get(self._model, {})
        max_dur = model_info.get("max_duration", MAX_DURATION_GLOBAL)
        if duration > max_dur:
            logger.warning("[LTX] duration=%d melebihi max=%d, di-clamp ke %d.", duration, max_dur, max_dur)
            duration = max_dur

        # Pastikan tidak melebihi batas global
        if duration > MAX_DURATION_GLOBAL:
            logger.warning("[LTX] duration=%d melebihi MAX_DURATION_GLOBAL=%d, di-clamp.", duration, MAX_DURATION_GLOBAL)
            duration = MAX_DURATION_GLOBAL

        payload: Dict[str, Any] = {
            "prompt": request.input,
            "model": self._model,
            "duration": duration,
            "resolution": resolution,
            "fps": fps,
            "generate_audio": self._generate_audio,
            # FIX AUDIO CUTOFF: audio_length HARUS sama dengan duration
            # Tanpa parameter ini, LTX memotong audio sebelum video selesai
            "audio_length": duration,
        }

        # Tambahkan context jika ada metadata relevan
        if request.context:
            # Misal: style_override, negative_prompt, seed
            if "negative_prompt" in request.context:
                payload["negative_prompt"] = request.context["negative_prompt"]
            if "seed" in request.context:
                payload["seed"] = request.context["seed"]

        logger.debug(
            "[LTX] Payload audio fix: duration=%d audio_length=%d generate_audio=%s",
            duration, duration, self._generate_audio
        )

        return payload