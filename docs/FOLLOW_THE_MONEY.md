# Follow-the-Money Standard

The Doomandgloom project treats **money relationships as a separate graph**, not an assumption derived from media appearances.

## Core rule

A person interviewing, praising, appearing with, or sharing a conference with another person does **not** prove money changed hands.

A money edge exists only when there is evidence of one or more of the following:

- ownership or equity
- salary / employment
- consulting payment
- legal or professional fees
- sponsorship
- affiliate / referral commission
- advertising payment
- product resale margin
- licensing fee
- speaking fee / appearance fee
- conference vendor or exhibitor payment
- subscription revenue
- product revenue
- investment
- donation or grant
- related-party transaction
- settlement / restitution / judgment
- revenue sharing
- joint venture
- payment-processor or merchant relationship when material

## Evidence hierarchy for money

Prefer:

1. court records and sworn filings
2. SEC/CFTC/FINRA/FTC/DOJ/state regulator filings
3. audited financial statements
4. tax filings / Form 990 / charity filings
5. corporate registries and ownership records
6. contracts / invoices / rate cards / affiliate terms
7. official sponsor and advertising disclosures
8. official product checkout / pricing pages
9. direct statements by payer/payee
10. credible investigative reporting

Social posts and forum allegations are leads only.

## Questions for every major actor

For every person/organization, determine where possible:

### Money in
- subscriptions
- memberships
- paid newsletters
- reports
- conferences
- software subscriptions
- consulting
- speaking fees
- sponsorships
- advertising
- affiliate/referral commissions
- precious-metals commissions
- product sales
- licensing
- investments
- donations/grants
- legal settlements
- other business income

### Money out
- employees
- contractors
- lawyers
- media production
- paid guests/speakers
- event vendors
- affiliate payouts
- advertising spend
- sponsorships
- grants/donations
- investments
- related-party companies
- product suppliers / manufacturers

## Revenue estimates

Never state an estimate as fact.

If exact revenue is unavailable, an estimate must show its formula.

Example:

> 2,000 subscribers × $30/month × 12 months = $720,000 theoretical annual gross at full retention.

That is **not** proof of actual revenue.

Store:
- assumption
- minimum
- maximum
- whether price includes discounts
- churn/retention assumption
- whether subscriber count is verified
- gross vs net

## Ownership / control

Track separately:
- legal owner
- beneficial owner
- executive control
- board control
- trademark owner
- domain owner
- merchant of record
- manufacturer
- reseller

Do not treat branding as ownership.

## Affiliate / referral testing

Whenever a network personality links to a commercial product:

1. inspect the URL for affiliate parameters;
2. look for discount/referral codes;
3. search the merchant's affiliate program;
4. inspect FTC-style disclosure language;
5. archive the landing page;
6. search historical versions;
7. determine whether compensation is disclosed;
8. record unknown compensation as **UNKNOWN**, not zero.

## Sponsorship testing

For podcasts/videos/newsletters/events:
- record sponsor reads;
- sponsor logos;
- "presented by" language;
- event exhibitor/vendor lists;
- media kits/rate cards where public;
- affiliate codes;
- product giveaways.

## Related-party transactions

Flag when:
- the same owner controls both sides;
- a director/officer appears on both entities;
- one entity contracts with another controlled by the same person;
- a nonprofit pays a related for-profit;
- a media platform promotes a product owned by its host or recurring guest.

A flag means **investigate**, not "fraud."

## Money-only graph

The published web should support a strict money-only view.

Allowed edge types:
- OWNS
- CONTROLS
- INVESTS_IN
- PAYS
- PAID_BY
- SPONSORS
- AFFILIATE_REFERRAL
- ADVERTISING
- SELLS
- RESELLS
- LICENSES
- DONATES_TO
- GRANTS_TO
- EMPLOYS
- CONSULTS_FOR
- SPEAKING_FEE
- VENDOR_OF
- RELATED_PARTY

Each money edge must carry:
- source IDs
- evidence type
- date
- amount if known
- confidence
- what the evidence proves
- what remains unknown

## Red-flag patterns worth testing

Do not assume these exist; test for them:

- the same product promoted across multiple supposedly independent shows
- reciprocal sponsorship/promotion
- undisclosed affiliate links
- recurring paid conference ecosystem
- high-ticket reports feeding into higher-ticket subscriptions/events
- "free" content acting as a funnel to costly proprietary products
- media personalities promoting companies they own/invest in
- vendors sponsoring events where their promoters speak
- financial fear narratives directly adjacent to precious-metals or preparedness offers
- health fear narratives directly adjacent to unvalidated devices/supplements
- circular money or related-party payments

## Deliverables

Generate:

- `data/money_flows.csv`
- `data/ownership.csv`
- `data/revenue_estimates.csv`
- `data/sponsorships.csv`
- `data/referrals.csv`
- `reports/money_only.graphml`
- `reports/money_summary.md`
- `reports/top_commercial_hubs.csv`

The final plain-English report should distinguish:

**"We found a media connection."**

from

**"We found a documented financial relationship."**

That distinction is non-negotiable.
