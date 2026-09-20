# YouTube Transcript Ingestion

## Goal

Ingest large amounts of YouTube speech **without running our own transcription whenever captions already exist**.

## Source priority

1. Creator-uploaded/manual captions
2. YouTube auto-generated captions
3. Public transcript/caption extraction via yt-dlp
4. Only if no captions exist: optional local speech-to-text fallback

## Important API limitation

YouTube automatically generates captions for many videos, but the official YouTube Data API only permits downloading a caption track when the authenticated user has permission to edit that video.

For public third-party research videos, use public caption extraction rather than relying on the official caption-download API.

## Default no-audio workflow

Use yt-dlp to inspect and fetch subtitles without downloading the video/audio.

Examples:

    yt-dlp --list-subs "VIDEO_URL"

    yt-dlp       --skip-download       --write-subs       --write-auto-subs       --sub-langs "en.*,en"       --sub-format "vtt/best"       -o "raw/youtube/%(channel_id)s/%(id)s/%(id)s.%(ext)s"       "VIDEO_URL"

This gives us timestamped caption files while avoiding media download.

## Data to preserve

For every video:
- video ID
- canonical URL
- channel ID/name
- title
- upload date
- duration
- caption language
- manual vs auto-generated if detectable
- caption format
- raw caption file path
- SHA-256 hash
- ingestion date
- caption extraction method
- source quality notes

## Parsing rules

Preserve the raw caption file unchanged.

Generate a normalized transcript that:
- keeps timestamps;
- removes duplicate rolling-caption fragments;
- normalizes whitespace;
- preserves meaningful pauses where possible;
- does not silently "correct" controversial wording;
- links every extracted claim back to timestamp ranges.

## Quote verification

YouTube auto-captions are useful for search/discovery but are not perfect.

Before publishing a damaging direct quote:
1. use the transcript to locate the timestamp;
2. check the original video/audio at that timestamp;
3. store the verified wording and timestamp;
4. mark whether wording came from manual captions, auto captions, or human verification.

## Speaker attribution

Do not infer speaker identity from auto-captions alone when multiple speakers are present.

Possible labels:
- KNOWN_HOST
- KNOWN_GUEST
- UNKNOWN_SPEAKER
- MULTIPLE_SPEAKERS

If speaker identity materially affects a claim, verify from the video/audio.

## Claim extraction

From normalized transcript, extract:
- factual claims;
- predictions;
- named people/companies;
- products;
- prices;
- discount codes;
- sponsor reads;
- calls to action;
- fear/urgency language;
- government-adviser claims;
- claims of proprietary technology;
- claims of prior prediction success;
- corrections/retractions.

Each extracted item must keep:
- start time;
- end time;
- exact/near-exact text;
- video ID;
- entity IDs;
- linked product IDs;
- linked money/conflict IDs.

## Product-pitch adjacency

Record whether a claim occurs:
- in same segment as a product pitch;
- within 1 minute;
- within 5 minutes;
- in description/show notes;
- in pinned comments.

This supports the fear-to-commerce analysis.

## Sponsor extraction

Search transcript/show notes for:
- sponsor
- sponsored by
- partner
- affiliate
- promo code
- discount code
- use code
- link below
- shop
- subscribe
- premium
- membership
- report
- conference
- consultation

## Scale strategy

Do not download full media by default.

For a channel or playlist:
1. enumerate video metadata;
2. test caption availability;
3. fetch captions only;
4. hash/store raw VTT;
5. normalize;
6. index text;
7. extract claims/entities/products;
8. queue only captionless/high-priority videos for speech-to-text.

This makes thousands of videos practical without GPU transcription.

## Failure modes

Captions may be unavailable because:
- creator disabled them;
- language unsupported;
- poor audio;
- overlapping speakers;
- long/complex audio;
- YouTube has not generated them;
- extraction temporarily fails.

Record the failure reason and do not silently treat missing captions as missing speech.

## Research standard

Captions are **discovery evidence**.

For high-stakes claims, the original audio/video at the cited timestamp is the final source.
