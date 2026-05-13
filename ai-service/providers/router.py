"""
Backend Routing Layer — sesuai ticket PM.

Ticket PM: "Routing logic dipindahkan ke backend layer"
Ticket PM: "Pendekatan multi-model tidak digunakan"

Router ini bertanggung jawab untuk:
1. Menentukan provider dan model berdasarkan task_type
2. Menyediakan fallback jika task tidak terdefinisi
3. TIDAK menggunakan multiple model untuk satu request
"""

from __future__ import annotations

import logging
import os
from typing import Dict, Optional

from .base import VideoProvider, VideoRequest
from .ltx_provider import LTXProvider
from .runway_provider import RunwayProvider
from .wavespeed_provider import WavespeedProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Routing rules: task_type → (provider_name, model)
# ---------------------------------------------------------------------------

ROUTING_TABLE: Dict[str, Dict[str, str]] = {
    "text_to_video": {
        "provider": "ltx",
        "model": "ltx-2-3-fast",
    },
    "text_to_video_hq": {
        "provider": "ltx",
        "model": "ltx-2-3-pro",
    },
    "image_to_video": {
        "provider": "runway",
        "model": "gen4.5",
    },
    "wavespeed_veo": {
        "provider": "wavespeed",
        "model": "google/veo3.1-lite",
    },
}

FALLBACK_ROUTE = {
    "provider": "ltx",
    "model": "ltx-2-3-fast",
}


def resolve_route(task_type: str) -> Dict[str, str]:
    """
    Tentukan provider dan model berdasarkan task_type.
    Jika tidak ditemukan, gunakan fallback.
    """
    route = ROUTING_TABLE.get(task_type)
    if not route:
        logger.warning(
            "[ROUTER] task_type='%s' tidak ada di routing table. Menggunakan fallback: %s",
            task_type, FALLBACK_ROUTE
        )
        return FALLBACK_ROUTE
    logger.info("[ROUTER] task_type='%s' → provider='%s' model='%s'", task_type, route["provider"], route["model"])
    return route


def enrich_routing(request: VideoRequest) -> VideoRequest:
    """
    Inject routing info ke dalam VideoRequest jika belum ada.
    Dipanggil sebelum request dikirim ke provider.
    """
    task_type = request.routing.get("task_type") or request.instruction or "text_to_video"
    route = resolve_route(task_type)

    request.routing.update({
        "task_type": task_type,
        "resolved_provider": route["provider"],
        "resolved_model": route["model"],
        "fallback": f"{FALLBACK_ROUTE['provider']}:{FALLBACK_ROUTE['model']}",
    })
    return request


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------

def build_provider(
    provider_name: Optional[str] = None,
    model: Optional[str] = None,
) -> VideoProvider:
    """
    Factory untuk membangun provider instance berdasarkan env vars atau parameter.
    
    Urutan prioritas:
    1. Parameter langsung (provider_name, model)
    2. Environment variables (ACTIVE_PROVIDER, ACTIVE_MODEL)
    3. Fallback default (ltx:ltx-2-fast)
    """
    _provider = (provider_name or os.getenv("ACTIVE_PROVIDER", "ltx")).strip().lower()
    _model = (model or os.getenv("ACTIVE_MODEL", "")).strip()

    logger.info("[FACTORY] Building provider=%s model=%s", _provider, _model or "(default)")

    if _provider == "ltx":
        api_key = os.getenv("LTX_API_KEY", "").strip()
        if not api_key:
            raise EnvironmentError("LTX_API_KEY tidak ditemukan di environment")
        return LTXProvider(
            api_key=api_key,
            model=_model or "ltx-2-3-fast",
            fps=int(os.getenv("LTX_FPS", "25")),
            generate_audio=True,  # # ltx-2-3-x support audio native
        )

    if _provider == "runway":
        api_key = os.getenv("RUNWAY_API_KEY", "").strip()
        if not api_key:
            raise EnvironmentError("RUNWAY_API_KEY tidak ditemukan di environment")
        return RunwayProvider(
            api_key=api_key,
            model=_model or "gen4.5",
        )

    if _provider == "wavespeed":
        api_key = os.getenv("WAVESPEED_API_KEY", "").strip()
        if not api_key:
            raise EnvironmentError("WAVESPEED_API_KEY tidak ditemukan di environment")
        return WavespeedProvider(
            api_key=api_key,
            model=_model or "google/veo3.1-lite",
        )

    raise ValueError(
        f"Provider '{_provider}' tidak dikenali. Pilihan valid: ltx, runway, wavespeed"
    )