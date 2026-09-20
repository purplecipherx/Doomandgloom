#!/usr/bin/env python3
"""
Bandwidth-conscious fallback acquisition for videos with no usable transcript.

Policy:
1. Prefer an audio-only stream nearest the 128 kbps target.
2. Explicitly transcode with ffmpeg to a normalized 128 kbps Opus file for diarization/transcription.
3. Only if no audio-only stream is available, fetch a muxed stream whose audio
   is nearest 128 kbps, preferring the smallest/lowest-resolution candidate.
4. ffmpeg extracts/transcodes the audio and the temporary source media is deleted.
5. Preserve info JSON + final audio SHA-256 for the audit trail.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

TARGET_KBPS = 128
AUDIO_EXTENSIONS = {".opus", ".m4a", ".mp3", ".aac", ".ogg", ".wav", ".flac", ".webm"}

def now():
    return datetime.now(timezone.utc).isoformat()

def run(args, timeout=1800):
    return subprocess.run(
        [sys.executable, "-m", "yt_dlp", *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )

def ytdlp_version():
    p = run(["--version"], timeout=30)
    return p.stdout.strip() if p.returncode == 0 else "unknown"

def sha256(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def info_json_for(vdir: Path, vid: str):
    files = sorted(vdir.glob(f"{vid}*.info.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return {}, ""
    p = files[0]
    try:
        return json.loads(p.read_text(encoding="utf-8")), str(p)
    except Exception:
        return {}, str(p)

def final_audio_file(vdir: Path, vid: str):
    candidates = []
    for p in vdir.iterdir():
        if not p.is_file():
            continue
        if p.name.endswith(".info.json") or p.suffix.lower() in {".part", ".ytdl", ".json"}:
            continue
        if p.suffix.lower() in AUDIO_EXTENSIONS:
            candidates.append(p)
    if not candidates:
        return None
    # The postprocessed .opus is expected to be newest.
    return max(candidates, key=lambda p: p.stat().st_mtime)

def download_audio_only(url: str, outtmpl: str):
    return run([
        "--no-playlist",
        "-f", "bestaudio",
        "-S", f"abr~{TARGET_KBPS}",
        "--format-sort-force",
        "--write-info-json",
        "--no-write-comments",
        "-o", outtmpl,
        url,
    ])

def download_muxed_fallback(url: str, outtmpl: str):
    # Only reached when no audio-only stream could be acquired.
    return run([
        "--no-playlist",
        "-f", "best[acodec!=none][vcodec!=none]",
        "-S", f"abr~{TARGET_KBPS},+size,+res,+br",
        "--format-sort-force",
        "--write-info-json",
        "--no-write-comments",
        "-o", outtmpl,
        url,
    ])

def normalize_to_128k(source: Path, output: Path):
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source), "-vn",
        "-c:a", "libopus", "-b:a", f"{TARGET_KBPS}k",
        "-application", "audio",
        str(output),
    ]
    p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       encoding="utf-8", errors="replace", timeout=1800)
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or "ffmpeg audio normalization failed")
    return p

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("queue_csv")
    ap.add_argument("--output-dir", default="")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    queue = Path(args.queue_csv).resolve()
    base = Path(args.output_dir).resolve() if args.output_dir else queue.parent / "audio_fallback"
    base.mkdir(parents=True, exist_ok=True)

    rows = list(csv.DictReader(queue.open(encoding="utf-8-sig")))
    if args.limit > 0:
        rows = rows[:args.limit]

    run_record = {
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_audio_fallback",
        "started_at": now(),
        "queue_csv": str(queue),
        "output_dir": str(base),
        "python_version": sys.version,
        "yt_dlp_version": ytdlp_version(),
        "argv": sys.argv,
        "queued_count": len(rows),
        "target_audio_kbps": TARGET_KBPS,
        "format_rule": (
            "audio-only nearest 128 kbps first; if unavailable, muxed fallback "
            "with audio nearest 128 kbps and smallest/lowest-resolution preference; "
            "extract to 128 kbps Opus; delete temporary video"
        ),
    }
    (base / "run_manifest.json").write_text(json.dumps(run_record, indent=2), encoding="utf-8")

    manifest = []
    for i, row in enumerate(rows, 1):
        vid = row["video_id"]
        url = row["url"]
        vdir = base / vid
        vdir.mkdir(parents=True, exist_ok=True)
        outtmpl = str(vdir / "%(id)s.%(ext)s")

        # Clear stale partials only. Keep prior audit JSON.
        for p in vdir.glob("*.part"):
            try:
                p.unlink()
            except OSError:
                pass

        # Remove stale retained media from an interrupted prior attempt while keeping JSON audit files.
        for old_media in list(vdir.iterdir()):
            if old_media.is_file() and not old_media.name.endswith(".info.json") and old_media.suffix.lower() not in {".json", ".part", ".ytdl"}:
                try:
                    old_media.unlink()
                except OSError:
                    pass

        mode = "audio_only"
        p = download_audio_only(url, outtmpl)
        source_media = final_audio_file(vdir, vid)

        if not source_media:
            mode = "muxed_video_fallback"
            p = download_muxed_fallback(url, outtmpl)
            # Muxed files may have a video extension; choose the largest non-JSON media file.
            media_candidates = [
                x for x in vdir.iterdir()
                if x.is_file() and not x.name.endswith(".info.json")
                and x.suffix.lower() not in {".json", ".part", ".ytdl"}
            ]
            source_media = max(media_candidates, key=lambda x: x.stat().st_size) if media_candidates else None

        info, info_path = info_json_for(vdir, vid)
        audio = None
        ffmpeg_error = ""
        if source_media:
            audio = vdir / f"{vid}.128k.opus"
            try:
                normalize_to_128k(source_media, audio)
            except Exception as e:
                ffmpeg_error = repr(e)
                audio = None
            finally:
                if source_media and source_media.exists() and (audio is None or source_media.resolve() != audio.resolve()):
                    try:
                        source_media.unlink()
                    except OSError:
                        pass

        if audio and audio.exists():
            status = "downloaded"
            digest = sha256(audio)
            rel = str(audio.relative_to(queue.parent))
        else:
            status = "failed"
            digest = ""
            rel = ""

        requested = info.get("requested_downloads") or []
        selected = requested[0] if requested else info
        rec = {
            "video_id": vid,
            "url": url,
            "title": row.get("title", ""),
            "downloaded_at": now(),
            "status": status,
            "acquisition_mode": mode,
            "target_audio_kbps": TARGET_KBPS,
            "source_format_id": selected.get("format_id", ""),
            "source_ext": selected.get("ext", ""),
            "source_abr_kbps": selected.get("abr", info.get("abr", "")),
            "source_tbr_kbps": selected.get("tbr", info.get("tbr", "")),
            "source_height": selected.get("height", info.get("height", "")),
            "source_filesize": selected.get("filesize", selected.get("filesize_approx", "")),
            "final_audio_codec": "opus",
            "final_audio_kbps": TARGET_KBPS,
            "audio_path": rel,
            "sha256": digest,
            "info_json_path": info_path,
            "temporary_source_media_retained": bool(source_media and source_media.exists() and (audio is None or source_media.resolve() != audio.resolve())),
            "ffmpeg_error": ffmpeg_error,
            "stderr_tail": p.stderr[-1200:],
        }
        manifest.append(rec)
        (vdir / "audio_manifest.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
        print(f"[audio] {i}/{len(rows)} {vid}: {status} mode={mode} target={TARGET_KBPS}kbps", flush=True)

    with (base / "audio_manifest.jsonl").open("w", encoding="utf-8") as f:
        for r in manifest:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    run_record["completed_at"] = now()
    run_record["status"] = "complete"
    run_record["downloaded_count"] = sum(1 for r in manifest if r["status"] == "downloaded")
    run_record["failed_count"] = sum(1 for r in manifest if r["status"] == "failed")
    run_record["muxed_fallback_count"] = sum(1 for r in manifest if r["acquisition_mode"] == "muxed_video_fallback")
    (base / "run_manifest.json").write_text(json.dumps(run_record, indent=2), encoding="utf-8")

if __name__ == "__main__":
    main()
