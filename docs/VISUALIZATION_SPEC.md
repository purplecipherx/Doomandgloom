# Investigation Graph Visualization Specification

## Principle

The UI is a view over evidence and derived analysis. It never creates or upgrades evidence.

## Why 2.5D

Unrestricted 3D becomes hard to read, search, compare and export. The default should use a stable 2D force layout with limited depth cues, layered hulls, edge bundling and semantic zoom.

## Semantic zoom levels

### Level 0 — landscape
- communities/rings rendered as meta-nodes or translucent hulls;
- inter-community relationship volume;
- bridge/broker nodes;
- money/product corridors;
- optional stance/shared-target overlays;
- time slider and evidence threshold.

### Level 1 — community
- members and subcommunities;
- community hubs and brokers;
- strongest internal documented relationships;
- external bridges;
- most shared supported/adversarial targets;
- major products/sponsors/money flows;
- narrative/claim clusters.

### Level 2 — entity ego graph
- all typed documented relationships;
- separate positive/negative/neutral stance edges;
- products and commercial relationships;
- claims asserted/amplified/disputed;
- sources/citations;
- open motifs and investigative leads.

### Level 3 — evidence
- exact source ID;
- transcript unit and timestamp;
- verbatim/minimally normalized text;
- provenance/hash;
- verification status;
- supporting/contradicting sources;
- subject response when material.

## Community rendering

- primary relationship community determines main hull/layout attraction;
- secondary memberships pull a node toward additional communities;
- bridge nodes may sit between hulls rather than being forced inside one;
- nested subcommunities use inner hulls;
- overlapping memberships may use overlapping hull membership or multi-ring node halos;
- communities are labeled by derived descriptors, not hard-coded ideology unless independently established.

## Layer controls

- documented relationships;
- money/ownership;
- commercial/product;
- media appearances;
- conferences;
- stance positive;
- stance negative;
- neutral reference;
- claim propagation;
- citations/source lineage;
- motifs/leads;
- fact-check status.

## Anti-hairball controls

- bundle inter-community edges;
- aggregate weak edges at overview;
- threshold by evidence strength/count;
- hide neutral mentions by default;
- isolate selected node/community;
- top-N strongest edges;
- search;
- time window;
- minimum source count;
- show/hide unverified observations.

## Temporal behavior

The time slider renders snapshot-specific community memberships. Split/merge/birth/death events animate or annotate lineage. Historical layouts are retained so a cluster can be inspected as it existed at a past point rather than rewritten by later evidence.
