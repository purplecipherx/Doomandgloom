# YouTube Channel Harvester

## Purpose

Given a channel URL, collect the **entire video list first**, then retrieve all existing captions without downloading media.

For a normal channel URL the harvester inventories:
- Videos
- Shorts
- Streams

and deduplicates by YouTube video ID.

## Windows setup

From the repo root:

    .\scripts\setup_youtube_harvester.ps1

## Inventory only — do this first

    .\scripts\run_youtube_channel_harvest.ps1 -Url "https://www.youtube.com/@CHANNEL" -Name "channel_name" -InventoryOnly

Outputs:
- inventory.csv
- inventory.jsonl
- inventory_summary.json

## Harvest all existing English captions

    .\scripts\run_youtube_channel_harvest.ps1 -Url "https://www.youtube.com/@CHANNEL" -Name "channel_name"

The tool prefers creator/manual English captions, otherwise YouTube auto-captions.

It stores:
- raw VTT
- normalized searchable text
- timestamped JSONL segments
- per-video metadata JSON
- caption status

## Captionless queue

Anything lacking usable captions appears in:

    needs_transcription.csv

## Audio-only fallback

This downloads **only YouTube's audio stream**, not video:

    .\scripts\download_captionless_audio.ps1 -QueueCsv ".\research\youtube\channel_name\needs_transcription.csv"

For testing:

    .\scripts\download_captionless_audio.ps1 -QueueCsv ".\research\youtube\channel_name\needs_transcription.csv" -Limit 5

The audio downloader uses yt-dlp format `bestaudio`. If an audio-only stream cannot be obtained, it fails rather than silently downloading video.

## Resume behavior

Caption harvesting stores one result JSON per video. Restarting the same channel skips completed per-video results.

## Audit trail

Raw captions/audio are never replaced by normalized or derived data. SHA-256 hashes and metadata are retained so claims can be traced back to the acquired source.

## Recommended workflow

1. inventory only;
2. inspect `inventory.csv`;
3. run caption harvest;
4. inspect `needs_transcription.csv`;
5. download audio-only for those videos;
6. transcribe only that fallback set;
7. sync repo / research artifacts according to storage policy.
