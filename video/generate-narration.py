#!/usr/bin/env python3
"""Generate measured, per-beat ElevenLabs narration and derived captions.

The production path is intentionally networked and is invoked only by the manual video
workflow. ``--validate`` checks the complete authoring contract without a credential,
network request, ffmpeg invocation, or output write.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pathlib
import re
import subprocess
import time
import urllib.error
import urllib.request


SPEC = pathlib.Path(__file__).with_name("narration.json")
SCENE_IDS = ("hook", "surface", "trigger", "live", "sponsor", "evidence", "close")
SCHEMA = "archon.submission-video/v1"
FPS = 25
TAIL_SECONDS = 0.65
MIN_TOTAL_SECONDS = 90
MAX_TOTAL_SECONDS_EXCLUSIVE = 175
MIN_SCENE_SECONDS = 3
MAX_SCENE_SECONDS = 40
CACHE_CONTRACT = "merismos-elevenlabs-per-beat/v1"
ELEVENLABS_KEY_ENV_NAMES = ("ELEVENLABS_API_KEY", "XI_API_KEY", "ELEVEN_LABS_KEY")


def run(args: list[str]) -> str:
    result = subprocess.run(args, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def duration(path: pathlib.Path) -> float:
    return float(
        run(
            [
                os.environ["FFPROBE"],
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ]
        )
    )


def timestamp(value: float) -> str:
    millis = round(max(0.0, value) * 1000)
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    seconds, millis = divmod(millis, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def wrapped(text: str, width: int = 66) -> str:
    words = text.split()
    lines: list[str] = []
    line = ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if line and len(candidate) > width:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    if len(lines) <= 2:
        return "\n".join(lines)
    midpoint = max(1, len(words) // 2)
    return " ".join(words[:midpoint]) + "\n" + " ".join(words[midpoint:])


def speaking_rate(spec: dict[str, object]) -> float:
    value = spec.get("speakingRate")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SystemExit("speakingRate must be a number between 0.7 and 1.2")
    rate = float(value)
    if not math.isfinite(rate) or not 0.7 <= rate <= 1.2:
        raise SystemExit("speakingRate must be between 0.7 and 1.2 for ElevenLabs")
    return rate


def elevenlabs_config(spec: dict[str, object]) -> dict[str, object]:
    config = spec.get("elevenLabs")
    if not isinstance(config, dict):
        raise SystemExit("provider is elevenlabs but the elevenLabs block is missing")
    voice_id = config.get("voiceId")
    model_id = config.get("modelId")
    output_format = config.get("outputFormat")
    if not isinstance(voice_id, str) or not re.fullmatch(r"[A-Za-z0-9]{16,40}", voice_id):
        raise SystemExit("elevenLabs.voiceId is missing or malformed")
    if not isinstance(model_id, str) or not re.fullmatch(r"[a-z0-9_]{4,40}", model_id):
        raise SystemExit("elevenLabs.modelId is missing or malformed")
    if not isinstance(output_format, str) or not re.fullmatch(r"[a-z0-9_]{4,32}", output_format):
        raise SystemExit("elevenLabs.outputFormat is missing or malformed")
    return {
        "voiceId": voice_id,
        "modelId": model_id,
        "outputFormat": output_format,
        "voiceSettings": {
            "stability": 0.45,
            "similarity_boost": 0.8,
            "use_speaker_boost": True,
            "speed": speaking_rate(spec),
        },
    }


def validate_spec(spec: object) -> tuple[dict[str, object], list[dict[str, str]]]:
    if not isinstance(spec, dict) or spec.get("schemaVersion") != SCHEMA:
        raise SystemExit(f"narration schemaVersion must be {SCHEMA}")
    if spec.get("provider") != "elevenlabs":
        raise SystemExit("the submission pipeline requires provider=elevenlabs")
    elevenlabs_config(spec)
    segments = spec.get("segments")
    if not isinstance(segments, list):
        raise SystemExit("narration segments must be a list")
    identifiers: list[str] = []
    validated: list[dict[str, str]] = []
    for segment in segments:
        if not isinstance(segment, dict):
            raise SystemExit("each narration segment must be an object")
        identifier = segment.get("id")
        speech = segment.get("speechText")
        caption = segment.get("captionText")
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-z][a-z-]{1,24}", identifier):
            raise SystemExit("scene identifier is invalid")
        if not all(isinstance(value, str) and 20 <= len(value) <= 800 for value in (speech, caption)):
            raise SystemExit(f"scene text is invalid: {identifier}")
        if "<" in f"{speech}{caption}" or ">" in f"{speech}{caption}":
            raise SystemExit(f"scene {identifier} contains an unfilled placeholder")
        identifiers.append(identifier)
        validated.append({"id": identifier, "speechText": speech, "captionText": caption})
    if tuple(identifiers) != SCENE_IDS:
        raise SystemExit(f"scene order must be: {', '.join(SCENE_IDS)}")
    return spec, validated


def read_spec() -> tuple[dict[str, object], list[dict[str, str]], bytes]:
    raw = SPEC.read_bytes()
    try:
        parsed = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SystemExit(f"narration.json is not valid UTF-8 JSON: {error}") from error
    spec, segments = validate_spec(parsed)
    return spec, segments, raw


def elevenlabs_key() -> str:
    for name in ELEVENLABS_KEY_ENV_NAMES:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    raise SystemExit("no ElevenLabs key is configured")


def elevenlabs_request_body(text: str, spec: dict[str, object]) -> bytes:
    config = elevenlabs_config(spec)
    return json.dumps(
        {
            "text": text,
            "model_id": config["modelId"],
            "voice_settings": config["voiceSettings"],
        },
        separators=(",", ":"),
    ).encode("utf-8")


def synthesize_elevenlabs(text: str, spec: dict[str, object], retries: int = 3) -> bytes:
    config = elevenlabs_config(spec)
    url = (
        f"https://api.elevenlabs.io/v1/text-to-speech/{config['voiceId']}"
        f"?output_format={config['outputFormat']}"
    )
    body = elevenlabs_request_body(text, spec)
    key = elevenlabs_key()
    last_error = "unknown provider error"
    for attempt in range(retries):
        try:
            request = urllib.request.Request(
                url,
                data=body,
                headers={
                    "xi-api-key": key,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                },
            )
            with urllib.request.urlopen(request, timeout=90) as response:
                data = response.read()
            if len(data) < 3000:
                raise RuntimeError(f"provider returned only {len(data)} audio bytes")
            return data
        except urllib.error.HTTPError as error:
            last_error = f"HTTP {error.code}"
        except Exception as error:  # noqa: BLE001 - retried at the provider boundary
            last_error = type(error).__name__
        if attempt + 1 < retries:
            time.sleep(2 * (attempt + 1))
    raise SystemExit(f"ElevenLabs failed after {retries} attempts: {last_error}")


def voice_signature(spec: dict[str, object]) -> str:
    config = elevenlabs_config(spec)
    return json.dumps(
        {
            "contract": CACHE_CONTRACT,
            "generatorSha256": sha256_bytes(pathlib.Path(__file__).read_bytes()),
            "elevenLabs": config,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def cache_key(segment: dict[str, str], spec: dict[str, object]) -> str:
    payload = json.dumps(
        {
            "id": segment["id"],
            "speech": segment["speechText"],
            "voice": voice_signature(spec),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256_bytes(payload.encode("utf-8"))


def cached_record(sidecar: pathlib.Path) -> dict[str, object] | None:
    try:
        value = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def write_json(path: pathlib.Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def synthesize_scene(
    audio: pathlib.Path,
    sidecar: pathlib.Path,
    segment: dict[str, str],
    spec: dict[str, object],
    forced: set[str],
) -> str:
    key = cache_key(segment, spec)
    record = cached_record(sidecar)
    if (
        segment["id"] not in forced
        and "all" not in forced
        and audio.is_file()
        and record is not None
        and record.get("cacheKey") == key
        and record.get("audioSha256") == sha256_bytes(audio.read_bytes())
    ):
        return "reused"
    data = synthesize_elevenlabs(segment["speechText"], spec)
    temporary = audio.with_suffix(".part.mp3")
    temporary.write_bytes(data)
    seconds = duration(temporary)
    if not MIN_SCENE_SECONDS <= seconds <= MAX_SCENE_SECONDS:
        temporary.unlink(missing_ok=True)
        raise SystemExit(
            f"scene audio duration is unsafe: {segment['id']} measured {seconds:.3f}s"
        )
    temporary.replace(audio)
    write_json(
        sidecar,
        {
            "schemaVersion": "merismos.narration-cache/v1",
            "cacheKey": key,
            "provider": "elevenlabs",
            "audioSha256": sha256_bytes(data),
        },
    )
    return "synthesized"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate", action="store_true", help="validate only; no network or writes")
    parser.add_argument(
        "--force",
        action="append",
        default=[],
        metavar="BEAT",
        help="re-synthesize one named beat, or all",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    spec, segments, raw_spec = read_spec()
    if args.validate:
        print(
            json.dumps(
                {
                    "schemaVersion": SCHEMA,
                    "provider": "elevenlabs",
                    "sceneIds": list(SCENE_IDS),
                    "speakingRate": speaking_rate(spec),
                    "narrationSpecSha256": sha256_bytes(raw_spec),
                    "networkCalled": False,
                },
                separators=(",", ":"),
            )
        )
        return

    root_value = os.environ.get("MERISMOS_VIDEO_ROOT", "").strip()
    if not root_value:
        raise SystemExit("MERISMOS_VIDEO_ROOT is required")
    ffprobe = os.environ.get("FFPROBE", "").strip()
    if not ffprobe:
        raise SystemExit("FFPROBE is required")
    root = pathlib.Path(root_value)
    out = root / "narration"
    out.mkdir(parents=True, exist_ok=True)
    forced = set(args.force)
    forced.update(item.strip() for item in os.environ.get("NARRATION_FORCE", "").split(",") if item.strip())
    unknown = forced - set(SCENE_IDS) - {"all"}
    if unknown:
        raise SystemExit(f"unknown forced beat: {', '.join(sorted(unknown))}")

    timing: list[dict[str, object]] = []
    cues: list[tuple[float, float, str, str]] = []
    offset = 0.0
    for index, segment in enumerate(segments, start=1):
        identifier = segment["id"]
        audio = out / f"{index:02d}-{identifier}.mp3"
        sidecar = out / f"{index:02d}-{identifier}.cache.json"
        outcome = synthesize_scene(audio, sidecar, segment, spec, forced)
        seconds = duration(audio)
        if not MIN_SCENE_SECONDS <= seconds <= MAX_SCENE_SECONDS:
            raise SystemExit(f"scene audio duration is unsafe: {identifier} measured {seconds:.3f}s")
        hold_frames = math.ceil((seconds + TAIL_SECONDS) * FPS)
        hold = hold_frames / FPS
        sentences = [
            part.strip()
            for part in re.split(r"(?<=[.!?])\s+", segment["captionText"])
            if part.strip()
        ]
        weight = sum(len(part) for part in sentences) or 1
        cursor = 0.0
        for sentence in sentences:
            share = seconds * len(sentence) / weight
            cues.append((offset + cursor, offset + cursor + share, wrapped(sentence), identifier))
            cursor += share
        timing.append(
            {
                "id": identifier,
                "audio": audio.name,
                "audioSha256": sha256_bytes(audio.read_bytes()),
                "durationSeconds": round(seconds, 3),
                "holdSeconds": round(hold, 3),
                "startSeconds": round(offset, 3),
                "holdFrames": hold_frames,
                "captionCount": len(sentences),
            }
        )
        print(f"{outcome} {audio.name} ({seconds:.3f}s)")
        offset += hold
    if not MIN_TOTAL_SECONDS <= offset < MAX_TOTAL_SECONDS_EXCLUSIVE:
        raise SystemExit(f"narration must be 90-174 seconds, observed {offset:.3f}")

    timing_payload = {
        "schemaVersion": "merismos.submission-video-timing/v1",
        "fps": FPS,
        "tailSeconds": TAIL_SECONDS,
        "totalSeconds": round(offset, 3),
        "narrationSpecSha256": sha256_bytes(raw_spec),
        "provider": "elevenlabs",
        "speakingRate": speaking_rate(spec),
        "scenes": timing,
    }
    write_json(out / "timing.json", timing_payload)
    srt: list[str] = []
    for number, (start, end, text, _) in enumerate(cues, start=1):
        srt.extend([str(number), f"{timestamp(start)} --> {timestamp(end)}", text, ""])
    (out / "captions.en.srt").write_text("\n".join(srt), encoding="utf-8")
    print(f"Generated {len(timing)} scenes across {offset:.3f} seconds")


if __name__ == "__main__":
    main()
