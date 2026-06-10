# Data Realism Playbook

Cross-industry heuristics for distributions, skew, timing, correlation, and
imperfection rates. All numbers are middle-of-road practitioner defaults for
demos, not calibrated statistics. Adjust per archetype and scenario.

## Choosing Distributions

Never sample uniformly unless the real process is uniform (it rarely is).

| Phenomenon | Distribution | Typical parameters | Example |
|---|---|---|---|
| Transaction amounts | Lognormal | median 40-120, sigma 0.8-1.5; clip at plausible max | Card purchases: median 45, sigma 1.1, max 5,000 |
| Customer activity skew | Zipf/Pareto | zipf s 1.0-1.3 over ranked entities | Top 10% of customers produce 50-70% of orders |
| Inter-arrival times | Poisson | rate from daily volume / business hours | Payments: poisson arrivals, mean gap 90s during 9-17 local |
| Quantities per line | Weighted choice | P(1) 50-70%, decaying tail, occasional bulk | Order lines: 1,1,2,1,3,1,12 |
| Durations / dwell | Lognormal | median in natural units, sigma 0.5-1.0 | Support ticket resolution: median 26h, sigma 0.9 |
| Rates / proportions | Beta | alpha/beta tuned to mean; avoid 0/1 spikes | Fill rate: Beta(18,2) for ~90% mean |
| Measurement noise | Normal | mean = true value, sd 0.5-3% of value | Sensor reading: value * N(1, 0.01) |

Notes:

- Round amounts to currency precision after sampling; let some values land on round numbers naturally (5-10% rounded to nearest 10/100 mimics manual entry).
- For mixed populations (retail + corporate), sample segment first, then segment-specific parameters. One global lognormal looks wrong to practitioners.
- Counts per parent (orders per customer, lines per order): overdispersed; approximate with poisson plus a per-parent lognormal rate multiplier and a fat-tail override for the top decile.

## Activity Skew and the Long Tail

Concentration is the single strongest realism signal. Anchor to 80/20-style shares:

- Top decile of customers: 45-70% of revenue/volume (B2B higher, consumer lower).
- Top 1% of entities: 10-25% of activity. A few "whales" should dominate any top-N report.
- Bottom half of entities: under 10% of activity combined.

Parameterizing:

- Zipf exponent s = 1.0 gives roughly 80/20 over a few thousand entities; s = 1.2-1.4 sharpens concentration (marketplaces, content); s = 0.8 flattens it (regulated/contracted B2B).
- Simpler alternative: assign each entity a lognormal "activity weight" (sigma 1.2-1.6) and draw events proportionally.

Dormancy and repeat behavior:

- 15-35% of customer-like entities should be dormant (no events in the last 6-12 months) but still present with valid history.
- 20-40% one-time actors (single order, single visit, single claim) -- never give every entity a multi-event history.
- Repeat actors follow the skew: most have 2-5 events, the top decile has 10-100x the median.
- Products/SKUs: 5-15% never transact at all (catalog deadwood); include them.

## Temporal Realism

Weekly shape by business type:

- B2B/back-office: weekday-heavy, weekend volume 2-10% of weekday; Monday and Friday slightly below midweek.
- Consumer retail/ecommerce: weekend at 110-150% of weekday; evening peaks.
- Healthcare ambulatory: weekday clinic hours; ED/inpatient runs 24/7 with a mild evening peak.
- Logistics/manufacturing: follows shift calendar, not the office week.

Calendar effects:

- Public holidays: near-zero human volume; batch/machine volume unchanged. Pick 8-12 holiday dates per year for the operating region.
- Paydays (1st/15th or biweekly Fridays) lift consumer payment and spending volume 1.2-1.5x.

- Month-end: 1.5-3x spike in postings, invoices, adjustments, and manual journal entries in the last 2-3 business days.
- Quarter/fiscal close: stronger spike plus a cluster of corrections in the first week of the next period.
- Seasonality archetypes: retail Q4 ramp (Nov-Dec 1.5-2.5x), B2B Q-end sales push, healthcare winter respiratory bump, logistics pre-holiday freight surge, SaaS renewals clustered on contract anniversaries.

Intra-day:

- Human-initiated events cluster in business hours: roughly N(13:30, 2.5h) local with a lunch dip; almost nothing 0-6 AM local.
- Machine events (batch jobs, webhooks, sensors) run on schedules or near-uniformly; batch loads land at fixed times (02:00 nightly) with occasional late runs.
- Never emit perfectly spaced timestamps; jitter every schedule by seconds-to-minutes.

