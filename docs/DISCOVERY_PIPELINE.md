# Discovery Pipeline

## Recursive graph expansion

For each validated node:

1. Collect all public content.
2. Extract named entities.
3. Extract products/services.
4. Extract sponsors/affiliates.
5. Extract conferences/events.
6. Extract cited research.
7. Extract claimed clients/government contacts.
8. Extract companies/LLCs/nonprofits.
9. Extract financial and ownership relationships.
10. Add new candidate nodes.
11. Validate candidate relationship.
12. Repeat from high-value new nodes.

## Priority scoring

Prioritize new nodes with:
- multiple strong ties to existing hubs
- documented financial relationships
- ownership/manufacturing roles
- high product sales exposure
- high audience reach
- repeated claim amplification
- research-funding roles
- securities positions
- conference organizer roles
- sponsor/affiliate concentration

## Stop rule

Do not expand forever through weak association.

A node is normally in-scope for a full 50-source profile when:
- it has at least 2 meaningful independent ties to the ecosystem; or
- it has 1 strong financial/formal/product tie; or
- it is a major commercial/media hub.

Weak one-off appearances stay in the graph but do not automatically receive a full dossier.

## Discovery outputs

- candidate_entities.csv
- validated_entities.csv
- rejected_or_weak_ties.csv
- discovery_edges.csv
- entity_priority_queue.csv

## Research status

Candidate → Validating → In Scope → 50-Source Build → Publication Review → Published
