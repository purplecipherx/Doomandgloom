# Audit Trail Standard

Every ingestion and research step must be reproducible.

## Every acquisition run records

- run ID
- UTC timestamp
- operator/machine optional label
- exact input URL/query
- tool name
- tool version
- command/options
- output directory
- success/failure
- error text
- produced files
- hashes of preserved source artifacts

## Every source artifact records

- canonical source ID
- original URL
- archive URL when available
- publication/upload date
- retrieval date
- author/channel/publisher
- file path
- SHA-256
- extraction method
- whether content is original or derivative
- linked entity IDs
- linked claim IDs
- linked product IDs
- linked money-flow IDs

## YouTube/video rule

Priority:
1. creator captions
2. platform auto-captions
3. publisher transcript
4. **audio-only** download for local transcription

Do not download video merely to obtain speech.

If audio fallback is required, use the platform's audio-only stream. Preserve:
- video ID
- audio file
- info JSON
- hash
- download timestamp
- transcript model/version/settings later used

Video is fetched only if a later human-verification task specifically requires visual evidence.

## Transcript provenance

Every transcript segment must identify:
- source video/audio
- caption/transcription method
- timestamp start/end
- language
- manual/auto/local transcription
- verification status

## Derived-data rule

Never overwrite raw evidence.

Use:
raw source → normalized source → extracted claims/entities → analysis

Derived files point backward to the source IDs they came from.

## Audit log

Maintain append-only run/event logs whenever practical.

Corrections create new records; they do not erase historical records.
