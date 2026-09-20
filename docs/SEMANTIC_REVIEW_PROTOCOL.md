# Semantic Review Protocol

## Objective

Read every current transcript unit in context and produce an evidence-preserving semantic record suitable for investigative analysis. The semantic pass determines **what was said and how it was said**. It does not decide whether external-world claims are true.

## Pass 0 — reconstruct the utterance

Before extracting anything:
- read the current unit plus neighboring units;
- use speaker attribution when available;
- stitch obvious caption fragmentation mentally without rewriting the source;
- preserve the original raw text;
- identify obvious transcription/name errors as correction candidates, never silent edits.

## Pass 1 — identify every entity/reference

Extract people, aliases, companies, nonprofits, agencies, governments, political organizations, media outlets, shows, podcasts, channels, websites, newsletters, publications, books, reports, studies, conferences, products, services, sponsors, financial instruments, places, events, laws/policies, technologies and named groups.

For each mention preserve:
- raw surface;
- normalized surface;
- entity type;
- canonical entity ID if justified;
- unresolved/ambiguous state otherwise;
- transcript-fragment flag;
- correction candidate;
- pronoun/coreference state;
- confidence.

Never guess a pronoun referent just to complete a graph.

## Pass 2 — identify semantic acts

Use the normalized ontology but preserve the raw predicate phrase.

Examples:
- "my number-one go-to source" -> TRUSTS_AS_SOURCE;
- "wonderful book" -> PRAISES;
- "I recommend..." -> RECOMMENDS;
- "they are grifting" -> ACCUSES_GRIFTING;
- "X would argue..." -> ATTRIBUTES_TO_SOURCE;
- "I think..." -> lower certainty;
- "could have..." -> HYPOTHETICAL / CONDITIONAL;
- "there is no doubt..." -> CERTAIN;
- "buy/subscribe/use my code" -> commercial/CTA predicates;
- "tyranny vs freedom" -> rhetorical framing, not automatically a factual claim.

## Pass 3 — preserve attribution and adoption

For every proposition decide:
- who originally made it;
- whether the current speaker adopts it;
- whether it is quoted/paraphrased/hearsay;
- whether it is a question or hypothetical;
- whether it is negated;
- degree of certainty.

The following are materially different:
- "X lied."
- "Y says X lied."
- "People say X lied."
- "I doubt X lied."
- "If X lied..."
- "X did not lie."
- "X was accused of lying, but I reject that accusation."

## Pass 4 — atomize factual claims

Split compound statements into independently checkable propositions. Preserve claimant and target separately.

Each checkable proposition gets a claim record and later a stable claim ID. Do not label it true/false in the semantic stage.

## Pass 5 — relationship discipline

A semantic event may assert or imply a relationship, but relationship graph admission is separate.

Do not create a documented relationship from:
- mention;
- praise;
- criticism;
- shared target;
- quote;
- one-way recommendation;
- ideological agreement;
- appearance in the same transcript unless an actual appearance/event edge is supported;
- inferred coordination.

Documented relationship candidates include explicit ownership, payment, employment, contract, sponsorship, affiliate, investment, recurring media, formal organizational role, joint product, co-production or other evidence-defined relationship types.

## Pass 6 — commerce and persuasion

Extract separately:
- products/services;
- seller/owner/manufacturer/distributor where stated;
- sponsor/affiliate/referral;
- price/discount code;
- CTA;
- recommendation;
- claimed benefit/risk;
- fear, urgency, scarcity, exclusivity, insider, authority, moral, patriotic, religious, anger, disgust, hope, greed and social-proof appeals;
- catastrophe/enemy/us-vs-them/scapegoat/secrecy framing.

Co-occurrence is not causation. A fear statement near a product pitch is a lead until the chain is reviewed.

## Pass 7 — second-pass adversarial verification

A separate pass reviews every semantic event against the original text/context.

Check explicitly for:
- WRONG_SPEAKER;
- WRONG_TARGET;
- WRONG_PREDICATE;
- OVERSTATED / UNDERSTATED;
- QUOTE_TO_BELIEF;
- HEARSAY_TO_BELIEF;
- ALLEGATION_TO_FACT;
- NEGATION_INVERSION;
- QUESTION_TO_ASSERTION;
- HYPOTHETICAL_TO_ASSERTION;
- PREDICTION_TO_OBSERVED_EVENT;
- MENTION_TO_RELATIONSHIP;
- CRITICISM_TO_ASSOCIATION;
- RECOMMENDATION_TO_AFFILIATE;
- SHARED_TARGET_TO_COORDINATION;
- COREFERENCE_GUESSED;
- ENTITY_RESOLUTION_ERROR;
- TRANSCRIPT_FRAGMENT_ERROR;
- MISSING_CONTEXT;
- DUPLICATE_EVENT.

Only VERIFIED_TEXT events enter default investigative summaries.

## Pass 8 — external fact checking

Fact checking happens after semantic verification.

Allowed outcomes:
- VERIFIED;
- SUPPORTED_INFERENCE;
- DISPUTED;
- UNVERIFIED;
- CONTRADICTED;
- OPINION_OR_NOT_CHECKABLE;
- NOT_APPLICABLE.

A statement can be semantically VERIFIED_TEXT while its factual claim is CONTRADICTED.

## Legal/reputational labels

"Defamation", "slander", "libel", "criminal", "fraud" and similar legal conclusions are not semantic truth labels. The system records the exact accusation made and fact-check/legal evidence separately. Use an adjudicated legal characterization only where an authoritative legal record establishes it.

## Output principle

The database should always be able to answer:
1. What exactly was said?
2. Who said it?
3. About whom/what?
4. Was it adopted, quoted, questioned, hypothetical or denied?
5. What normalized semantic action does it represent?
6. Is it a real documented relationship or only discourse?
7. Does it require external fact checking?
8. What evidence supports the extraction?
9. Has a second pass verified the extraction?
10. What later evidence supports, disputes or contradicts the factual proposition?
