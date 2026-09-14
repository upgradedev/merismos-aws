#!/usr/bin/env python3
"""Prove the Merismos video gate passes good media and rejects five bad cases.

The fixtures are synthetic, contain no product capture or speech, use no network or
credential, and are removed when the test exits.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
GATE = REPO / "scripts" / "verify_video_sync.py"
GENERATOR = REPO / "video" / "generate-narration.py"
NARRATION = REPO / "video" / "narration.json"
SCENE_IDS = ("hook", "surface", "trigger", "live", "sponsor", "evidence", "close")
RELEASE_SHA = "0" * 40
FPS = 25
SCENE_SECONDS = 13.0
SPOKEN_SECONDS = 12.35
TOTAL_SECONDS = SCENE_SECONDS * len(SCENE_IDS)
CAPTION_STYLE = (
    "FontName=DejaVu Sans,FontSize=14,PrimaryColour=&H00FFFFFF,"
    "BackColour=&HA0000000,BorderStyle=4,Outline=0,Shadow=0,MarginV=38,Alignment=2"
)


def run(
    args: list[str], *, check: bool = True, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, capture_output=True, text=True, env=env)
    if check and result.returncode != 0:
        raise SystemExit("command failed:\n" + " ".join(args) + "\n" + result.stderr[-2000:])
    return result


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: pathlib.Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def ffprobe(path: pathlib.Path) -> dict[str, object]:
    result = run(
        [
            "ffprobe",
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
    return json.loads(result.stdout)


def write_srt(
    path: pathlib.Path, *, overlap: bool = False, truncate: str | None = None
) -> None:
    def stamp(value: float) -> str:
        millis = round(value * 1000)
        hours, millis = divmod(millis, 3_600_000)
        minutes, millis = divmod(millis, 60_000)
        seconds, millis = divmod(millis, 1_000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

    rows = []
    for index, identifier in enumerate(SCENE_IDS, start=1):
        start = (index - 1) * SCENE_SECONDS
        if overlap and index == 2:
            start -= 2
        end = (index - 1) * SCENE_SECONDS + 12
        if identifier == truncate:
            end -= 2
        rows.extend(
            [
                str(len(rows) // 4 + 1),
                f"{stamp(start)} --> {stamp(end)}",
                f"Synthetic {identifier} caption.",
                "",
            ]
        )
    path.write_text("\n".join(rows), encoding="utf-8")


def make_media(path: pathlib.Path, *, audio_seconds: float = TOTAL_SECONDS) -> None:
    run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size=1920x1080:rate={FPS}:duration={TOTAL_SECONDS}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate=48000:duration={audio_seconds}",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "38",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(path),
        ]
    )


def make_captioned_media(source: pathlib.Path, path: pathlib.Path, captions: pathlib.Path) -> None:
    escaped_captions = str(captions).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-vf",
            (
                f"trim=start=0:end={TOTAL_SECONDS:.3f},setpts=PTS-STARTPTS,fps={FPS},"
                "scale=1920:1080:force_original_aspect_ratio=decrease,"
                "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x07111f,"
                f"subtitles='{escaped_captions}':force_style='{CAPTION_STYLE}',format=yuv420p"
            ),
            "-frames:v",
            str(round(TOTAL_SECONDS * FPS)),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "20",
            "-c:a",
            "copy",
            str(path),
        ]
    )


def make_av_mismatch(source: pathlib.Path, path: pathlib.Path) -> None:
    run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate=48000:duration={TOTAL_SECONDS + 2}",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(path),
        ]
    )


def write_contracts(
    directory: pathlib.Path,
    media: pathlib.Path,
    capture_media: pathlib.Path,
    *,
    order=SCENE_IDS,
    overlap=False,
) -> None:
    scenes = [
        {
            "id": identifier,
            "audio": f"{index:02d}-{identifier}.mp3",
            "audioSha256": "1" * 64,
            "durationSeconds": SPOKEN_SECONDS,
            "holdSeconds": SCENE_SECONDS,
            "startSeconds": (index - 1) * SCENE_SECONDS,
            "holdFrames": int(SCENE_SECONDS * FPS),
            "captionCount": 1,
        }
        for index, identifier in enumerate(order, start=1)
    ]
    timing = {
        "schemaVersion": "merismos.submission-video-timing/v1",
        "fps": FPS,
        "tailSeconds": 0.65,
        "totalSeconds": TOTAL_SECONDS,
        "narrationSpecSha256": "2" * 64,
        "provider": "elevenlabs",
        "speakingRate": 0.98,
        "scenes": scenes,
    }
    timing_path = directory / "timing.json"
    captions_path = directory / "captions.en.srt"
    capture_path = directory / "capture-receipt.json"
    ffprobe_path = directory / "ffprobe.json"
    write_json(timing_path, timing)
    write_srt(captions_path, overlap=overlap)
    capture_scenes = [
        {
            "id": scene["id"],
            "observedStartSeconds": scene["startSeconds"],
            "observedEndSeconds": scene["startSeconds"] + scene["holdSeconds"],
            "actionSeconds": 0.5,
        }
        for scene in scenes
    ]
    capture = {
        "schemaVersion": "merismos.submission-video-capture/v1",
        "releaseSha": RELEASE_SHA,
        "deployRunId": 1,
        "frontendRunId": 2,
        "sourceUrl": "https://example.invalid/",
        "servedFrontendCommit": RELEASE_SHA,
        "answeringBackendCommit": RELEASE_SHA,
        "sceneCount": len(SCENE_IDS),
        "sceneIds": list(order),
        "scenes": capture_scenes,
        "trimLeadSeconds": 0,
        "timelineSeconds": TOTAL_SECONDS,
        "narrationTimingSha256": sha256(timing_path),
        "pageErrors": [],
        "requestFailures": [],
        "bytes": capture_media.stat().st_size,
        "sha256": sha256(capture_media),
    }
    write_json(capture_path, capture)
    probe = {
        "schemaVersion": "merismos.submission-video-ffprobe/v1",
        "releaseSha": RELEASE_SHA,
        "file": media.name,
        "sha256": sha256(media),
        "probe": ffprobe(media),
    }
    write_json(ffprobe_path, probe)
    video_probe = probe["probe"]
    video_stream = next(item for item in video_probe["streams"] if item["codec_type"] == "video")
    receipt = {
        "schemaVersion": "merismos.submission-video-receipt/v1",
        "releaseSha": RELEASE_SHA,
        "deployRunId": 1,
        "frontendRunId": 2,
        "durationSeconds": TOTAL_SECONDS,
        "fps": FPS,
        "frameCount": int(video_stream.get("nb_read_frames") or video_stream["nb_frames"]),
        "width": 1920,
        "height": 1080,
        "sceneCount": len(SCENE_IDS),
        "sceneIds": list(order),
        "sha256": sha256(media),
        "bytes": media.stat().st_size,
        "narrationSpecSha256": "2" * 64,
        "timingSha256": sha256(timing_path),
        "captionsSha256": sha256(captions_path),
        "captureSha256": sha256(capture_media),
        "captureReceiptSha256": sha256(capture_path),
        "ffprobeSha256": sha256(ffprobe_path),
    }
    write_json(directory / "video-receipt.json", receipt)


def run_gate(
    directory: pathlib.Path, media: pathlib.Path, capture_media: pathlib.Path
) -> tuple[int, list[str], str]:
    result = run(
        [
            sys.executable,
            str(GATE),
            str(media),
            "--release-sha",
            RELEASE_SHA,
            "--capture-media",
            str(capture_media),
        ],
        check=False,
    )
    output = result.stdout + result.stderr
    failures = re.findall(r"::error::  - (\S+)", output)
    return result.returncode, failures, output


def copy_case(
    source_media: pathlib.Path, root: pathlib.Path, name: str
) -> tuple[pathlib.Path, pathlib.Path]:
    directory = root / name
    directory.mkdir()
    media = directory / "merismos-submission.mp4"
    shutil.copy2(source_media, media)
    return directory, media


def load_generator():
    spec = importlib.util.spec_from_file_location("merismos_video_generator", GENERATOR)
    if spec is None or spec.loader is None:
        raise SystemExit("could not load narration generator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prove_speaking_rate() -> None:
    module = load_generator()
    narration = json.loads(NARRATION.read_text(encoding="utf-8"))
    module.validate_spec(narration)
    body = json.loads(
        module.elevenlabs_request_body("A sufficiently long synthetic sentence.", narration)
    )
    observed = body["voice_settings"].get("speed")
    if observed != narration["speakingRate"]:
        raise SystemExit(f"speakingRate was not passed to ElevenLabs: {observed}")
    invalid = dict(narration, speakingRate=1.21)
    try:
        module.validate_spec(invalid)
    except SystemExit:
        pass
    else:
        raise SystemExit("out-of-contract ElevenLabs speakingRate was accepted")
    print(f"[OK ] SPEAKING_RATE                  speed={observed}; invalid rate rejected")


def prove_per_beat_cache() -> None:
    module = load_generator()
    narration = json.loads(NARRATION.read_text(encoding="utf-8"))
    spec, segments = module.validate_spec(narration)
    calls: list[str] = []

    def synthesize(text: str, _spec: dict[str, object]) -> bytes:
        calls.append(text)
        return (f"synthetic-{len(calls)}".encode() * 400)[:4000]

    module.synthesize_elevenlabs = synthesize
    module.duration = lambda _path: 5.0
    with tempfile.TemporaryDirectory(prefix="merismos-narration-cache-") as raw:
        root = pathlib.Path(raw)
        first = []
        second = []
        for index, segment in enumerate(segments, start=1):
            audio = root / f"{index:02d}-{segment['id']}.mp3"
            sidecar = root / f"{index:02d}-{segment['id']}.cache.json"
            first.append(module.synthesize_scene(audio, sidecar, segment, spec, set()))
            second.append(module.synthesize_scene(audio, sidecar, segment, spec, set()))

        changed = dict(segments[3])
        changed["speechText"] += " Corrected."
        audio = root / f"04-{changed['id']}.mp3"
        sidecar = root / f"04-{changed['id']}.cache.json"
        changed_result = module.synthesize_scene(audio, sidecar, changed, spec, set())

    if first != ["synthesized"] * len(SCENE_IDS):
        raise SystemExit(f"cold narration cache did not synthesize all beats: {first}")
    if second != ["reused"] * len(SCENE_IDS):
        raise SystemExit(f"unchanged narration cache did not reuse all beats: {second}")
    if changed_result != "synthesized" or len(calls) != len(SCENE_IDS) + 1:
        raise SystemExit("one changed beat did not cause exactly one additional synthesis")
    print("[OK ] PER_BEAT_CACHE                 cold=7; unchanged=0; one edit=1")


def main() -> int:
    for executable in ("ffmpeg", "ffprobe"):
        if shutil.which(executable) is None:
            raise SystemExit(f"::error::{executable} is required")
    prove_speaking_rate()
    prove_per_beat_cache()
    results = []
    with tempfile.TemporaryDirectory(prefix="merismos-video-selftest-") as raw:
        root = pathlib.Path(raw)
        source = root / "source.mp4"
        make_media(source)

        good_dir = root / "good"
        good_dir.mkdir()
        good = good_dir / "merismos-submission.mp4"
        write_srt(good_dir / "captions.en.srt")
        make_captioned_media(source, good, good_dir / "captions.en.srt")
        write_contracts(good_dir, good, source)
        rc, failures, log = run_gate(good_dir, good, source)
        results.append(("GOOD", rc == 0, rc, failures, log))

        missing_dir, missing_media = copy_case(source, root, "bad-missing-burn-in")
        write_contracts(missing_dir, missing_media, source)
        rc, failures, log = run_gate(missing_dir, missing_media, source)
        results.append(
            (
                "BAD_MISSING_BURN_IN",
                rc != 0 and "caption-pixels-bound" in failures,
                rc,
                failures,
                log,
            )
        )

        partial_dir = root / "bad-within-cue-truncation"
        partial_dir.mkdir()
        partial_media = partial_dir / "merismos-submission.mp4"
        partial_render_srt = root / "partial-render.srt"
        write_srt(partial_render_srt, truncate="live")
        make_captioned_media(source, partial_media, partial_render_srt)
        write_contracts(partial_dir, partial_media, source)
        rc, failures, log = run_gate(partial_dir, partial_media, source)
        results.append(
            (
                "BAD_WITHIN_CUE_TRUNCATION",
                rc != 0
                and "caption-pixels-bound" in failures
                and "failing_cues=4" in log
                and re.search(r"first_failed=cue4/frame\d+@[0-9.]+s", log) is not None,
                rc,
                failures,
                log,
            )
        )

        order_dir, order_media = copy_case(good, root, "bad-order")
        bad_order = ("surface", "hook", *SCENE_IDS[2:])
        write_contracts(order_dir, order_media, source, order=bad_order)
        rc, failures, log = run_gate(order_dir, order_media, source)
        results.append(("BAD_ORDER", rc != 0 and "scene-order" in failures, rc, failures, log))

        caption_dir, caption_media = copy_case(good, root, "bad-caption")
        write_contracts(caption_dir, caption_media, source, overlap=True)
        rc, failures, log = run_gate(caption_dir, caption_media, source)
        results.append(
            (
                "BAD_CAPTION_OVERLAP",
                rc != 0 and "captions-monotonic-nonoverlap" in failures,
                rc,
                failures,
                log,
            )
        )

        av_dir = root / "bad-av"
        av_dir.mkdir()
        av_media = av_dir / "merismos-submission.mp4"
        make_av_mismatch(good, av_media)
        write_contracts(av_dir, av_media, source)
        rc, failures, log = run_gate(av_dir, av_media, source)
        results.append(
            ("BAD_AV_MISMATCH", rc != 0 and "av-duration" in failures, rc, failures, log)
        )

    for name, ok, rc, failures, log in results:
        pixel_match = re.search(r"caption-pixels-bound :: (.+)", log)
        pixel_detail = f" pixels=({pixel_match.group(1)})" if pixel_match else ""
        print(
            f"[{'OK ' if ok else 'FAIL'}] {name:30s} rc={rc} "
            f"failing={failures or '-'}{pixel_detail}"
        )
        if not ok:
            print("---- gate output ----")
            print(log)
            print("---------------------")
    if not all(item[1] for item in results):
        print("::error::video gate self-test failed")
        return 1
    print(
        "video gate self-test: captioned media passed; missing and within-cue truncation, "
        "order, caption, and A/V defects failed closed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
