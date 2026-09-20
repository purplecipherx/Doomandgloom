# Network-Wide Content Ingestion

## Principle

Ingest the public information ecosystem around **every discovered node**, not only the original seed personalities.

## Platforms / source classes

### Video
- YouTube
- Rumble
- Odysee
- Vimeo
- conference-hosted video archives
- embedded videos on personal/company sites

### Audio / podcasts
- Apple Podcasts
- Spotify episode metadata/show notes
- RSS feeds
- podcast-hosting archives
- downloadable MP3s
- syndicated radio archives

### Written media
- official websites
- newsletters
- Substack
- blogs
- press releases
- product pages
- sales pages
- FAQs
- terms/refund pages
- conference programs
- speaker bios
- sponsor/exhibitor pages

### Social / community
- Reddit
- public X/Twitter posts
- public Facebook pages where accessible
- public Telegram channels where lawfully accessible
- forums / message boards
- YouTube comments when material
- public Discord archives only where legitimately accessible

### Records
- court filings
- regulators
- corporate registries
- charity filings
- patents/trademarks
- procurement
- campaign/lobbying records where materially relevant
- scientific literature
- retraction databases

## Caption / transcript strategy

Use existing captions/transcripts first.

Priority:
1. creator-provided transcript/captions
2. platform auto-captions
3. podcast transcript supplied by publisher
4. third-party transcript supplied by original publisher
5. only then local speech-to-text

## Every ingested content item must preserve

- canonical content ID
- platform
- creator/channel/entity
- title
- date
- URL
- archive URL when available
- transcript/caption provenance
- timestamps
- raw text
- normalized text
- SHA/hash where locally preserved
- detected names/entities
- products
- sponsors
- promo codes
- claims
- predictions
- calls to action
- money/conflict references
- source IDs

## Automatic discovery from transcripts/text

Extract:
- new people
- company names
- products
- conferences
- sponsors
- cited researchers
- books/reports
- nonprofits
- manufacturers
- affiliate codes
- discount codes
- URLs
- claimed government contacts
- claimed clients
- claims of prior prediction success
- research citations
- investment/stock/commodity mentions

Every new entity goes into a **discovery queue** for validation and graph expansion.

## Co-appearance and amplification

Track:
- who interviews whom
- who introduces whom
- who repeatedly appears together
- who shares the same sponsors
- who cites the same source
- who promotes the same product
- who posts the same claim within a narrow period
- who sends audiences to the same conference/newsletter/store

## Goal

Build the network from the evidence itself.

The system should be able to discover an unknown person from a sponsor read, then discover their company, then find its owners, then find its manufacturers, then find its other promoters, and bring those entities back into the graph.
