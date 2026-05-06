"""
Main runner — refactored sesuai ticket PM.

Perubahan dari versi sebelumnya:
- Payload lama { user_query, context } → VideoRequest structured format
- Routing logic ada di backend (router.py), bukan di .env saja
- Response distandarisasi via VideoResponse
- Logging proper (bukan print)
- Error handling per-item tanpa crash keseluruhan run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv

from logging_config import setup_logging
from providers import VideoRequest, VideoResponse, build_provider, enrich_routing

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Konstanta
# ---------------------------------------------------------------------------

MAX_DURATION = 12  # Batas maksimum durasi video (detik) — sesuai LTX audio native limit


# ---------------------------------------------------------------------------
# CLI Argument Parser
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """
    Parse argumen dari terminal.

    Contoh penggunaan:
        python run_trial.py --prompt "..." --duration 12 --ratio 16:9
        python run_trial.py  # <-- load prompts.json (mode batch)
    """
    parser = argparse.ArgumentParser(
        description="ITS Marketing Video Generator — LTX AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Contoh penggunaan:

  # Kirim prompt langsung dari terminal:
  python run_trial.py --prompt "A cinematic video of ITS Surabaya campus..."

  # Dengan durasi dan rasio custom:
  python run_trial.py --prompt "..." --duration 12 --ratio 16:9

  # Mode HQ (ltx-2-3-pro):
  python run_trial.py --prompt "..." --task-type text_to_video_hq

  # Mode batch dari prompts.json (tanpa --prompt):
  python run_trial.py
        """,
    )
    parser.add_argument(
        "--prompt", "-p",
        type=str,
        default=None,
        help=(
            "Deskripsi video yang ingin digenerate. "
            "Jika tidak diberikan, script akan load dari prompts.json."
        ),
    )
    parser.add_argument(
        "--duration", "-d",
        type=int,
        default=12,
        choices=range(1, MAX_DURATION + 1),
        metavar=f"[1-{MAX_DURATION}]",
        help=f"Durasi video dalam detik (default: 12, max: {MAX_DURATION})",
    )
    parser.add_argument(
        "--ratio", "-r",
        type=str,
        default="16:9",
        choices=["16:9", "9:16", "1:1", "4:3"],
        help="Aspect ratio video (default: 16:9)",
    )
    parser.add_argument(
        "--task-type", "-t",
        type=str,
        default="text_to_video",
        choices=["text_to_video", "text_to_video_hq"],
        dest="task_type",
        help=(
            "Jenis task: "
            "text_to_video (ltx-2-3-fast, cepat), "
            "text_to_video_hq (ltx-2-3-pro, kualitas lebih tinggi). "
            "Default: text_to_video"
        ),
    )
    parser.add_argument(
        "--id",
        type=str,
        default=None,
        help="ID unik untuk video ini (default: auto-generate dari timestamp)",
    )
    parser.add_argument(
        "--prompts-file",
        type=str,
        default="prompts.json",
        dest="prompts_file",
        help="Path ke file prompts.json untuk mode batch (default: prompts.json)",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_prompts(path: str) -> List[Dict[str, Any]]:
    """Load prompt list dari JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    logger.info("Loaded %d prompts from %s", len(data), path)
    return data


def build_video_request(item: Dict[str, Any]) -> VideoRequest:
    """
    Ticket PM — Payload Mapping:
    Konversi item dari prompts.json ke VideoRequest (structured format).

    Input format:
        { "id": ..., "prompt": ..., "duration": ..., "ratio": ..., "task_type": ... }

    FIX AUDIO CUTOFF: duration di-clamp ke MAX_DURATION.
    """
    task_type = item.get("task_type", "text_to_video")
    duration = int(item.get("duration", os.getenv("ACTIVE_DURATION", "12")))

    # Clamp duration ke batas maksimum
    if duration > MAX_DURATION:
        logger.warning(
            "[RUNNER] duration=%d melebihi MAX_DURATION=%d, di-clamp.",
            duration, MAX_DURATION
        )
        duration = MAX_DURATION

    return VideoRequest(
        instruction=task_type,
        input=item["prompt"],
        context={
            "prompt_id": item.get("id", "unknown"),
            "source": item.get("source", "prompts.json"),
        },
        constraints={
            "duration": duration,
            "ratio": item.get("ratio", os.getenv("ACTIVE_RATIO", "16:9")),
            "resolution": item.get("resolution", os.getenv("LTX_RESOLUTION", "1920x1080")),
            "fps": int(item.get("fps", os.getenv("LTX_FPS", "25"))),
        },
        routing={
            "task_type": task_type,
            "fallback": "ltx:ltx-2-3-fast",
        },
    )


def make_output_path(video_dir: str, prompt_id: str, provider_name: str) -> str:
    """Buat path output yang aman (menghindari karakter spesial)."""
    safe_provider = provider_name.replace(":", "_")
    filename = f"{prompt_id}__{safe_provider}.mp4"
    return os.path.join(video_dir, filename)


def save_report(report_dir: str, results: List[Dict[str, Any]]) -> str:
    """Simpan report JSON dengan timestamp."""
    Path(report_dir).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(report_dir, f"trial_report_{timestamp}.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    return report_path


def build_prompt_list_from_cli(args: argparse.Namespace) -> List[Dict[str, Any]]:
    """
    Buat list prompt dari argumen CLI.
    Digunakan saat --prompt diberikan di terminal.
    """
    # Auto-generate ID jika tidak diberikan
    prompt_id = args.id or f"cli_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    return [
        {
            "id": prompt_id,
            "prompt": args.prompt.strip(),
            "duration": args.duration,
            "ratio": args.ratio,
            "task_type": args.task_type,
            "source": "cli",
        }
    ]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    load_dotenv()

    args = parse_args()

    # Setup directories
    video_dir = os.getenv("VIDEO_OUTPUT_DIR", "outputs/videos")
    report_dir = os.getenv("REPORT_DIR", "outputs/reports")
    log_dir = os.getenv("LOG_DIR", "outputs/logs")
    log_level = os.getenv("LOG_LEVEL", "INFO")

    Path(video_dir).mkdir(parents=True, exist_ok=True)
    Path(report_dir).mkdir(parents=True, exist_ok=True)

    setup_logging(log_dir=log_dir, log_level=log_level)

    logger.info("=" * 60)
    logger.info("Video Generator — AI Marketing ITS")
    logger.info("=" * 60)

    # Tentukan sumber prompt: CLI atau prompts.json
    if args.prompt:
        logger.info("[MODE] Prompt dari CLI terminal")
        prompts = build_prompt_list_from_cli(args)
    else:
        logger.info("[MODE] Batch mode — load dari %s", args.prompts_file)
        if not os.path.exists(args.prompts_file):
            logger.error(
                "File '%s' tidak ditemukan. Gunakan --prompt untuk kirim prompt via terminal, "
                "atau pastikan file prompts.json ada.",
                args.prompts_file,
            )
            sys.exit(1)
        prompts = load_prompts(args.prompts_file)

    results: List[Dict[str, Any]] = []
    success_count = 0
    fail_count = 0

    for item in prompts:
        prompt_id = item.get("id", "unknown")
        logger.info("-" * 60)
        logger.info("Processing prompt_id=%s", prompt_id)
        logger.info("Prompt preview: %.120s...", item["prompt"])
        logger.info("Config: duration=%ds ratio=%s task_type=%s",
                    item.get("duration", 12), item.get("ratio", "16:9"), item.get("task_type", "text_to_video"))

        # Transform ke structured VideoRequest
        request = build_video_request(item)

        # Enrich routing di backend layer (ticket PM)
        request = enrich_routing(request)

        logger.info(
            "Routing: task_type=%s → provider=%s model=%s",
            request.routing.get("task_type"),
            request.routing.get("resolved_provider"),
            request.routing.get("resolved_model"),
        )

        provider_name = request.routing.get("resolved_provider")
        model_name = request.routing.get("resolved_model")

        try:
            provider = build_provider(provider_name, model_name)
        except (EnvironmentError, ValueError) as e:
            logger.error("Gagal inisialisasi provider untuk prompt_id=%s: %s", prompt_id, e)
            fail_count += 1
            continue

        output_path = make_output_path(video_dir, prompt_id, provider.name)
        logger.info("Output path: %s", output_path)

        # Generate
        response: VideoResponse = provider.generate(request=request, output_path=output_path)

        # Ticket PM — Standardized response logging
        logger.info(
            "Result: status=%s route_used=%s",
            response.status, response.route_used
        )
        if response.status == "error":
            logger.error("FAILED prompt_id=%s error=%s", prompt_id, response.error)
            fail_count += 1
        else:
            logger.info("SUCCESS prompt_id=%s output=%s", prompt_id, response.result.get("output_path"))
            # Audio check
            audio_ok = response.result.get("audio", False)
            if not audio_ok:
                logger.warning(
                    "[AUDIO] prompt_id=%s — Video tidak memiliki audio. %s",
                    prompt_id,
                    response.result.get("audio_note", ""),
                )
            else:
                logger.info(
                    "[AUDIO] prompt_id=%s — Audio OK (duration=%ds audio_length=%ds)",
                    prompt_id,
                    response.result.get("duration", "?"),
                    response.result.get("duration", "?"),
                )
            success_count += 1

        # Build report entry sesuai standardized response
        report_entry: Dict[str, Any] = {
            **response.to_dict(),
            "prompt_id": prompt_id,
            "prompt_preview": request.input[:120] + "...",
            "request_payload": {
                "instruction": request.instruction,
                "constraints": request.constraints,
                "routing": request.routing,
            },
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        results.append(report_entry)

    # Simpan report
    report_path = save_report(report_dir, results)

    logger.info("=" * 60)
    logger.info("DONE — success=%d failed=%d total=%d", success_count, fail_count, len(prompts))
    logger.info("Report: %s", report_path)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()