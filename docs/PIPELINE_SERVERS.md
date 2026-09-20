# CPU/GPU Pipeline Services

## Architecture

The runtime is split into three localhost services:

- Job hub (`127.0.0.1:8765`): durable SQLite/WAL queue, leases, retries, events, idempotent job keys.
- CPU service (`127.0.0.1:8766`): concurrent YouTube harvest, caption processing, 128 kbps audio prefetch, transcript-unit ledger, semantic-review batching, spider/index work.
- GPU service (`127.0.0.1:8767`): exactly one M0J1M0J1/WhisperX consumer by default.

The GPU service never downloads source audio. CPU workers prefetch and normalize audio first, then enqueue a GPU-ready job.

## Flow

1. `harvest_channel` (CPU/network)
2. `analysis_sync` + `spider_channel` (CPU) can start on captioned material immediately.
3. `prepare_audio` (CPU/network/ffmpeg) downloads only true captionless items and normalizes to 128 kbps Opus.
4. If audio is ready, `gpu_moji_channel` is queued.
5. GPU runs scan -> diarize -> embed -> cluster -> extract -> transcribe -> timestamp bridge.
6. GPU completion enqueues a second `analysis_sync` and `spider_channel` so diarized material joins the same evidence system.
7. `analysis_sync` creates stable transcript units and semantic-review batches.

## Durability

Jobs have stable keys, priorities, attempts, leases, heartbeats, completion results and event history. Expired leases are requeued. Runtime state is local under `research/runtime/` and is ignored by Git.

## Transcript evidence

Every transcript unit has a stable `TU_...` ID tied to source SHA-256, content ID, timestamp span, speaker, text and unit index. If a transcript artifact changes, old units are retained as `SUPERSEDED`; new units become `CURRENT`.

## Review lane

Semantic review batches are written under `data/analysis/review_batches/pending/` and also represented as `review` lane jobs in the hub. These are intentionally not consumed by regex heuristics.

Each unit must be classified and inspected for all mentions, atomic claims, claims about people/organizations, relationships, products/services/sponsors/CTAs, predictions, money/conflict signals, and cited sources.

Every atomic factual claim receives a stable `CL_...` ID and is placed in `data/analysis/fact_check_queue.csv` until reviewed.

## Controls

Start services:

    powershell.exe -ExecutionPolicy Bypass -File .\scripts\start_pipeline_servers.ps1

Queue verified YouTube channels:

    .\.venv-youtube\Scripts\python.exe .\scripts\queue_youtube_corpus.py

Status:

    powershell.exe -ExecutionPolicy Bypass -File .\scripts\pipeline_status.ps1

Stop:

    powershell.exe -ExecutionPolicy Bypass -File .\scripts\stop_pipeline_servers.ps1
