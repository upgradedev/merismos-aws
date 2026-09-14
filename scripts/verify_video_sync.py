#!/usr/bin/env python3
"""Fail-closed post-build gate for the seven-beat continuous Merismos capture."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pathlib
import re
import subprocess

SCENE_IDS = ("hook", "surface", "trigger", "live", "sponsor", "evidence", "close")
SHA = re.compile(r"[0-9a-f]{40}")
SRT_WINDOW = re.compile(
    r"(?m)^(\d+)\r?\n(\d{2}:\d{2}:\d{2},\d{3}) --> "
    r"(\d{2}:\d{2}:\d{2},\d{3})\r?\n(.+?)(?=\r?\n\r?\n|\Z)",
    re.DOTALL,
)
PSNR_FRAME = re.compile(r"(?m)^n:(\d+)\s+mse_avg:([0-9]+(?:\.[0-9]+)?)")
CAPTION_STYLE = (
    "FontName=DejaVu Sans,FontSize=14,PrimaryColour=&H00FFFFFF,"
    "BackColour=&HA0000000,BorderStyle=4,Outline=0,Shadow=0,MarginV=38,Alignment=2"
)
CAPTION_CROP = "crop=1920:320:0:760"
CAPTION_EDGE_SECONDS = 0.12
MIN_CAPTIONED_PSNR_DB = 30
MIN_CAPTION_ADVANTAGE_DB = 1


class Gate:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def check(self, ok: bool, label: str, detail: str) -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label} :: {detail}")
        if not ok:
            self.failures.append(f"{label} :: {detail}")


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
        raise SystemExit(f"::error::invalid JSON input {path}: {error}") from error
    if not isinstance(value, dict):
        raise SystemExit(f"::error::JSON input must be an object: {path}")
    return value


def command(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True)


def probe(path: pathlib.Path) -> dict[str, object]:
    ffprobe = os.environ.get("FFPROBE", "ffprobe")
    result = command(
        [
            ffprobe,
            "-v",
            "error",
            "-count_frames",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ]
    )
    if result.returncode != 0:
        raise SystemExit(f"::error::ffprobe failed: {result.stderr[-1000:]}")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise SystemExit("::error::ffprobe did not return JSON") from error
    if not isinstance(value, dict):
        raise SystemExit("::error::ffprobe JSON must be an object")
    return value


def rational(value: object) -> float:
    text = str(value)
    if "/" in text:
        numerator, denominator = text.split("/", 1)
        return float(numerator) / float(denominator)
    return float(text)


def stream_duration(stream: dict[str, object], media: dict[str, object]) -> float:
    value = stream.get("duration")
    if value not in (None, "N/A"):
        return float(value)
    return float(dict(media.get("format", {})).get("duration", 0))


def parse_timestamp(value: str) -> float:
    hours, minutes, rest = value.split(":")
    seconds, millis = rest.split(",")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000


def parse_srt(path: pathlib.Path) -> list[tuple[float, float, str]]:
    text = path.read_text(encoding="utf-8")
    matches = SRT_WINDOW.findall(text)
    if not matches:
        return []
    numbers = [int(number) for number, _, _, _ in matches]
    if numbers != list(range(1, len(matches) + 1)):
        return []
    return [
        (parse_timestamp(start), parse_timestamp(end), caption.strip())
        for _, start, end, caption in matches
    ]


def frame_hash(path: pathlib.Path, at: float) -> str | None:
    ffmpeg = os.environ.get("FFMPEG", "ffmpeg")
    result = command(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{at:.3f}",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-an",
            "-frames:v",
            "1",
            "-f",
            "framemd5",
            "-",
        ]
    )
    if result.returncode != 0:
        return None
    rows = [line for line in result.stdout.splitlines() if line and not line.startswith("#")]
    if len(rows) != 1 or "," not in rows[0]:
        return None
    return rows[0].rsplit(",", 1)[-1].strip()


def max_volume(path: pathlib.Path, start: float, duration: float) -> float | None:
    ffmpeg = os.environ.get("FFMPEG", "ffmpeg")
    result = command(
        [
            ffmpeg,
            "-hide_banner",
            "-nostats",
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{duration:.3f}",
            "-i",
            str(path),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ]
    )
    match = re.search(r"max_volume:\s*(-?[0-9.]+)\s*dB", result.stderr)
    return float(match.group(1)) if match else None


def escaped_filter_path(path: pathlib.Path) -> str:
    return str(path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def reference_frame_mse(
    shipped: pathlib.Path,
    capture: pathlib.Path,
    captions: pathlib.Path,
    trim_lead: float,
    total: float,
    *,
    burn_captions: bool,
) -> list[float] | None:
    """Compare decoded shipped caption pixels with an independent capture render."""
    ffmpeg = os.environ.get("FFMPEG", "ffmpeg")
    reference = (
        f"trim=start={trim_lead:.3f}:end={trim_lead + total:.3f},"
        "setpts=PTS-STARTPTS,fps=25,scale=1920:1080:"
        "force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x07111f"
    )
    if burn_captions:
        reference += (
            f",subtitles='{escaped_filter_path(captions)}':"
            f"force_style='{CAPTION_STYLE}'"
        )
    filters = (
        f"[0:v]setpts=PTS-STARTPTS,fps=25,{CAPTION_CROP},format=yuv420p[actual];"
        f"[1:v]{reference},{CAPTION_CROP},format=yuv420p[reference];"
        "[actual][reference]psnr=shortest=1:stats_file=-:stats_version=2"
    )
    result = command(
        [
            ffmpeg,
            "-hide_banner",
            "-nostats",
            "-i",
            str(shipped),
            "-i",
            str(capture),
            "-filter_complex",
            filters,
            "-an",
            "-f",
            "null",
            "-",
        ]
    )
    if result.returncode != 0:
        return None
    matches = PSNR_FRAME.findall(result.stdout + "\n" + result.stderr)
    if not matches:
        return None
    numbers = [int(number) for number, _ in matches]
    if numbers != list(range(1, len(matches) + 1)):
        return None
    return [float(mse) for _, mse in matches]


def psnr_from_mse(values: list[float]) -> float | None:
    if not values:
        return None
    mean_mse = sum(values) / len(values)
    return math.inf if mean_mse == 0 else 10 * math.log10((255**2) / mean_mse)


def frame_psnr(mse: float) -> float:
    return math.inf if mse == 0 else 10 * math.log10((255**2) / mse)


def cue_frame_indices(frame_count: int, start: float, end: float) -> list[int]:
    margin = min(CAPTION_EDGE_SECONDS, (end - start) / 4)
    return [
        index
        for index in range(frame_count)
        if start + margin <= index / 25 < end - margin
    ]


def frame_matches_caption(captioned_mse: float, uncaptioned_mse: float) -> bool:
    captioned = frame_psnr(captioned_mse)
    uncaptioned = frame_psnr(uncaptioned_mse)
    return (
        captioned >= MIN_CAPTIONED_PSNR_DB
        and captioned > uncaptioned + MIN_CAPTION_ADVANTAGE_DB
    )


def psnr_advantage(captioned: float, uncaptioned: float) -> float | None:
    if math.isinf(captioned) and math.isinf(uncaptioned):
        return None
    return captioned - uncaptioned


def report_metric(value: float | None) -> float | str | None:
    if value is None:
        return None
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    return round(value, 3)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("mp4", type=pathlib.Path)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--timing", type=pathlib.Path)
    parser.add_argument("--captions", type=pathlib.Path)
    parser.add_argument("--receipt", type=pathlib.Path)
    parser.add_argument("--capture-receipt", type=pathlib.Path)
    parser.add_argument("--capture-media", required=True, type=pathlib.Path)
    parser.add_argument("--ffprobe-evidence", type=pathlib.Path)
    parser.add_argument("--report", type=pathlib.Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not SHA.fullmatch(args.release_sha):
        raise SystemExit("::error::--release-sha must be a full lowercase commit SHA")
    base = args.mp4.parent
    paths = {
        "mp4": args.mp4,
        "timing": args.timing or base / "timing.json",
        "captions": args.captions or base / "captions.en.srt",
        "receipt": args.receipt or base / "video-receipt.json",
        "capture": args.capture_receipt or base / "capture-receipt.json",
        "capture_media": args.capture_media,
        "ffprobe": args.ffprobe_evidence or base / "ffprobe.json",
        "report": args.report or base / "verification-report.json",
    }
    for name, path in paths.items():
        if name != "report" and (not path.is_file() or path.stat().st_size == 0):
            raise SystemExit(f"::error::required verification input is missing: {path}")

    timing = load_json(paths["timing"])
    receipt = load_json(paths["receipt"])
    capture = load_json(paths["capture"])
    ffprobe_evidence = load_json(paths["ffprobe"])
    media = probe(paths["mp4"])
    streams = media.get("streams", [])
    videos = [item for item in streams if item.get("codec_type") == "video"]
    audios = [item for item in streams if item.get("codec_type") == "audio"]
    gate = Gate()

    print("== exact-release and artifact chain ==")
    gate.check(
        receipt.get("releaseSha") == args.release_sha,
        "release-receipt",
        str(receipt.get("releaseSha")),
    )
    gate.check(
        capture.get("releaseSha") == args.release_sha,
        "release-capture",
        str(capture.get("releaseSha")),
    )
    gate.check(
        ffprobe_evidence.get("releaseSha") == args.release_sha,
        "release-ffprobe",
        str(ffprobe_evidence.get("releaseSha")),
    )
    video_sha = sha256(paths["mp4"])
    capture_sha = sha256(paths["capture_media"])
    gate.check(receipt.get("sha256") == video_sha, "receipt-video-sha", video_sha)
    gate.check(ffprobe_evidence.get("sha256") == video_sha, "ffprobe-video-sha", video_sha)
    gate.check(
        receipt.get("timingSha256") == sha256(paths["timing"]),
        "receipt-timing-sha",
        sha256(paths["timing"]),
    )
    gate.check(
        receipt.get("captionsSha256") == sha256(paths["captions"]),
        "receipt-caption-sha",
        sha256(paths["captions"]),
    )
    gate.check(
        receipt.get("captureReceiptSha256") == sha256(paths["capture"]),
        "receipt-capture-sha",
        sha256(paths["capture"]),
    )
    gate.check(
        receipt.get("captureSha256") == capture_sha
        and capture.get("sha256") == capture_sha
        and capture.get("bytes") == paths["capture_media"].stat().st_size,
        "capture-media-sha",
        capture_sha,
    )
    gate.check(
        receipt.get("ffprobeSha256") == sha256(paths["ffprobe"]),
        "receipt-ffprobe-sha",
        sha256(paths["ffprobe"]),
    )

    print("== seven-beat continuous timeline ==")
    scenes = timing.get("scenes") if isinstance(timing.get("scenes"), list) else []
    scene_ids = [scene.get("id") for scene in scenes if isinstance(scene, dict)]
    gate.check(tuple(scene_ids) == SCENE_IDS, "scene-order", f"observed={scene_ids}")
    fps = float(timing.get("fps", 0))
    gate.check(abs(fps - 25) < 0.001, "timeline-fps", f"fps={fps}")
    total = float(timing.get("totalSeconds", 0))
    gate.check(90 <= total < 175, "publication-budget", f"total={total:.3f}s")
    expected_start = 0.0
    timeline_ok = len(scenes) == len(SCENE_IDS)
    for scene in scenes:
        if not isinstance(scene, dict):
            timeline_ok = False
            continue
        start = float(scene.get("startSeconds", -1))
        hold = float(scene.get("holdSeconds", 0))
        spoken = float(scene.get("durationSeconds", 0))
        frames = int(scene.get("holdFrames", 0))
        timeline_ok = timeline_ok and abs(start - expected_start) <= 0.002
        timeline_ok = timeline_ok and 3 <= spoken <= 40 and hold >= spoken
        timeline_ok = timeline_ok and abs(hold - frames / 25) <= 0.002
        expected_start += hold
    timeline_ok = timeline_ok and abs(expected_start - total) <= 0.002
    gate.check(
        timeline_ok,
        "timeline-contiguous",
        f"reconstructed={expected_start:.3f}s total={total:.3f}s",
    )

    capture_scenes = capture.get("scenes") if isinstance(capture.get("scenes"), list) else []
    capture_ids = [scene.get("id") for scene in capture_scenes if isinstance(scene, dict)]
    gate.check(tuple(capture_ids) == SCENE_IDS, "capture-scene-order", f"observed={capture_ids}")
    capture_alignment = len(capture_scenes) == len(scenes)
    for planned, observed in zip(scenes, capture_scenes, strict=False):
        if not isinstance(planned, dict) or not isinstance(observed, dict):
            capture_alignment = False
            continue
        start = float(planned.get("startSeconds", 0))
        hold = float(planned.get("holdSeconds", 0))
        observed_start = float(observed.get("observedStartSeconds", -99))
        observed_end = float(observed.get("observedEndSeconds", -99))
        action = float(observed.get("actionSeconds", -1))
        capture_alignment = capture_alignment and abs(start - observed_start) <= 0.75
        capture_alignment = (
            capture_alignment and abs(hold - (observed_end - observed_start)) <= 0.75
        )
        capture_alignment = capture_alignment and 0 <= action <= hold
    capture_total = float(capture.get("timelineSeconds", 0))
    capture_alignment = capture_alignment and total <= capture_total <= total + 2
    gate.check(
        capture_alignment, "capture-timeline", f"observed={capture_total:.3f}s planned={total:.3f}s"
    )
    gate.check(
        capture.get("pageErrors") == [] and capture.get("requestFailures") == [],
        "capture-browser-errors",
        f"page={capture.get('pageErrors')} requests={capture.get('requestFailures')}",
    )

    print("== shipped frames and audio ==")
    gate.check(
        len(videos) == 1 and len(audios) == 1,
        "stream-count",
        f"video={len(videos)} audio={len(audios)}",
    )
    video_duration = audio_duration = 0.0
    frame_tolerance = 1 / 25
    if len(videos) == 1 and len(audios) == 1:
        video = videos[0]
        audio = audios[0]
        measured_fps = rational(video.get("avg_frame_rate", "0/1"))
        frame_count = int(video.get("nb_read_frames") or video.get("nb_frames") or 0)
        video_duration = frame_count / measured_fps if measured_fps > 0 else 0
        audio_duration = stream_duration(audio, media)
        gate.check(abs(measured_fps - 25) < 0.001, "video-fps", f"fps={measured_fps:.3f}")
        gate.check(frame_count > 0, "frame-count", f"frames={frame_count}")
        gate.check(
            video.get("width") == 1920 and video.get("height") == 1080,
            "video-size",
            f"{video.get('width')}x{video.get('height')}",
        )
        gate.check(
            video.get("codec_name") == "h264" and video.get("pix_fmt") == "yuv420p",
            "video-codec",
            f"{video.get('codec_name')}/{video.get('pix_fmt')}",
        )
        gate.check(audio.get("codec_name") == "aac", "audio-codec", str(audio.get("codec_name")))
        gate.check(
            abs(video_duration - total) <= frame_tolerance,
            "video-timeline",
            f"frames/fps={video_duration:.3f}s expected={total:.3f}s tol={frame_tolerance:.3f}s",
        )
        duration_delta = abs(audio_duration - video_duration)
        gate.check(
            duration_delta <= frame_tolerance,
            "av-duration",
            (
                f"audio={audio_duration:.3f}s video={video_duration:.3f}s "
                f"delta={duration_delta:.3f}s tol={frame_tolerance:.3f}s"
            ),
        )
        gate.check(
            receipt.get("frameCount") == frame_count,
            "receipt-frame-count",
            f"receipt={receipt.get('frameCount')} measured={frame_count}",
        )

    frame_hashes = []
    audible = True
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        start = float(scene.get("startSeconds", 0))
        hold = float(scene.get("holdSeconds", 0))
        spoken = float(scene.get("durationSeconds", 0))
        frame_hashes.append(frame_hash(paths["mp4"], start + hold / 2))
        volume = max_volume(paths["mp4"], start + 0.2, max(0.5, spoken - 0.4))
        audible = audible and volume is not None and volume > -50
    gate.check(
        all(frame_hashes),
        "scene-frames-present",
        f"sampled={sum(bool(value) for value in frame_hashes)}/{len(SCENE_IDS)}",
    )
    gate.check(
        len(set(frame_hashes)) >= 4,
        "scene-pixels-vary",
        f"unique_midpoint_frames={len(set(frame_hashes))}",
    )
    gate.check(audible, "every-beat-audible", "max volume above -50 dB in every spoken window")

    print("== captions ==")
    captions = parse_srt(paths["captions"])
    expected_captions = sum(
        int(scene.get("captionCount", 0)) for scene in scenes if isinstance(scene, dict)
    )
    gate.check(
        len(captions) == expected_captions and len(captions) > 0,
        "caption-count",
        f"observed={len(captions)} expected={expected_captions}",
    )
    monotonic = True
    in_bounds = True
    per_scene = {identifier: 0 for identifier in SCENE_IDS}
    previous_end = -1.0
    for start, end, text in captions:
        monotonic = monotonic and start + 0.001 >= previous_end and bool(text)
        in_bounds = in_bounds and 0 <= start < end <= video_duration + 0.001
        owners = []
        for scene in scenes:
            if not isinstance(scene, dict):
                continue
            scene_start = float(scene.get("startSeconds", 0))
            speech_end = scene_start + float(scene.get("durationSeconds", 0))
            if start + frame_tolerance >= scene_start and end <= speech_end + frame_tolerance:
                owners.append(str(scene.get("id")))
        if len(owners) == 1 and owners[0] in per_scene:
            per_scene[owners[0]] += 1
        else:
            in_bounds = False
        previous_end = end
    gate.check(monotonic, "captions-monotonic-nonoverlap", f"count={len(captions)}")
    gate.check(in_bounds, "captions-in-bounds", f"video={video_duration:.3f}s")
    gate.check(all(per_scene.values()), "captions-cover-scenes", str(per_scene))

    captioned_psnr = uncaptioned_psnr = None
    caption_windows: list[dict[str, object]] = []
    if not gate.failures:
        trim_lead = float(capture.get("trimLeadSeconds", -1))
        captioned_frames = uncaptioned_frames = None
        if 0 <= trim_lead <= 30:
            captioned_frames = reference_frame_mse(
                paths["mp4"],
                paths["capture_media"],
                paths["captions"],
                trim_lead,
                total,
                burn_captions=True,
            )
            uncaptioned_frames = reference_frame_mse(
                paths["mp4"],
                paths["capture_media"],
                paths["captions"],
                trim_lead,
                total,
                burn_captions=False,
            )
        expected_frames = round(total * 25)
        complete_metrics = (
            captioned_frames is not None
            and uncaptioned_frames is not None
            and len(captioned_frames) == expected_frames
            and len(uncaptioned_frames) == expected_frames
        )
        if complete_metrics and captioned_frames is not None and uncaptioned_frames is not None:
            captioned_psnr = psnr_from_mse(captioned_frames)
            uncaptioned_psnr = psnr_from_mse(uncaptioned_frames)
            for index, (start, end, _) in enumerate(captions, start=1):
                frame_indices = cue_frame_indices(expected_frames, start, end)
                captioned_window_mse = [captioned_frames[item] for item in frame_indices]
                uncaptioned_window_mse = [uncaptioned_frames[item] for item in frame_indices]
                captioned_window = psnr_from_mse(captioned_window_mse)
                uncaptioned_window = psnr_from_mse(uncaptioned_window_mse)
                failed_frames = [
                    item
                    for item in frame_indices
                    if not frame_matches_caption(captioned_frames[item], uncaptioned_frames[item])
                ]
                frame_captioned = [frame_psnr(captioned_frames[item]) for item in frame_indices]
                frame_advantages = [
                    psnr_advantage(
                        frame_psnr(captioned_frames[item]),
                        frame_psnr(uncaptioned_frames[item]),
                    )
                    for item in frame_indices
                ]
                measured_advantages = [item for item in frame_advantages if item is not None]
                first_failed = None
                if failed_frames:
                    frame = failed_frames[0]
                    first_failed = {
                        "number": frame + 1,
                        "timeSeconds": round(frame / 25, 3),
                        "captionedReferencePsnrDb": report_metric(
                            frame_psnr(captioned_frames[frame])
                        ),
                        "uncaptionedReferencePsnrDb": report_metric(
                            frame_psnr(uncaptioned_frames[frame])
                        ),
                    }
                caption_windows.append(
                    {
                        "cue": index,
                        "startSeconds": start,
                        "endSeconds": end,
                        "captionedReferencePsnrDb": report_metric(captioned_window),
                        "uncaptionedReferencePsnrDb": report_metric(uncaptioned_window),
                        "interiorFrameCount": len(frame_indices),
                        "failedFrameCount": len(failed_frames),
                        "minimumFrameCaptionedReferencePsnrDb": report_metric(
                            min(frame_captioned) if frame_captioned else None
                        ),
                        "minimumFrameAdvantageDb": report_metric(
                            min(measured_advantages) if measured_advantages else None
                        ),
                        "firstFailedFrame": first_failed,
                        "passed": bool(frame_indices) and not failed_frames,
                    }
                )
        failed_cues = [str(item["cue"]) for item in caption_windows if not item["passed"]]
        first_failed_detail = "-"
        for window in caption_windows:
            failed = window.get("firstFailedFrame")
            if isinstance(failed, dict):
                first_failed_detail = (
                    f"cue{window['cue']}/frame{failed.get('number')}@"
                    f"{failed.get('timeSeconds')}s"
                )
                break
        pixels_bound = (
            complete_metrics and len(caption_windows) == len(captions) and not failed_cues
        )
        gate.check(
            pixels_bound,
            "caption-pixels-bound",
            (
                f"captioned_reference={report_metric(captioned_psnr)}dB "
                f"uncaptioned_reference={report_metric(uncaptioned_psnr)}dB "
                f"windows={len(caption_windows)}/{len(captions)} "
                f"failing_cues={','.join(failed_cues) or '-'} "
                f"first_failed={first_failed_detail}"
            ),
        )
    else:
        gate.check(
            False,
            "caption-pixels-bound",
            "not evaluated because an earlier artifact or timing gate failed",
        )

    report = {
        "schemaVersion": "merismos.submission-video-verification/v1",
        "releaseSha": args.release_sha,
        "passed": not gate.failures,
        "failures": gate.failures,
        "videoSha256": video_sha,
        "videoDurationSecondsFromFrames": round(video_duration, 3),
        "audioDurationSeconds": round(audio_duration, 3),
        "frameToleranceSeconds": frame_tolerance,
        "captionCount": len(captions),
        "captionedReferencePsnrDb": report_metric(captioned_psnr),
        "uncaptionedReferencePsnrDb": report_metric(uncaptioned_psnr),
        "captionPixelPolicy": {
            "edgeExclusionSeconds": CAPTION_EDGE_SECONDS,
            "minimumCaptionedReferencePsnrDb": MIN_CAPTIONED_PSNR_DB,
            "minimumAdvantageDb": MIN_CAPTION_ADVANTAGE_DB,
            "scope": "every interior frame of every caption cue",
        },
        "captionPixelWindows": caption_windows,
        "sceneIds": scene_ids,
    }
    paths["report"].write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print()
    if gate.failures:
        print("::error::verify_video_sync FAILED:")
        for failure in gate.failures:
            print(f"::error::  - {failure}")
        return 1
    print("verify_video_sync: ALL MERISMOS VIDEO GATES PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
