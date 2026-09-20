#!/usr/bin/env python3
"""
Doomandgloom captionless-audio fallback using the proven M0J1M0J1 core:
  - pyannote/speaker-diarization-community-1
  - WhisperX transcription + forced alignment

This intentionally omits M0J1M0J1's TTS-specific embedding/clustering/export stages.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MOJI_DIARIZER_MODEL = "pyannote/speaker-diarization-community-1"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def annotation_items(annotation):
    # Matches the compatibility behavior used in M0J1M0J1/voice_harvester/diarize.py.
    if hasattr(annotation, "itertracks"):
        for turn, _, speaker in annotation.itertracks(yield_label=True):
            yield float(turn.start), float(turn.end), str(speaker)
    else:
        for turn, speaker in annotation:
            yield float(turn.start), float(turn.end), str(speaker)


def mark_overlaps(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = sorted(rows, key=lambda x: (x["start"], x["end"]))
    active: list[dict[str, Any]] = []
    for row in rows:
        active = [a for a in active if a["end"] > row["start"]]
        for a in active:
            overlap = min(a["end"], row["end"]) - max(a["start"], row["start"])
            if a["speaker"] != row["speaker"] and overlap > 0.03:
                a["overlap"] = 1
                row["overlap"] = 1
        active.append(row)
    return rows


def overlap_seconds(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def choose_speaker(start: float, end: float, diar: list[dict[str, Any]]) -> tuple[str, float]:
    scores: dict[str, float] = {}
    for d in diar:
        ov = overlap_seconds(start, end, float(d["start"]), float(d["end"]))
        if ov > 0:
            scores[d["speaker"]] = scores.get(d["speaker"], 0.0) + ov
    if not scores:
        return "UNKNOWN_SPEAKER", 0.0
    speaker, sec = max(scores.items(), key=lambda kv: kv[1])
    dur = max(0.001, end - start)
    return speaker, min(1.0, sec / dur)


def load_audio_manifest(audio_root: Path) -> list[dict[str, Any]]:
    manifest = audio_root / "audio_manifest.jsonl"
    if not manifest.exists():
        raise SystemExit(f"Missing audio manifest: {manifest}")
    rows = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def resolve_audio_path(channel_root: Path, audio_root: Path, rec: dict[str, Any]) -> Path | None:
    # New manifest path is relative to channel root; support direct and fallback guesses.
    raw = rec.get("audio_path") or ""
    candidates = []
    if raw:
        candidates.append(channel_root / raw)
        candidates.append(audio_root / Path(raw).name)
    vid = str(rec.get("video_id") or "")
    vdir = audio_root / vid
    if vdir.exists():
        candidates.extend(
            p for p in vdir.iterdir()
            if p.is_file() and p.suffix.lower() not in {".json", ".part", ".ytdl"}
        )
    for p in candidates:
        if p.exists() and p.is_file():
            return p.resolve()
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Diarize + transcribe captionless YouTube audio using the M0J1M0J1 core stack.")
    ap.add_argument("--channel-root", required=True, help="research/youtube/<channel> directory")
    ap.add_argument("--audio-root", default="", help="Defaults to <channel-root>/audio_fallback")
    ap.add_argument("--output", default="", help="Defaults to <channel-root>/moji")
    ap.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    ap.add_argument("--whisper-model", default="medium.en")
    ap.add_argument("--language", default="en")
    ap.add_argument("--compute-type", default="int8")
    ap.add_argument("--batch-size", type=int, default=4)
    ap.add_argument("--hf-token", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    import torch
    import whisperx
    from pyannote.audio import Pipeline

    channel_root = Path(args.channel_root).resolve()
    audio_root = Path(args.audio_root).resolve() if args.audio_root else channel_root / "audio_fallback"
    output = Path(args.output).resolve() if args.output else channel_root / "moji"
    output.mkdir(parents=True, exist_ok=True)

    token = args.hf_token or os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")
    if not token:
        raise SystemExit(
            "HF token required for pyannote Community-1. "
            "Set $env:HF_TOKEN='hf_...' after accepting the model terms."
        )

    device = args.device
    compute_type = args.compute_type
    if device == "cuda" and not torch.cuda.is_available():
        print("CUDA requested but unavailable; falling back to CPU/int8.", flush=True)
        device, compute_type = "cpu", "int8"

    rows = [r for r in load_audio_manifest(audio_root) if r.get("status") == "downloaded"]
    if args.limit > 0:
        rows = rows[: args.limit]

    run = {
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_moji",
        "started_at": now(),
        "channel_root": str(channel_root),
        "audio_root": str(audio_root),
        "output": str(output),
        "python": sys.version,
        "platform": platform.platform(),
        "torch_version": getattr(torch, "__version__", ""),
        "cuda_available": bool(torch.cuda.is_available()),
        "device": device,
        "compute_type": compute_type,
        "diarizer_model": MOJI_DIARIZER_MODEL,
        "whisper_model": args.whisper_model,
        "language": args.language,
        "batch_size": args.batch_size,
        "argv": sys.argv,
        "input_count": len(rows),
        "source_code_provenance": {
            "project": "purplecipherx/M0J1M0J1",
            "components_reused": [
                "voice_harvester/diarize.py algorithm/model selection",
                "voice_harvester/export.py WhisperX model/alignment configuration"
            ]
        }
    }
    (output / "run_manifest.json").write_text(json.dumps(run, indent=2), encoding="utf-8")

    print(f"Loading diarizer: {MOJI_DIARIZER_MODEL}", flush=True)
    diarizer = Pipeline.from_pretrained(MOJI_DIARIZER_MODEL, token=token)
    diarizer.to(torch.device(device))

    print(f"Loading WhisperX: {args.whisper_model}", flush=True)
    whisper = whisperx.load_model(
        args.whisper_model,
        device,
        compute_type=compute_type,
        language=args.language,
    )
    align_model = None
    align_meta = None
    align_lang = None

    summary: list[dict[str, Any]] = []

    for idx, rec in enumerate(rows, 1):
        vid = str(rec["video_id"])
        vout = output / vid
        final_path = vout / "speaker_transcript.json"
        if final_path.exists() and not args.force:
            print(f"[{idx}/{len(rows)}] {vid}: already complete", flush=True)
            summary.append({"video_id": vid, "status": "already_complete", "output": str(final_path)})
            continue

        audio = resolve_audio_path(channel_root, audio_root, rec)
        if audio is None:
            print(f"[{idx}/{len(rows)}] {vid}: audio missing", flush=True)
            summary.append({"video_id": vid, "status": "audio_missing"})
            continue

        vout.mkdir(parents=True, exist_ok=True)
        digest = sha256_file(audio)
        expected = rec.get("sha256") or ""
        if expected and expected != digest:
            print(f"[{idx}/{len(rows)}] {vid}: HASH MISMATCH", flush=True)
            summary.append({"video_id": vid, "status": "hash_mismatch", "expected": expected, "actual": digest})
            continue

        print(f"[{idx}/{len(rows)}] diarize: {vid}", flush=True)
        dout = diarizer(str(audio))
        ann = getattr(dout, "speaker_diarization", dout)
        diar = []
        for start, end, speaker in annotation_items(ann):
            if end > start:
                diar.append({
                    "start": start,
                    "end": end,
                    "duration": end - start,
                    "speaker": speaker,
                    "overlap": 0,
                })
        diar = mark_overlaps(diar)
        (vout / "diarization.json").write_text(
            json.dumps({
                "video_id": vid,
                "audio_path": str(audio),
                "audio_sha256": digest,
                "model": MOJI_DIARIZER_MODEL,
                "segments": diar,
            }, indent=2),
            encoding="utf-8",
        )

        print(f"[{idx}/{len(rows)}] transcribe/align: {vid}", flush=True)
        wav = whisperx.load_audio(str(audio))
        result = whisper.transcribe(wav, batch_size=args.batch_size)
        lang = result.get("language") or args.language

        if align_model is None or align_meta is None or align_lang != lang:
            align_model, align_meta = whisperx.load_align_model(language_code=lang, device=device)
            align_lang = lang

        aligned = whisperx.align(
            result["segments"],
            align_model,
            align_meta,
            wav,
            device,
            return_char_alignments=False,
        )

        out_segments = []
        for seg in aligned.get("segments", []):
            start = float(seg.get("start", 0.0))
            end = float(seg.get("end", start))
            speaker, coverage = choose_speaker(start, end, diar)
            out_segments.append({
                "start": start,
                "end": end,
                "speaker": speaker,
                "speaker_overlap_coverage": coverage,
                "text": " ".join(str(seg.get("text") or "").split()),
                "words": seg.get("words") or [],
            })

        payload = {
            "video_id": vid,
            "canonical_url": rec.get("url"),
            "title": rec.get("title"),
            "source_audio": str(audio),
            "source_audio_sha256": digest,
            "acquired_at": rec.get("downloaded_at"),
            "processed_at": now(),
            "language": lang,
            "diarizer_model": MOJI_DIARIZER_MODEL,
            "whisper_model": args.whisper_model,
            "device": device,
            "compute_type": compute_type,
            "segments": out_segments,
        }
        final_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        with (vout / "speaker_transcript.jsonl").open("w", encoding="utf-8") as f:
            for seg in out_segments:
                f.write(json.dumps({
                    "video_id": vid,
                    "source_audio_sha256": digest,
                    **seg
                }, ensure_ascii=False) + "\n")

        summary.append({
            "video_id": vid,
            "status": "complete",
            "audio_sha256": digest,
            "diarization_segments": len(diar),
            "transcript_segments": len(out_segments),
            "output": str(final_path),
        })

    with (output / "processing_summary.jsonl").open("w", encoding="utf-8") as f:
        for item in summary:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    run["completed_at"] = now()
    run["complete"] = sum(1 for x in summary if x["status"] in {"complete", "already_complete"})
    run["failed"] = sum(1 for x in summary if x["status"] not in {"complete", "already_complete"})
    run["status"] = "complete"
    (output / "run_manifest.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
