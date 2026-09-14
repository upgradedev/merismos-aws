#!/usr/bin/env python3
"""Compose the exact-release browser capture, narration, and burned captions."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess


FPS = 25
FRAME_SECONDS = 1 / FPS
SCENE_IDS = ("hook", "surface", "trigger", "live", "sponsor", "evidence", "close")
SHA = re.compile(r"[0-9a-f]{40}")
OUTPUT_NAME = "merismos-submission.mp4"


def run(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(result.stderr[-3000:] or "media command failed")
    return result.stdout.strip()


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: pathlib.Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SystemExit(f"invalid JSON input {path}: {error}") from error
    if not isinstance(value, dict):
        raise SystemExit(f"JSON input must be an object: {path}")
    return value


def positive_run_id(name: str) -> int:
    value = os.environ.get(name, "").strip()
    if not re.fullmatch(r"[1-9][0-9]*", value):
        raise SystemExit(f"{name} must be a positive GitHub Actions run id")
    return int(value)


def main() -> None:
    root_value = os.environ.get("MERISMOS_VIDEO_ROOT", "").strip()
    release_sha = os.environ.get("MERISMOS_RELEASE_SHA", "").strip()
    if not root_value:
        raise SystemExit("MERISMOS_VIDEO_ROOT is required")
    if not SHA.fullmatch(release_sha):
        raise SystemExit("MERISMOS_RELEASE_SHA must be a full lowercase commit SHA")
    deploy_run_id = positive_run_id("MERISMOS_DEPLOY_RUN_ID")
    frontend_run_id = positive_run_id("MERISMOS_FRONTEND_RUN_ID")
    ffmpeg = os.environ.get("FFMPEG", "").strip()
    ffprobe = os.environ.get("FFPROBE", "").strip()
    if not ffmpeg or not ffprobe:
        raise SystemExit("FFMPEG and FFPROBE are required")

    root = pathlib.Path(root_value)
    narration = root / "narration"
    capture_dir = root / "capture"
    capture = capture_dir / "production.webm"
    timing_path = narration / "timing.json"
    captions_path = narration / "captions.en.srt"
    capture_receipt_path = capture_dir / "capture-receipt.json"
    output = root / "output"
    for path in (capture, timing_path, captions_path, capture_receipt_path):
        if not path.is_file() or path.stat().st_size == 0:
            raise SystemExit(f"required build input is missing or empty: {path}")

    timing = load_json(timing_path)
    capture_receipt = load_json(capture_receipt_path)
    scenes = timing.get("scenes")
    if timing.get("schemaVersion") != "merismos.submission-video-timing/v1" or not isinstance(scenes, list):
        raise SystemExit("timing contract is invalid")
    if tuple(scene.get("id") for scene in scenes if isinstance(scene, dict)) != SCENE_IDS:
        raise SystemExit("timing scene order is invalid")
    if timing.get("fps") != FPS:
        raise SystemExit(f"timing fps must be {FPS}")
    total = float(timing.get("totalSeconds", 0))
    if not 90 <= total < 175:
        raise SystemExit("timing total must be 90-174 seconds")
    total_frames = round(total * FPS)
    if abs(total - total_frames / FPS) > 0.001:
        raise SystemExit("timing total is not aligned to whole video frames")

    if capture_receipt.get("schemaVersion") != "merismos.submission-video-capture/v1":
        raise SystemExit("capture receipt contract is invalid")
    expected_capture = {
        "releaseSha": release_sha,
        "deployRunId": deploy_run_id,
        "frontendRunId": frontend_run_id,
        "sceneCount": len(SCENE_IDS),
    }
    for field, expected in expected_capture.items():
        if capture_receipt.get(field) != expected:
            raise SystemExit(f"capture receipt {field} does not match the build input")
    if capture_receipt.get("sha256") != sha256(capture):
        raise SystemExit("capture receipt SHA-256 does not match production.webm")
    if capture_receipt.get("narrationTimingSha256") != sha256(timing_path):
        raise SystemExit("capture receipt does not bind the narration timing")
    trim_lead = float(capture_receipt.get("trimLeadSeconds", -1))
    if not 0 <= trim_lead <= 30:
        raise SystemExit("capture trim lead is outside the 0-30 second contract")
    if float(capture_receipt.get("timelineSeconds", 0)) + FRAME_SECONDS < total:
        raise SystemExit("capture timeline is shorter than the narration")

    output.mkdir(parents=True, exist_ok=True)
    filters: list[str] = []
    labels: list[str] = []
    args = [ffmpeg, "-y", "-loglevel", "warning", "-i", str(capture)]
    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            raise SystemExit("timing scene must be an object")
        audio = narration / str(scene.get("audio", ""))
        if not audio.is_file() or scene.get("audioSha256") != sha256(audio):
            raise SystemExit(f"narration audio is missing or changed: {scene.get('id')}")
        args.extend(["-i", str(audio)])
        delay = round(float(scene["startSeconds"]) * 1000)
        hold = float(scene["holdSeconds"])
        label = f"a{index}"
        filters.append(
            f"[{index}:a]aresample=48000,apad=pad_dur={hold:.3f},"
            f"atrim=0:{hold:.3f},adelay={delay}:all=1[{label}]"
        )
        labels.append(f"[{label}]")

    escaped_captions = str(captions_path).replace("\\", "/").replace(":", "\\:")
    style = (
        "FontName=DejaVu Sans,FontSize=14,PrimaryColour=&H00FFFFFF,"
        "BackColour=&HA0000000,BorderStyle=4,Outline=0,Shadow=0,MarginV=38,Alignment=2"
    )
    filters.append(
        f"[0:v]trim=start={trim_lead:.3f}:end={trim_lead + total:.3f},"
        "setpts=PTS-STARTPTS,fps=25,scale=1920:1080:"
        "force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x07111f,"
        f"subtitles='{escaped_captions}':force_style='{style}',format=yuv420p[v]"
    )
    filters.append(
        f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:normalize=0,"
        f"loudnorm=I=-16:LRA=7:TP=-1.5,atrim=0:{total:.3f},"
        f"apad=whole_dur={total:.3f}[a]"
    )
    final = output / OUTPUT_NAME
    args.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-frames:v",
            str(total_frames),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-map_metadata",
            "-1",
            "-movflags",
            "+faststart",
            str(final),
        ]
    )
    run(args)

    probe_text = run(
        [
            ffprobe,
            "-v",
            "error",
            "-count_frames",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(final),
        ]
    )
    media = json.loads(probe_text)
    streams = media.get("streams", [])
    videos = [item for item in streams if item.get("codec_type") == "video"]
    audios = [item for item in streams if item.get("codec_type") == "audio"]
    if len(videos) != 1 or len(audios) != 1:
        raise SystemExit("final media must contain exactly one video and one audio stream")
    video = videos[0]
    if video.get("width") != 1920 or video.get("height") != 1080:
        raise SystemExit("final video dimensions are not 1920x1080")
    frame_count = int(video.get("nb_read_frames") or video.get("nb_frames") or 0)
    if frame_count != total_frames:
        raise SystemExit(f"final video has {frame_count} frames; expected {total_frames}")

    video_sha = sha256(final)
    ffprobe_evidence = {
        "schemaVersion": "merismos.submission-video-ffprobe/v1",
        "releaseSha": release_sha,
        "file": OUTPUT_NAME,
        "sha256": video_sha,
        "probe": media,
    }
    ffprobe_path = output / "ffprobe.json"
    ffprobe_path.write_text(json.dumps(ffprobe_evidence, indent=2) + "\n", encoding="utf-8")
    shutil.copy2(captions_path, output / "captions.en.srt")
    shutil.copy2(timing_path, output / "timing.json")
    shutil.copy2(capture_receipt_path, output / "capture-receipt.json")

    receipt = {
        "schemaVersion": "merismos.submission-video-receipt/v1",
        "releaseSha": release_sha,
        "deployRunId": deploy_run_id,
        "frontendRunId": frontend_run_id,
        "durationSeconds": round(total_frames / FPS, 3),
        "fps": FPS,
        "frameCount": frame_count,
        "width": 1920,
        "height": 1080,
        "sceneCount": len(SCENE_IDS),
        "sceneIds": list(SCENE_IDS),
        "sha256": video_sha,
        "bytes": final.stat().st_size,
        "narrationSpecSha256": timing.get("narrationSpecSha256"),
        "timingSha256": sha256(output / "timing.json"),
        "captionsSha256": sha256(output / "captions.en.srt"),
        "captureSha256": sha256(capture),
        "captureReceiptSha256": sha256(output / "capture-receipt.json"),
        "ffprobeSha256": sha256(ffprobe_path),
    }
    receipt_path = output / "video-receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, separators=(",", ":")))


if __name__ == "__main__":
    main()
