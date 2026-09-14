#!/usr/bin/env python3
"""Generate measured, per-beat ElevenLabs narration and derived captions.

The production path is intentionally networked and is invoked only by the manual video
workflow. ``--validate`` checks the complete authoring contract without a credential,
network request, ffmpeg invocation, or output write.
"""

from __future__ import annotations

import argparse
import base64
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
SCHEMA = "merismos.submission-video/v1"
FPS = 25
FRAME_SECONDS = 1 / FPS
TAIL_SECONDS = 0.65
MIN_TOTAL_SECONDS = 90
MAX_TOTAL_SECONDS_EXCLUSIVE = 175
MIN_SCENE_SECONDS = 3
MAX_SCENE_SECONDS = 40
MAX_PROVIDER_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_BILLED_CHARACTERS = 12_000
CACHE_CONTRACT = "merismos-elevenlabs-per-beat/v2"
ELEVENLABS_KEY_ENV_NAMES = ("ELEVENLABS_API_KEY", "XI_API_KEY", "ELEVEN_LABS_KEY")
ATTEMPT_FILENAME = re.compile(
    r"[a-z][a-z-]{1,24}\.[a-f0-9]{16}\.[1-9][0-9]*\.attempt\.json"
)


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


def sentence_spans(text: str) -> list[tuple[str, int, int]]:
    spans: list[tuple[str, int, int]] = []
    for match in re.finditer(r".+?(?:[.!?](?=\s|$)|$)", text, flags=re.DOTALL):
        raw = match.group(0)
        leading = len(raw) - len(raw.lstrip())
        trailing = len(raw) - len(raw.rstrip())
        start = match.start() + leading
        end = match.end() - trailing
        if start < end:
            spans.append((text[start:end], start, end))
    return spans


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
        if not all(
            isinstance(value, str) and 20 <= len(value) <= 800 for value in (speech, caption)
        ):
            raise SystemExit(f"scene text is invalid: {identifier}")
        if "<" in f"{speech}{caption}" or ">" in f"{speech}{caption}":
            raise SystemExit(f"scene {identifier} contains an unfilled placeholder")
        if len(sentence_spans(speech)) != len(sentence_spans(caption)):
            raise SystemExit(
                f"scene {identifier} speech and caption sentence counts differ"
            )
        identifiers.append(identifier)
        validated.append({"id": identifier, "speechText": speech, "captionText": caption})
    if tuple(identifiers) != SCENE_IDS:
        raise SystemExit(f"scene order must be: {', '.join(SCENE_IDS)}")
    if sum(len(segment["speechText"]) for segment in validated) > MAX_BILLED_CHARACTERS:
        raise SystemExit(f"narration exceeds the {MAX_BILLED_CHARACTERS}-character provider cap")
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


