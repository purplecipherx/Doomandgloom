# Market Influence / Trading Conflict Audit

## Research question

Did any person or organization in the network make public statements about a publicly traded security while holding, controlling, benefiting from, or being paid in relation to a position that could profit from the resulting price move?

This includes both directions:
- **short-and-distort risk**: bearish public claims while short / long puts / otherwise benefiting from a decline;
- **pump-and-dump risk**: bullish promotion while long / compensated / planning to sell into audience demand.

Short selling itself is lawful and often useful. The SEC explicitly recognizes that short sellers can improve price discovery. The problem is deceptive or manipulative conduct, especially false or misleading statements combined with a position that benefits from the induced move.

## What counts as evidence

For each candidate event preserve:

1. exact statement and timestamp;
2. security/ticker;
3. whether the statement was bullish or bearish;
4. evidence cited in the statement;
5. whether a financial position was disclosed;
6. evidence of the actual position;
7. opening/closing dates if available;
8. price and volume reaction;
9. benchmark-adjusted return;
10. options/short-interest data where available;
11. any affiliate/sponsor/issuer compensation;
12. corrections or retractions;
13. regulator/court findings if any.

## Position evidence hierarchy

Strongest:
- SEC filings;
- Form SHO / institutional short reporting where available;
- fund filings;
- court discovery/exhibits;
- brokerage/account records in litigation;
- sworn testimony;
- official disclosure by the person/fund;
- reputable investigative reporting based on records.

Weak:
- rumors, anonymous posts, inferred positions from rhetoric.

Never say someone shorted a stock solely because they publicly criticized it.

## Event-study discipline

A price decline after a video does not prove causation.

Record:
- market-wide move;
- sector move;
- company news released at the same time;
- earnings;
- analyst downgrades;
- macro events;
- unusual volume;
- audience size / distribution;
- timing precision.

Use benchmark-adjusted returns where practical.

## Disclosure / conflict testing

Check:
- website disclosures;
- video/podcast disclosures;
- SEC/FINRA registrations;
- Form ADV if applicable;
- paid promotion disclosures;
- affiliate disclosures;
- compensation from issuer or competitor;
- fund/adviser ownership;
- options or short-position disclosures.

The SEC has repeatedly treated undisclosed financial conflicts and deceptive securities promotion as serious. It has also brought enforcement actions alleging both social-media stock manipulation and short-and-distort conduct.

## High-priority patterns

Investigate when:
- a person repeatedly attacks named public companies and later boasts that they predicted the decline;
- the person runs a trading/forecasting product while discussing those securities;
- a newsletter recommends or attacks a security without clear position disclosure;
- multiple connected influencers coordinate timing or repeat near-identical claims;
- connected entities have options/short exposure;
- a negative report is followed by monetized access to trading signals;
- an issuer, competitor, hedge fund, or sponsor appears to fund the coverage.

## Internal classifications

- VERIFIED POSITION + VERIFIED STATEMENT
- VERIFIED POSITION + UNVERIFIED IMPACT
- DISCLOSED CONFLICT
- UNDISCLOSED CONFLICT SUSPECTED
- NO POSITION EVIDENCE
- REGULATORY / COURT FINDING
- INSUFFICIENT DATA

Do not label conduct manipulation unless supported by a regulator/court finding or evidence strong enough to support that conclusion explicitly.

## Deliverables

- data/market_influence_events.csv
- data/securities_positions.csv
- data/issuer_claims.csv
- report: public claim → market move → position/conflict → evidence → conclusion
