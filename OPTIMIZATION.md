# Data loading and provenance changes

This patch separates dashboard reads from slow collection and corrects misleading chart labels. It has not been deployed to production.

## Changes

- Independent dashboard requests start together; market rows appear before slower panels finish. Concurrent refreshes share requests, use a 12-second timeout, and pause polling in hidden tabs. Slow-changing histories have bounded browser caching. Existing market data survives partial failures with an explicit warning.
- Cold dashboard GETs return `503` and `Retry-After: 30` rather than starting an entire collection cycle. Empty history reads no longer write fabricated current snapshots. The normal background scheduler must remain enabled.
- Stablecoin and on-chain histories refresh in a bounded background pool, with one task per source. On upstream failure they retain the previous successful data, mark it stale, and wait 60 seconds before retrying. A cold history request returns 503 until its first background load completes. This cache is process-local and is lost on restart.
- Compress HTML and JSON responses with gzip. Cap history queries at 5,000 rows (decision history at 2,000). The frontend requests 2,500 position observations, sufficient for approximately 34.7 days at the configured 20-minute interval; gaps or longer intervals are still disclosed rather than filled.
- Daily Hyperliquid candles are sorted, deduplicated, checked for finite values, gaps and a recent closed candle. Only completed UTC daily candles enter divergence signals. Successful daily series are reused within the UTC day. Missing/failed daily series are shown as unavailable, not as confirmed absence of divergence. This changes signal inputs from the prior intraday candle behavior and should be reviewed before deployment.
- OI retains its Hyperliquid value in a separate field and identifies whether the displayed number is CoinGecko aggregate or Hyperliquid fallback. Valid zero ratios remain zero. CoinGecko market-cap matching remains based on symbol and the top 250 market list; the UI now acknowledges that limitation.
- On-chain charts use true 7/30-day boundaries, actual sample counts, and distinguish balance/notional changes from executed trades. Stablecoin charts show market-cap change rather than claiming actual cash flows. The table distinguishes comprehensive decisions from market-scan scores.
- `/data_status` reports cycle start, most recent successful cycle completion, duration and failure/running flags. These are collector timings, not proof that every upstream source is current. A cycle can complete with partial upstream failures.

## Verification

Run from this repository with Python 3.10+ and Node.js:

```sh
python -m pip install -r requirements.txt pytest
python -m pytest -q
node --test tests/test_frontend.cjs
```

9 Python tests and 12 JavaScript tests passed locally. Tests cover nonblocking duplicate refreshes, stale-on-error/backoff, cold GET isolation, limits, gzip, OI provenance, zero ratios, candle order/completeness/cache boundaries, malformed history, progressive rendering, failure retention, timeouts and calendar windows. Frontend fixtures are public dashboard responses captured on 2026-09-12, not current market data. Browser replay rendered 234 rows and the corrected date windows.

## Remaining work before claiming all data is correct

1. Compare the deployed checkout/image, Caddy mapping and volume mounts with this repository. Back up the current image and persistent databases before deployment; retain the old image for rollback. Do not reset the VPS or delete volumes.
2. Measure end-to-end loading and several collection cycles on the VPS. Locally, cold GET tests never invoke the collector, but production latency improvement has not yet been measured.
3. Separate fast price/funding refreshes (e.g. 30–60 seconds) from account selection (20 minutes) and daily metrics. At present the central cycle is still shared, and 30-second browser polling does not make a 20-minute market snapshot real-time.
4. Persist last-known-good source snapshots and source observation/fetch timestamps. Atomically publish a complete cycle snapshot so clients cannot mix old/new fields during collection. Add source-specific failure and staleness indicators across all panels, not only the two daily histories.
5. Replace ambiguous symbol-based market-cap matching with verified asset IDs and explicit aliases (including scaled `k` symbols). Validate exchange aggregation units, venue coverage and duplication before trusting every OI value.
6. Verify wallet-band definitions and the mismatch between the dashboard's whale+humpback grouping and the decision agent's configured humpback+megaWhale grouping. Audit LTH/whale changes by source date; repeated sampling of an unchanged daily value should not imply a fresh neutral daily signal.
7. Backtest/validation endpoints still perform potentially expensive upstream reads. Move these to cached background jobs with bounded concurrency. Review SQLite connection/transaction sharing before increasing API worker count. Do not increase workers now: collector and caches are process-local.
8. Review strategy claims and confidence calibration separately. Arithmetic consistency does not demonstrate predictive accuracy or establish that address cohorts represent independent people.