History depth:

- Apply a growth trend across the horizon: 5-30% YoY for a steady business; older months should have visibly less volume.
- Cohort aging: older records carry more nulls, legacy code values, retired formats, and missing newer columns. A field added "two years ago" must be null before that date.
- Backdating and late posting: 2-10% of events have effective/business dates earlier than created_at; lag is lognormal (median 1-2 days, tail to 30-90). Period-end records show the longest lags.

## Correlation and Coherence

Independently sampled columns are the fastest way to fail review. Fields that must move together:

- Entity size <-> volume and amounts: large customers have more orders, higher credit limits, more contacts, more support tickets.
- Price <-> product tier/category: enterprise SKUs cost more than starter SKUs; unit price varies within a band per product, not globally.
- Geography <-> region codes, currency, tax rates, phone formats, time zones, warehouse assignment.
- Status <-> timestamp presence: delivered implies delivered_at; cancelled implies no later fulfillment events; closed_at >= opened_at always.
- Tenure <-> history depth: a customer created last month cannot have a 3-year order history.
- Risk/quality scores <-> outcomes: high-risk flags should actually correlate with denials, chargebacks, or failures.

How to fake correlation cheaply (no covariance math needed):

- fk_copy: denormalize the driver attribute onto the child row (copy customer_segment onto the order), then condition on it.
- expression: derive one field from another plus noise, e.g. amount = qty * unit_price * (1 +/- 2%), or score = base(segment) + N(0, 5).
- segment-conditional parameters: pick the segment first, then use per-segment distribution parameters (enterprise order: lognormal median 8,000; SMB: median 600).

Generate parents before children, and events in state-machine order, so coherence falls out of sequencing rather than patching.

Generation order that keeps coherence cheap:

1. Reference/dimension data (geography, calendars, code sets, products).
2. Core entities with segment, size tier, and activity weight assigned up front.
3. Relationships and effective-dated assignments.
4. Events drawn per entity using segment-conditional parameters and the entity's activity weight.
5. Derived balances/roll-forwards computed from the events, never sampled independently.
6. Imperfections injected last, against named scenarios.

## Categorical Realism

- Status and code frequencies are never uniform. Default shape: 80-15-5 (dominant value, common alternate, everything else).
- Terminal states dominate aged data: ~85-95% of old orders are completed/closed/settled; in-flight states concentrate in the most recent days.
- Rare codes must appear: every defined enum value should occur at least once at medium+ scale, even at 0.1%. An unused code list is its own red flag, but so is a missing rare value.
- A small rate of retired/invalid codes (0.5-2%) on legacy rows is realistic and feeds DQ rules.
- Free-text fields (notes, descriptions, denial reasons): generate from 10-30 templates with slot variation, typos, and casing inconsistency; let the same template repeat. Real operators copy-paste. Leave 30-60% of optional note fields empty.
- Names of things (campaigns, projects, files) follow conventions inconsistently: "Q3_Promo_FINAL_v2" lives next to "q3 promo".

## Identifier Safety

Never generate identifier values that could collide with real people or accounts.
Format-valid but provably fictional is the goal.

| Identifier | Safe fictional strategy |
|---|---|
| Card numbers | Test BINs only: 4111 1111..., 5555 5555 5555 4444, 4242 4242...; Luhn-valid is fine within test ranges |
| Phone numbers | 555-01xx range (e.g. +1-212-555-0142); fictional ranges for non-US locales |
| Emails | example.com, example.org, or .test/.invalid TLDs only |
| National IDs / SSNs | Never emit 9-digit SSN-shaped values; use surrogate formats like TAX-XXXXXX or NID-XXXXXXX |
| Bank routing numbers | Valid checksum but reserved/unassigned district prefixes; or surrogate RTN-XXXXXXXX |
| Account/IBAN | IBAN with fictional country code ZZ, or clearly internal formats (ACCT-XXXXXXXX) |
| ISIN/CUSIP/SEDOL | Fine to generate with valid check digits -- security identifiers are not personal; avoid real issuers' codes |
| NPI / provider IDs | Valid check-digit format acceptable; pair only with fictional provider names |
| Names | Draw only from fictional pools; never combine a real-sounding full name with other realistic identifiers |
| Addresses | Fictional street names on real-shaped formats; real cities/regions are fine, real street addresses are not |

When in doubt, prefix with an internal-looking scheme (CUST-, MRN-, POL-) -- enterprises surrogate everything anyway, so it reads as more realistic, not less.

