# Dynamic Multiplex Network Model

## Core rule

Communities/rings are derived views, never source facts. The durable evidence layer records events and typed edges with provenance. Community assignments can change as evidence accumulates.

## Independent graph layers

1. **Documented relationship graph** — ownership, employment, payment, sponsorship, affiliate, formal professional, product, recurring/single media, conferences.
2. **Stance graph** — praises, endorses, supports, defends, agrees with, criticizes, disputes, accuses, warns against, distances from, neutral reference, quotation.
3. **Claim/narrative graph** — who asserts/amplifies/disputes which atomic claim; source lineage; citations; corrections.
4. **Commerce/money graph** — products, sellers, owners, manufacturers, affiliates, sponsors, documented payments/funding/investments.
5. **Source/citation graph** — reports, studies, websites, articles and evidentiary lineage.
6. **Event graph** — conferences, interviews, releases, campaigns, dated appearances.

No layer may silently substitute for another. A negative stance edge does not create a relationship edge. A relationship edge does not imply ideological support.

## Community inference

Community detection runs primarily on the documented relationship graph. Stance/claim/commerce layers are analyzed separately and may be overlaid.

Each snapshot produces:
- hard community ID for layout only;
- membership strengths to multiple communities;
- bridge/participation score;
- brokerage/betweenness score;
- outlier score;
- centrality metrics by layer;
- evidence coverage and uncertainty.

Multiple memberships are normal. A bridge node can connect several communities without being central inside any one of them.

## Temporal snapshots

Every community computation is dated and versioned. Membership history is never overwritten.

Community lineage between snapshots is classified as:
- CONTINUE
- SPLIT
- MERGE
- BIRTH
- DEATH
- REFORMED

Lineage is based on weighted membership overlap, not community-number equality.

## Investigative motif engine

Motifs are lead generators, not findings. Examples:
- documented collaborators share an adversarial target;
- documented collaborators praise/support the same target;
- same unusual claim + same source + close timing;
- reciprocal media/promotion;
- shared sponsor/affiliate/vendor/manufacturer;
- shared attorney/PR/marketing infrastructure;
- criticism of a commercial competitor where a financial interest exists;
- fear/urgency claim -> CTA -> product -> beneficiary;
- prediction -> product pitch;
- citation chain/cycle;
- many apparent confirmations resolve to one originating source;
- coordinated-looking timing that disappears against a comparison corpus;
- stance reversal over time;
- cross-cluster bridge carrying a claim/product into another community.

Each motif records its component evidence IDs and a `signal_strength`; it must never be labeled proof of coordination unless independent documentary evidence establishes coordination.

## Comparison/baseline corpus

Shared targets and shared narratives are only distinctive when compared with an appropriate background corpus. Store observed rate, baseline rate, lift, time window and population. High overlap without baseline lift is not treated as a distinctive network signal.

## Visualization

Default UI should be 2.5D rather than unrestricted 3D:
- 2D force-directed node positions;
- translucent community hulls/rings;
- nested/overlapping hulls where memberships overlap;
- visual depth/layer controls for relationship, stance, claims, money, citations;
- time slider with community lineage animation;
- evidence-strength threshold slider;
- click node -> ego network and dossier;
- click edge -> exact evidence/timestamps;
- click community -> members, hubs, bridges, shared targets, shared sponsors, narratives;
- click target -> who supports/criticizes it and through which claims;
- collapse weak edges by default; bundle inter-community edges;
- search and isolate mode for dense 4,500-node graphs.

The full graph remains queryable even when the visual view hides low-value edges.
