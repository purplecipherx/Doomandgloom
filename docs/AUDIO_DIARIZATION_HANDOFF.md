# Audio / Diarization Handoff

## Locked acquisition order

For every media item:

1. Use publisher/manual transcript if available.
2. Otherwise use platform-generated captions.
3. Otherwise download **audio only**.
4. Send audio to the M0J1M0J1 diarization/transcription pipeline.
5. Preserve speaker-attributed, timestamped output.
6. Never bulk-download video.

Video imagery is outside the bulk pipeline. Visual media is reviewed only when a specific claim requires visual verification.

## Why diarization matters

Many network videos are interviews, panels, conferences, podcasts, and roundtables. A transcript without speaker identity can falsely attribute a statement to the host, guest, sponsor, or panelist.

Captionless audio therefore enters the diarization queue before claim extraction.

## Handoff manifest

Each audio item should provide:

- video_id / content_id
- canonical_url
- title
- channel/publisher
- upload/publication date
- audio_path
- audio_sha256
- acquisition_timestamp
- acquisition_run_id
- original duration when known
- source platform
- expected speakers if known
- diarization_status
- transcription_status

## Expected M0J1M0J1 output

Prefer JSONL segments:

```json
{"start":12.41,"end":18.03,"speaker":"SPEAKER_00","text":"...","confidence":0.94}
```

Optional speaker resolution layer:

```json
{"speaker":"SPEAKER_00","resolved_entity_id":"fitts_catherine","resolution":"verified","evidence":"host introduction at 00:00:42"}
```

Never rewrite raw diarizer labels in the preserved source output. Store resolved identities as a derived layer.

## Audit trail

Keep all stages:

```text
original source URL
  -> audio-only acquisition
  -> audio SHA-256
  -> raw diarization output
  -> transcription output
  -> speaker-resolution mapping
  -> normalized transcript
  -> extracted claims
```

Each derived artifact references its immediate parent and the original source ID.

## Speaker identity states

- VERIFIED
- HIGH_CONFIDENCE
- POSSIBLE
- UNKNOWN

Only VERIFIED or sufficiently supported HIGH_CONFIDENCE identities should be used for damaging attributed quotations.

## Output into Doomandgloom

Final normalized segments should contain:

- content_id
- start_seconds
- end_seconds
- raw_speaker_label
- resolved_entity_id
- speaker_resolution_status
- text
- transcription_confidence
- source_audio_sha256
- diarizer_version/run ID
- transcription_model/version
- verified_against_audio

This becomes the source for claim, product, sponsor, prediction, and conflict extraction.