## Imperfection Rates That Ring True

Pair with the Controlled Imperfections list in `enterprise-patterns.md`; this table supplies default rates.

| Imperfection | Typical rate range | Notes |
|---|---|---|
| missing_xref | 1-5% | Unmapped source IDs; higher for newest source system; feeds unmapped-entity queues |
| duplicate_entity | 0.5-2% | Near-duplicates: name variants, same email different ID |
| late_arrival | 2-10% | Lag lognormal, median 1-3 days, tail 30-90; spikes at period end |
| orphan_fk | 0.1-1% | Staging/raw layers only; canonical layer should quarantine, not store |
| conflicting_source_values | 1-5% | Same entity, different address/status per system; survivorship picks one |
| format_drift | per-batch | 1-3 legacy batches with old date formats, renamed columns, or padding |
| manual_override | 0.5-3% | Clustered on month-end and on the largest accounts; always with override reason and user |
| restatement_reversal | 0.1-0.5% | Rare but clustered: one bad batch, one bad period, not evenly spread |
| stale_mapping | 0.5-2% | Retired/invalid codes left mapped on legacy rows; concentrated in oldest cohort |
| typo | 1-3% | Hand-keyed text fields only (names, references); engine keeps digit-bearing values safe |
| out_of_order_events | 0.5-2% of event groups | CDC/webhook disorder; sequence swaps within a group |
| duplicate_webhook | 0.5-2% | Retried deliveries in integration/event tables |
| null_field | 1-5% | Logged missingness on top of design-level null_rate |

Rules of thumb:

- Null rates in optional fields run 5-40% by field criticality; near-zero only for keys and amounts.
- Imperfections cluster (by source, batch, period, or operator); uniform random sprinkling of errors looks synthetic.
- Every imperfection should be detectable by a DQ rule or reconciliation in the same ecosystem, with a handful intentionally escaping detection.
- Reconciliation break rates: 0.5-3% of items, 80%+ explained, the rest open in workflow queues.

## Volume Anchors by Scale

Coherent ratios matter more than absolute counts. Defaults for a 2-3 year horizon:

| Tier | Core entities | Events/transactions | Examples |
|---|---|---|---|
| Small (demo) | 100-1,000 customers; 50-500 products; 20-100 employees | 5k-50k event rows | Quick demos, unit-test seeds; SQLite trivially |
| Medium (default) | 5k-50k customers; 1k-10k products; 200-2k employees | 100k-2M event rows | Realistic dashboards, DQ/recon stories; SQLite comfortable |
| Large | 100k-1M customers; 10k-100k products | 5M-50M event rows | Performance/scale demos; consider sampling or warehouse target |

Ratio sanity checks:

- Orders per active customer per year: 2-12 (consumer), 10-200 (B2B distribution).
- Lines per order: 1-5 typical, tail to 50+ (distribution/food service skews high).
- Support tickets: 0.1-0.5 per customer per year, concentrated in the largest accounts.
- Crosswalk coverage: 90-99% of canonical entities mapped per source, never 100%.
- Users/operators: events per operator per day should be humanly possible (tens to low hundreds, not thousands).
- Reference/dimension tables stay small at every tier: 10-200 codes per code set, 5-50 locations, 3-15 source systems.
- Keep ratios stable when scaling tiers up or down; scale event counts, not the shape of the data.

## Red Flags That Break the Illusion

If any of these appear, the data fails practitioner scrutiny:

- Uniform anything: flat amounts, flat daily volume, equal status shares, evenly spread categories.
- No weekend/business-hours signal in human-generated events.
- All entities active; no churn, dormancy, closures, or terminations.
- Amounts like 5000.00 everywhere: no cents, no skew, no outliers, suspicious round numbers.
- Perfectly evenly spaced timestamps. (IDs *should* correlate with created_at order — real sequences do — but the gaps between timestamps must be irregular.)
- 100% referential integrity, 100% crosswalk coverage, zero DQ failures, zero recon breaks.
- Zero nulls in optional fields; every record fully populated regardless of age.
- Every customer has the same number of orders; no whales, no one-timers.
- New fields populated on records that predate the field's introduction.
- Statuses inconsistent with timestamps (delivered with no delivered_at, cancelled then shipped).
- No growth trend: month 1 volume identical to month 36.
- Real-looking SSNs, card numbers outside test BINs, or real-domain email addresses.

See also: structural red flags in `validation-checklists.md`.