def synthesize_elevenlabs(
    text: str, spec: dict[str, object]
) -> tuple[bytes, dict[str, object], str]:
    config = elevenlabs_config(spec)
    url = (
        f"https://api.elevenlabs.io/v1/text-to-speech/{config['voiceId']}/with-timestamps"
        f"?output_format={config['outputFormat']}"
    )
    body = elevenlabs_request_body(text, spec)
    key = elevenlabs_key()
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "xi-api-key": key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read(MAX_PROVIDER_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise SystemExit(f"ElevenLabs returned HTTP {error.code}; no automatic billed retry") from None
    except Exception as error:  # noqa: BLE001 - provider boundary, deliberately no retry
        raise SystemExit(
            f"ElevenLabs transport failed with {type(error).__name__}; no automatic billed retry"
        ) from None
    if len(raw) > MAX_PROVIDER_RESPONSE_BYTES:
        raise SystemExit("ElevenLabs response exceeded the 32 MiB bound")
    try:
        result = json.loads(raw)
        audio = base64.b64decode(result["audio_base64"], validate=True)
        alignment = result["alignment"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit("ElevenLabs returned an invalid timestamped response; no retry") from error
    if len(audio) < 3000 or not isinstance(alignment, dict):
        raise SystemExit("ElevenLabs returned incomplete audio or alignment; no retry")
    return audio, alignment, sha256_bytes(raw)


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


def attempt_records(directory: pathlib.Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for path in sorted(directory.glob("*.attempt.json")):
        record = cached_record(path)
        if (
            record is None
            or record.get("schemaVersion") != "merismos.narration-attempt/v1"
            or not isinstance(record.get("characters"), int)
            or not 0 < int(record["characters"]) <= MAX_BILLED_CHARACTERS
        ):
            raise SystemExit(f"invalid ElevenLabs attempt ledger: {path.name}")
        if record.get("status") not in {"completed", "acknowledged"}:
            raise SystemExit(
                f"unresolved ElevenLabs attempt; reconcile before another paid call: {path.name}"
            )
        records.append(record)
    return records


def acknowledge_attempt(directory: pathlib.Path, name: str) -> pathlib.Path:
    if pathlib.PurePath(name).name != name or not ATTEMPT_FILENAME.fullmatch(name):
        raise SystemExit("--acknowledge-attempt must be one exact attempt-ledger filename")
    path = directory / name
    record = cached_record(path)
    if (
        record is None
        or record.get("schemaVersion") != "merismos.narration-attempt/v1"
        or record.get("status") != "started"
        or not isinstance(record.get("characters"), int)
        or not 0 < int(record["characters"]) <= MAX_BILLED_CHARACTERS
    ):
        raise SystemExit("only one valid unresolved attempt can be acknowledged")
    record["status"] = "acknowledged"
    record["acknowledgement"] = "provider billing reviewed before an explicit retry"
    record["acknowledgedByWorkflowRun"] = os.environ.get("GITHUB_RUN_ID", "manual")
    write_json(path, record)
    return path


def reserve_attempt(
    directory: pathlib.Path, segment: dict[str, str], key: str
) -> pathlib.Path:
    spent = sum(int(record["characters"]) for record in attempt_records(directory))
    characters = len(segment["speechText"])
    if spent + characters > MAX_BILLED_CHARACTERS:
        raise SystemExit(
            f"ElevenLabs cumulative character cap exceeded: {spent} + {characters} > "
            f"{MAX_BILLED_CHARACTERS}"
        )
    path = directory / f"{segment['id']}.{key[:16]}.{time.time_ns()}.attempt.json"
    payload = {
        "schemaVersion": "merismos.narration-attempt/v1",
        "status": "started",
        "sceneId": segment["id"],
        "cacheKey": key,
        "characters": characters,
    }
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return path


def validate_alignment(
    alignment: object, speech: str, seconds: float
) -> dict[str, list[object]]:
    if not isinstance(alignment, dict):
        raise SystemExit("ElevenLabs character alignment is missing")
    characters = alignment.get("characters")
    starts = alignment.get("character_start_times_seconds")
    ends = alignment.get("character_end_times_seconds")
    # Provider responses use the long field names; cache sidecars deliberately
    # store the normalized names returned below.  Validation must be idempotent
    # because main() validates the persisted sidecar before deriving captions.
    if starts is None and ends is None:
        starts = alignment.get("startSeconds")
        ends = alignment.get("endSeconds")
    if not isinstance(characters, list) or not isinstance(starts, list) or not isinstance(ends, list):
        raise SystemExit("ElevenLabs character alignment arrays are missing")
    if not characters or not len(characters) == len(starts) == len(ends):
        raise SystemExit("ElevenLabs character alignment lengths differ")
    if not all(isinstance(character, str) and len(character) == 1 for character in characters):
        raise SystemExit("ElevenLabs character alignment contains an invalid character")
    if "".join(characters) != speech:
        raise SystemExit("ElevenLabs character alignment does not match the requested speech")
    previous = 0.0
    checked_starts: list[float] = []
    checked_ends: list[float] = []
    for character, start, end in zip(characters, starts, ends, strict=True):
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, (int, float))
            or not isinstance(end, (int, float))
            or not math.isfinite(float(start))
            or not math.isfinite(float(end))
            or not previous <= float(start) <= float(end) <= seconds + FRAME_SECONDS
        ):
            raise SystemExit("ElevenLabs character alignment is not monotonic or in bounds")
        checked_starts.append(float(start))
        checked_ends.append(min(float(end), seconds))
        previous = float(end)
    return {
        "characters": characters,
        "startSeconds": checked_starts,
        "endSeconds": checked_ends,
    }


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
        and isinstance(record.get("alignment"), dict)
    ):
        return "reused"
    attempt = reserve_attempt(sidecar.parent, segment, key)
    data, raw_alignment, response_sha = synthesize_elevenlabs(segment["speechText"], spec)
    temporary = audio.with_suffix(".part.mp3")
    temporary.write_bytes(data)
    seconds = duration(temporary)
    if not MIN_SCENE_SECONDS <= seconds <= MAX_SCENE_SECONDS:
        temporary.unlink(missing_ok=True)
        raise SystemExit(f"scene audio duration is unsafe: {segment['id']} measured {seconds:.3f}s")
    alignment = validate_alignment(raw_alignment, segment["speechText"], seconds)
    temporary.replace(audio)
    write_json(
        sidecar,
        {
            "schemaVersion": "merismos.narration-cache/v1",
            "cacheKey": key,
            "provider": "elevenlabs",
            "audioSha256": sha256_bytes(data),
            "providerResponseSha256": response_sha,
            "alignment": alignment,
        },
    )
    write_json(
        attempt,
        {
            "schemaVersion": "merismos.narration-attempt/v1",
            "status": "completed",
            "sceneId": segment["id"],
            "cacheKey": key,
            "characters": len(segment["speechText"]),
            "audioSha256": sha256_bytes(data),
            "providerResponseSha256": response_sha,
        },
    )
    return "synthesized"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--validate", action="store_true", help="validate only; no network or writes"
    )
    parser.add_argument(
        "--force",
        action="append",
        default=[],
        metavar="BEAT",
        help="re-synthesize one named beat, or all",
    )
    parser.add_argument(
        "--acknowledge-attempt",
        metavar="FILENAME",
        help="acknowledge one reviewed unresolved attempt, count it as spent and exit",
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
    root = pathlib.Path(root_value)
    out = root / "narration"
    out.mkdir(parents=True, exist_ok=True)
    if args.acknowledge_attempt:
        path = acknowledge_attempt(out, args.acknowledge_attempt)
        print(f"Acknowledged reviewed attempt: {path.name}")
        return
    ffprobe = os.environ.get("FFPROBE", "").strip()
    if not ffprobe:
        raise SystemExit("FFPROBE is required")
    attempt_records(out)
    forced = set(args.force)
    forced.update(
        item.strip() for item in os.environ.get("NARRATION_FORCE", "").split(",") if item.strip()
    )
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
            raise SystemExit(
                f"scene audio duration is unsafe: {identifier} measured {seconds:.3f}s"
            )
        hold_frames = math.ceil((seconds + TAIL_SECONDS) * FPS)
        hold = hold_frames / FPS
        record = cached_record(sidecar)
        if record is None:
            raise SystemExit(f"narration cache record is missing: {sidecar.name}")
        alignment = validate_alignment(record.get("alignment"), segment["speechText"], seconds)
        speech_sentences = sentence_spans(segment["speechText"])
        caption_sentences = sentence_spans(segment["captionText"])
        for speech_sentence, caption_sentence in zip(
            speech_sentences, caption_sentences, strict=True
        ):
            _, start_index, end_index = speech_sentence
            caption, _, _ = caption_sentence
            start = float(alignment["startSeconds"][start_index])
            end = float(alignment["endSeconds"][end_index - 1])
            if not 0 <= start < end <= seconds:
                raise SystemExit(f"caption alignment is outside scene {identifier}")
            cues.append((offset + start, offset + end, wrapped(caption), identifier))
        timing.append(
            {
                "id": identifier,
                "audio": audio.name,
                "audioSha256": sha256_bytes(audio.read_bytes()),
                "durationSeconds": round(seconds, 3),
                "holdSeconds": round(hold, 3),
                "startSeconds": round(offset, 3),
                "holdFrames": hold_frames,
                "captionCount": len(caption_sentences),
                "captionAlignment": "elevenlabs-character",
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
