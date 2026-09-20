# Recursive Transcript Spider

## Purpose

After every completed transcription batch, Doomandgloom scans the text for **new things worth investigating**.

The spider is intentionally broad. It looks for mentions of:

- people
- organizations
- YouTube channels
- podcasts/shows
- websites/domains
- companies/nonprofits
- products/services
- books/reports/films
- conferences/events
- sponsors/advertisers
- researchers/experts
- regulators/government bodies
- other named entities

## Critical rule

**Discovery is automatic. Promotion is not.**

A mention creates a candidate for human review. It does not automatically become a graph node or a full research target.

Statuses:

- new
- review
- approved
- rejected
- merged
- existing

## What gets tracked

Per candidate:

- total mention count
- number of distinct content items
- number of distinct transcript/source files
- number of speakers mentioning it
- first/last seen
- sample snippet
- source/timestamp evidence
- co-mentions
- discovery batch ID

All raw mention evidence is preserved in JSONL.

## Outputs

`data/spider/mention_candidates.csv`

Human-review queue.

`data/spider/mention_evidence.jsonl`

Every source occurrence with content ID, timestamps, source file and snippet.

`data/spider/co_mentions.csv`

How often discovered candidates occur together.

`data/spider/spider_manifest.json`

Audit manifest for the spider run.

## Approval

Approved candidates can be copied/recorded into:

`data/spider/approved_entities.csv`

Those approved entities can then feed future acquisition work:

- YouTube channel discovery
- website discovery
- podcast/RSS discovery
- corporate-record searches
- product searches
- graph expansion

## End-of-batch loop

```text
Acquire source
  -> transcript/captions
  -> diarize if needed
  -> normalize transcript
  -> SPIDER
  -> count mentions/co-mentions
  -> human review with ChatGPT
  -> approve/reject/merge
  -> approved entities enter next acquisition queue
  -> repeat
```

This is the project's recursive network-expansion mechanism.
