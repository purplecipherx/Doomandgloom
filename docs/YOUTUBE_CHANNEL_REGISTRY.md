# YouTube Channel Registry + Batch Harvest

Doomandgloom now separates **channel discovery** from **channel harvesting**.

## Verified registry

`data/youtube_channels.csv` contains known channels. Only rows with:

- `verification_status=verified`
- `enabled=true`

are automatically harvested.

Candidate/ambiguous channels are deliberately excluded until verified.

## Discover candidates for every entity

This searches YouTube for every row in `data/entities.csv` and creates an audit/review file:

```powershell
.\.venv-youtube\Scripts\python.exe .\scripts\discover_youtube_channels.py
```

Output:

`data/youtube_channel_candidates.csv`

This allows the network to expand without manually finding every URL.

## Batch inventory every verified channel

```powershell
powershell.exe -ExecutionPolicy Bypass -File ".\scripts\run_all_youtube_channels.ps1" -Mode inventory
```

## Batch captions

```powershell
powershell.exe -ExecutionPolicy Bypass -File ".\scripts\run_all_youtube_channels.ps1" -Mode captions
```

## Full pipeline

```powershell
powershell.exe -ExecutionPolicy Bypass -File ".\scripts\run_all_youtube_channels.ps1" -Mode full
```

Full mode means:

existing captions first → audio-only for missing captions → M0J1M0J1 diarization/transcription.

No bulk video download.

## Audit behavior

Every per-channel run retains its own manifest. The batch runner additionally records:

- channel ID
- entity ID
- URL
- mode
- start/end UTC
- exit code

A failed channel does not terminate harvesting of all later channels.
