# Investigative Semantic Ontology

## Core rule

The semantic system records **what a speaker did linguistically** and **what relationship/event was actually asserted**, while the fact-check layer separately records whether factual propositions are verified, contradicted, disputed, or unresolved.

A mention is never a relationship.
A criticism is never an alliance.
A shared target is never coordination.
A quote is never automatically speaker adoption.
An allegation is never automatically fact.
A recommendation is never automatically financial promotion.
A media appearance is never automatically a commercial relationship.

## Every semantic event preserves

- raw predicate phrase;
- normalized predicate code;
- predicate family;
- source speaker / claimant;
- target entity and/or target claim;
- object/product/source/event when relevant;
- polarity;
- speaker adoption;
- attribution mode;
- certainty/modality;
- explicitness;
- temporal scope;
- topic;
- severity;
- commerciality;
- evidentiary status;
- source unit/timestamp;
- confidence;
- notes.

## Critical dimensions

### Speaker adoption
- ADOPTS
- REJECTS
- NEUTRAL_REPORT
- QUOTING
- HYPOTHETICAL
- QUESTIONING
- UNCERTAIN
- SARCASTIC_OR_IRONIC
- MIXED

### Epistemic certainty
- CERTAIN
- HIGH_CONFIDENCE
- ASSERTED
- PROBABLE
- POSSIBLE
- SPECULATIVE
- CONDITIONAL
- UNKNOWN

### Attribution mode
- OWN_CLAIM
- DIRECT_QUOTE
- PARAPHRASE
- HEARSAY
- ATTRIBUTED_TO_NAMED_SOURCE
- ATTRIBUTED_TO_UNNAMED_SOURCE
- SUMMARY_OF_GROUP_VIEW
- RHETORICAL_QUESTION
- HYPOTHETICAL

### Polarity
- POSITIVE
- NEGATIVE
- NEUTRAL
- MIXED
- NOT_APPLICABLE

### Factual resolution is separate
- PENDING
- VERIFIED
- SUPPORTED_INFERENCE
- DISPUTED
- UNVERIFIED
- CONTRADICTED
- OPINION_OR_NOT_CHECKABLE
- NOT_APPLICABLE

## Investigative principle

The ontology is intentionally broader than the graph. Many semantic events remain discourse-only observations. Only events that satisfy the documented relationship standard may contribute to the primary relationship graph.

The raw phrase is always retained so a future ontology revision can remap an event without losing the original language.
