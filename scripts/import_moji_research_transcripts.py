#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, json
from pathlib import Path

def load_audio_manifest(path: Path):
    by_stem = {}
    if not path.exists():
        return by_stem
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        ap = r.get("audio_path") or ""
        if ap:
            by_stem[Path(ap).stem] = r
        if r.get("video_id"):
            by_stem[r["video_id"]] = r
    return by_stem

def find_map(maps, t):
    for m in maps:
        if float(m["master_start"]) <= t <= float(m["master_end"]):
            return m
    return None

def src_time(master_t, m):
    return float(m["source_start"]) + (master_t - float(m["master_start"]))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--moji-output", required=True)
    ap.add_argument("--audio-manifest", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    moji = Path(args.moji_output).resolve()
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    audio_meta = load_audio_manifest(Path(args.audio_manifest))

    rows = []
    speakers_root = moji / "speakers"
    if not speakers_root.exists():
        raise SystemExit(f"Missing Moji speakers directory: {speakers_root}")

    for spkdir in sorted(speakers_root.iterdir()):
        if not spkdir.is_dir():
            continue
        map_path = spkdir / "master_map.json"
        tx_path = spkdir / "transcript.aligned.json"
        if not (map_path.exists() and tx_path.exists()):
            continue

        mp = json.loads(map_path.read_text(encoding="utf-8"))
        tx = json.loads(tx_path.read_text(encoding="utf-8"))
        maps = mp.get("segments") or []
        speaker_id = tx.get("speaker_id") or mp.get("global_speaker_id") or spkdir.name
        display_name = tx.get("display_name") or mp.get("display_name") or ""

        words = []
        for seg in tx.get("segments") or []:
            words.extend(seg.get("words") or [])

        current = None
        for w in words:
            if w.get("start") is None or w.get("end") is None:
                continue
            ws, we = float(w["start"]), float(w["end"])
            m = find_map(maps, (ws + we) / 2.0)
            if not m:
                continue
            source = Path(m["source_path"])
            start = src_time(ws, m)
            end = src_time(we, m)
            token = str(w.get("word") or "")
            key = (str(source), speaker_id)

            if current and current["_key"] == key and start - current["end_seconds"] < 1.25:
                current["text"] += token
                current["end_seconds"] = end
            else:
                if current:
                    rows.append(current)
                meta = audio_meta.get(source.stem, {})
                current = {
                    "_key": key,
                    "video_id": meta.get("video_id", source.stem),
                    "canonical_url": meta.get("url", ""),
                    "title": meta.get("title", ""),
                    "speaker_id": speaker_id,
                    "speaker_display_name": display_name,
                    "start_seconds": start,
                    "end_seconds": end,
                    "text": token,
                    "source_audio_path": str(source),
                    "source_audio_sha256": meta.get("sha256", ""),
                    "moji_master_map": str(map_path),
                    "moji_transcript": str(tx_path),
                }
        if current:
            rows.append(current)

    rows.sort(key=lambda r: (r["video_id"], r["start_seconds"], r["speaker_id"]))
    fields = [
        "video_id","canonical_url","title","speaker_id","speaker_display_name",
        "start_seconds","end_seconds","text","source_audio_path",
        "source_audio_sha256","moji_master_map","moji_transcript"
    ]

    csv_path = out / "diarized_transcript.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k:r.get(k,"") for k in fields})

    jsonl_path = out / "diarized_transcript.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for r in rows:
            rr = {k:v for k,v in r.items() if k != "_key"}
            f.write(json.dumps(rr, ensure_ascii=False) + "\n")

    manifest = {
        "moji_output": str(moji),
        "audio_manifest": str(Path(args.audio_manifest).resolve()),
        "row_count": len(rows),
        "csv": str(csv_path),
        "jsonl": str(jsonl_path),
    }
    (out / "import_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Restored {len(rows)} speaker-attributed rows to original source timestamps.")
    print(csv_path)

if __name__ == "__main__":
    main()
