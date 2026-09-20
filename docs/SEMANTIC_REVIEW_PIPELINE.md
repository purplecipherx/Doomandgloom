# Semantic Review and Fact-Check Pipeline

## Evidence first

`data/analysis/transcript_units.csv` is the lossless evidence layer. Review results attach to `unit_id`; they do not overwrite transcript evidence.

Every current unit must be reviewed, even when the result is question, opinion, procedural speech, advertisement, or no checkable factual assertion.

## Required semantic output per unit

- speech act(s)
- all person/organization/product/place/event/source mentions
- zero or more atomic claims
- claims about another person or organization, preserving claimant and target separately
- relationships asserted or implied by the speaker
- products/services/sponsors/affiliate or CTA references
- predictions and measurable conditions/dates where stated
- money, ownership, compensation, investment, funding or conflict-of-interest signals
- citations/reports/studies/websites/sources mentioned
- notes and uncertainty

Atomic claims must be split into independently checkable propositions. A transcript allegation remains an allegation until corroborated.

## Fact checking

Every checkable atomic claim gets a stable `CL_...` ID and enters `data/analysis/fact_check_queue.csv`.

Allowed completed statuses:

- VERIFIED
- SUPPORTED_INFERENCE
- DISPUTED
- UNVERIFIED
- CONTRADICTED
- OPINION_OR_NOT_CHECKABLE
- NOT_APPLICABLE

Fact-check records should preserve primary sources, independent sources, contradicting evidence, subject rebuttal when material, exact dates/populations/context, limitations, reviewer and reviewed timestamp.

## Write-back

Apply semantic review JSONL:

    .\.venv-youtube\Scripts\python.exe .\scripts\apply_semantic_review.py <review.jsonl> --reviewer <name>

This rebuilds:

- `atomic_claims.csv`
- `mentions.csv`
- `relationship_claims.csv`
- `product_mentions.csv`
- `predictions.csv`
- `money_conflict_signals.csv`
- `cited_sources.csv`
- `fact_check_queue.csv`

Apply fact-check result JSONL:

    .\.venv-youtube\Scripts\python.exe .\scripts\apply_fact_checks.py <fact_checks.jsonl> --reviewer <name>

A transcript unit reaches fact-check COMPLETE only when every checkable atomic claim attached to that unit has a completed review status.