Dedicated VPS IPs are still rate limited. Hyperliquid documents IP-weighted REST limits and additional candle/response weights; reducing duplicate requests is preferable to indiscriminately increasing concurrency. See the [official limits](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits) and [Info API](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint).

## Phase 2: independent market quotes

Market quotes now refresh every 60 seconds on a separate scheduler job and HTTP
client. Slow analysis keeps its existing interval. Dashboard reads never fetch
upstream. Valid quotes are atomically persisted beside the decision database,
restored after restart, and retained on fetch/validation errors. Fetch time is
shown separately from analysis time; quotes older than 180 seconds or with a
failed refresh are marked delayed. Slow score funding cannot overwrite quote
funding. CoinGecko market-cap identity matching remains a separate follow-up;
this change does not claim all asset identities are verified.

Validation: 11 Python pipeline tests and 13 JavaScript frontend tests pass.

## Phase 3: market identity and listing status

Exclude Hyperliquid `isDelisted` markets before building live quotes and scores;
validate universe/context lengths before zipping to prevent silent truncation.
The frontend does not reintroduce symbols from old scores/decisions when a live
quote universe is available. Persisted quote caches require the active-only
schema marker, so older snapshots cannot restore delisted markets.

CoinGecko uses the six existing configured asset IDs where available; other
symbols are explicitly marked as candidates, and duplicate symbols are omitted.
Missing volume stays null rather than zero. HTTP failures retain the original
cache timestamp. The page shows separate market-cap and aggregate-OI fetch ages.
No extra CoinGecko calls or expanded page budget are introduced.

Validation: 14 Python and 15 JavaScript tests. Public upstream inspection found
56 delisted entries in a 234-entry universe (178 active). This does not verify
all symbol candidates or aggregate derivative asset identities.

References: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals
and https://docs.coingecko.com/reference/coins-markets

## Phase 4: derivative coverage and cross-source checks

Normalize USD OI from perpetual contracts only; discard invalid/negative OI,
expired contracts, missing/future trade times, and contracts without a trade in
24 hours. Deduplicate exchange/ticker by latest trade. This is a coverage policy,
not proof that OI itself was updated at the last-trade timestamp.

Before using CoinGecko valuation/OI for a Hyperliquid symbol, require a positive
finite reference price within 20% of the HL quote. This is a conservative mismatch
guard, not asset identity certification. No symbol candidates are promoted to
verified IDs by this heuristic. Macro OI includes non-crypto underlyings, so the
UI now describes its coverage and omits the invalid crypto-market-cap ratio.

Validation: 18 Python and 15 frontend tests. Audit of 26,418 public derivative
rows found 330 futures and one negative OI entry. CoinGecko documents OI in USD:
https://docs.coingecko.com/reference/derivatives-tickers

Still requiring audit: settlement intervals for cross-exchange funding-rate
annualization in legacy agent signals; full identity registry for candidates.

## Phase 5: signal availability, funding provenance and restart recovery

Whale market signals now use explicitly annualized Hyperliquid hourly funding,
not a blanket eight-hour assumption over cross-exchange rates. Missing OI is
not stored as zero; missing funding is no_data. OI alone no longer determines
a directional vote. Aggregate scoring excludes unavailable/warming observations
from effective weight, coverage, reasons and alerts; all unavailable becomes
資料不足. Historical decisions remain unchanged.

History caches persist atomically under CRYPIG_DATA_DIR/history_cache and restore
original timestamps after restart. Expired saved histories remain readable while
refresh runs. Persistence failures are surfaced separately from upstream errors.

Manual POST /cycle is disabled unless CRYPIG_ADMIN_TOKEN is configured and requires
a matching Bearer token. The public dashboard does not use this route; scheduled
collection is unchanged. No new credentials were configured during this work.

Validation: 24 Python and 15 frontend tests, including source availability,
missing-versus-zero, funding provenance, cache restart and anonymous collection.
Source: https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding
