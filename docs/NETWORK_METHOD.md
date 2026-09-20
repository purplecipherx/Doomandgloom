# Relationship Web / Hub Analysis

## Purpose

Build an evidence-backed web of people, organizations, products, media platforms, conferences, sponsors, and commercial relationships.

The graph should reveal **hubs, brokers, amplifiers, and commercial centers** without treating mere association as proof of coordination.

## Node types

- person
- organization/company
- media platform
- conference/event
- product/service
- sponsor/vendor

## Relationship classes

### Strong / commercial
- OWNS / CONTROLS
- EMPLOYS / OFFICER / DIRECTOR
- FINANCIAL
- AFFILIATE_REFERRAL
- SPONSORSHIP
- SELLS
- MANUFACTURES
- LICENSES
- JOINT_PRODUCT
- FORMAL_PROFESSIONAL

### Medium
- COMMERCIAL_PROMOTION
- RECURRING_MEDIA
- RECURRING_CONFERENCE
- COAUTHORS / COPRODUCES

### Weak
- SINGLE_MEDIA
- SINGLE_CONFERENCE
- IDEOLOGICAL_TOPICAL

## Hub metrics

Calculate separately:

1. **All-edge degree** — who appears everywhere.
2. **Strong-tie degree** — who remains central after interviews/conferences are removed.
3. **Commercial degree** — who owns/sells/promotes the most monetized products.
4. **Betweenness** — who bridges otherwise separate clusters.
5. **PageRank/eigenvector-style score** — who connects to other central actors.
6. **Product influence** — how many products someone owns, sells, promotes, or receives documented compensation from.
7. **Money-only graph** — only documented financial relationships.

The phrase "ringleader" should be treated as an informal research question. Published conclusions should use the precise evidence-based label actually established: **network hub, media amplifier, commercial hub, owner, broker, or cross-cluster bridge**.

## Edge evidence rule

Every edge needs source IDs.

Financial/ownership edges require strong documentary support. A guest interview never proves a financial relationship.

## Product integration

Products are not leaves hidden in an appendix. They sit inside the graph so we can ask:

- Who owns the product?
- Who advertises it?
- Who hosts the advertisements?
- Is the promoter an affiliate?
- Does a conference vendor belong to the same network?
- Do multiple personalities route audiences to the same merchant?
- Does the seller then sponsor or promote those personalities?

See `docs/PRODUCT_AUDIT_STANDARD.md`.
