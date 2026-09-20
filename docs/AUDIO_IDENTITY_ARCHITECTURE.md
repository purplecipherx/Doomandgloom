# Corpus Audio / Voice Identity Architecture

## Purpose

Combine diarization, corpus-wide voice matching, transcript/context analysis and reviewed identity evidence without confusing acoustic similarity with proven identity.

## Identity layers

1. `raw_speaker_id` — local/M0J1M0J1 diarization/global-cluster label preserved exactly.
2. `acoustic_cluster_id` — versioned corpus observation of an acoustic cluster.
3. `canonical_voice_id` — persistent corpus identity such as `VOICE_00000042`; may remain unnamed.
4. `resolved_entity_id` — investigated person/entity identity only after evidence review.

Raw IDs are never rewritten. Improved identity resolution is additive.

## Central local database

`research/audio_identity/voice_identity.sqlite` stores:
- audio assets keyed by SHA-256;
- acoustic clusters and centroids;
- cluster source membership;
- clean voice exemplars;
- canonical speaker identities;
- cluster-to-canonical bindings;
- transcript/context identity evidence;
- pairwise/ranked voice-match candidates;
- fused identity hypotheses;
- verified reference clips;
- identity events/audit history.

The SQLite database and audio vault are local runtime/evidence storage and are ignored by Git. Reviewable CSV exports live under `data/audio/`.

## Audio vault

`research/audio_vault/` is content-addressed by SHA-256.

Retention tiers:
- full 128 kbps source audio where required for captionless transcription/provenance or explicitly retained for investigation;
- clean 16 kHz mono FLAC diarized exemplars for speaker recognition;
- multiple reviewed reference clips for verified canonical speakers.

Captioned media can contribute voice exemplars without requiring redundant transcription. Bulk source video remains excluded.

## Voice matching

Acoustic centroids are compared across files/channels. Candidate records preserve:
- cosine similarity;
- rank from each side;
- nearest-neighbor margin;
- same-channel flag;
- review status.

A high acoustic score creates an identity lead, not a named-speaker fact.

## Transcript/context identity evidence

Semantic review can emit explicit identity clues:
- SELF_IDENTIFICATION;
- HOST_INTRODUCTION / EXPLICIT_INTRODUCTION;
- CHANNEL_HOST_METADATA;
- DIRECT_ADDRESS;
- TITLE_METADATA;
- CO_SPEAKER_REFERENCE;
- TRANSCRIPT_CONTEXT.

Every clue references the exact transcript unit, acoustic cluster, content ID, timestamp and evidence text.

## Evidence fusion

`audio_identity_db.py fuse-identities` combines contextual evidence with acoustic support from already reviewed reference voices.

Possible states include:
- WEAK;
- OPEN;
- ACOUSTIC_CANDIDATE;
- HIGH_CONFIDENCE_CANDIDATE;
- HIGH_CONFIDENCE;
- VERIFIED;
- REJECTED.

Fusion does not automatically produce VERIFIED identity. Approval is an explicit audited action.

## Attribution gate

For potentially damaging attributed quotations:
- VERIFIED is preferred;
- HIGH_CONFIDENCE requires multiple compatible evidence classes and no material conflict;
- ACOUSTIC_CANDIDATE / POSSIBLE / UNKNOWN cannot be treated as identified speakers in published findings.

## Pipeline

CPU acquisition -> GPU diarization/transcription -> CPU audio identity sync -> voice-aware timestamp bridge -> transcript ledger -> semantic identity clues -> identity fusion/review -> updated canonical binding.

The GPU does not perform the corpus-wide identity search, so it can return immediately to queued GPU work.

## Exported review files

- `data/audio/speaker_resolution_current.csv`
- `data/audio/identity_hypotheses.csv`
- `data/audio/voice_match_candidates.csv`
- `data/analysis/speaker_identity_clues.csv`

These are intended for review, audit and model calibration without committing the audio corpus itself.

## Calibration

Voice thresholds must be calibrated against a labeled corpus containing same-speaker and different-speaker pairs across microphones, compression, age/date, noise and speaking styles. False merges receive a substantially larger penalty than false splits.
