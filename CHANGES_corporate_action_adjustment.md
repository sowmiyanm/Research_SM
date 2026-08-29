# Corporate-Action Price Adjustment

Splits and bonuses are now corrected instead of just flagged. Every test below was run against your live cache.

---

## What it does

NSE bhav copy is unadjusted at source, so a 1:1 bonus prints as a clean −50% overnight gap and every indicator downstream reads it as a crash. HDFCAMC showed `52W High −56%` and `Stage 1` while actually trading near its adjusted highs.

`apply_corporate_action_adjustment()` back-adjusts across each detected gap: prices before it are multiplied by the gap ratio, share counts divided by it. Multiple actions compound.

**No network needed.** The gap ratio *is* the adjustment factor, and the ones in your data land on clean corporate-action fractions — which doubles as evidence they're real actions rather than crashes:

```
HDFCAMC    0.5020  = 1:1 bonus
ZFCVINDIA  0.1654  = 1:5
V2RETAIL   0.1019  = 1:9
TATAINVEST 0.1043  = 1:9
```

I built it from your own data rather than Yahoo's adjusted series deliberately: no network dependency, deterministic, and testable offline. It also independently agrees with Yahoo — see below.

---

## Safety design

**The cache is never modified.** Adjustment happens in memory during processing, so:

- it can't compound across runs
- reverting is one config flag, not a rebuild
- your cache stays a faithful record of raw NSE data

Controlled by `adjust_corporate_actions` in `config.json` (default `true`). Set it `false` to restore the previous detect-and-exclude behaviour exactly.

---

## Verification

**1. The gaps are gone**

| | max 1-day move after adjustment | adj_factor |
|---|---|---|
| HDFCAMC | 8.3% | 0.5020 → 1.0 |
| V2RETAIL | 10.0% | 0.1019 → 1.0 |
| TATAINVEST | 16.8% | 0.1043 → 1.0 |
| ZFCVINDIA | 13.7% | 0.1654 → 1.0 |

**2. Independent agreement with Yahoo.** HDFCAMC's `52W High %` computed from the adjusted cache is **−13.15%**. Yahoo's adjusted figure in the 28-Aug report was **−13.4%**. Two completely independent methods, 0.25pp apart — that's the strongest evidence the adjustment is right.

**3. HDFCAMC, before and after**

```
                  unadjusted      ADJUSTED
52w_high_pct          -56.40        -13.15
pivot_price              nan       2957.87
stop_level               nan       2566.71
dist_to_pivot_pct        nan        -13.15
```

Pivot and stop were previously incomputable because the base detector couldn't find a coherent range across the −50% cliff. They now work.

**4. Unaffected stocks are untouched — the critical test**

```
69 stocks processed with adjustment ON vs OFF
  10 had a corporate action
  59 unaffected
  columns that differed on the 59: 0
```

Checked `stage`, `weekly_wma30`, `52w_high_pct`, `rsi`, `deliv_avg_30d`, `dist_to_pivot_pct`, `stop_level`, `roc_3m`, `accum_score`. For a stock with no corporate action this code is a mathematical no-op.

**5. `delivery_pct` is unchanged** — it's a ratio of two quantities that scale together, so it's invariant by construction. Confirmed identical.

`vol_ratio` **does** change, and should: before, a split stock's post-action volumes looked 2× (or 9×) higher than its pre-action volumes, inflating the ratio. They're now on one scale.

**6. Synthetic control.** A manufactured 1:2 split mid-series: max daily move drops to 0.2%, recovered factor 0.501 against a true 0.500.

**7. Edge cases** — all pass, including two that used to crash:

```
empty · 1 row · zero close · all-NaN close · duplicate dates · idempotency
index series with no volume columns    <- previously KeyError
frame with no delivery column          <- previously KeyError
```

I fixed that missing-column crash while here: `process_ticker_data` now fills absent volume columns with NaN and logs a warning, instead of dying inside `calculate_delivery_percentage`. That was outstanding Issue 3 from Review #9.

**8. Full pipeline** — 4 sheets, correct dimensions, filters intact under every configuration.

---

## Your shortlist does not change

```
adjustment ON vs OFF, both excluding corp-action stocks:  identical, 0 differences
```

Because those stocks are still excluded by `exclude_corp_action: true`, today's shortlist is byte-for-byte what it was. Nothing to re-check.

What *has* changed is the Report sheet: it's now on **one consistent price basis**. Issue 1 from Review #9 — the mixed adjusted/unadjusted columns — is resolved.

---

## Optional next step: re-admit those stocks

Now that prices are corrected, `exclude_corp_action` is doing less useful work. On a 70-ticker sample, flipping it to `false`:

```
shortlist 13 -> 16 names
newly admitted: INDOTECH, COFORGE, MOTHERSON
  MOTHERSON   Stage 2   52WH -2.8%   →Pivot +9.2%   →Stop 14.2%
```

Scaled up, that's roughly 35 companies returning to your investable universe.

**I left the flag at `true`** so nothing changed without you deciding. When you want them back:

```json
"exclude_corp_action": false
```

I'd suggest flipping it, running once, and eyeballing any newly-admitted name that has `adj_factor != 1.0` against its chart — just to satisfy yourself the adjustment matches what actually happened. After that it can stay off.

---

## Three gates, not one

The original version inferred a corporate action from the price gap alone. It now has to clear three tests, because a single test is only as good as its threshold.

### Gate 1 — a >30% single-day move

Not a heuristic. NSE circuit limits mean a genuine collapse **cannot** produce one. Measured across 500 stocks over two years:

| | |
|---|---|
| Genuine multi-day collapses (>30% over 5 days) | 39 found |
| Their median worst single day | **−20.0%** (the circuit limit) |
| Their worst single day, all 39 | **−28.4%** |
| Smallest observed corporate action | **−31.5%** |

Real collapses happen as consecutive limit-down days (INDOTHAI −53% over 5 sessions, worst day exactly −20.0%), never one cliff. The 30% threshold sits in an empirically empty band with margin either side.

The daily-move distribution shows the same break — 378 observations in 15–20%, then only **26** in 20–30%, then **68** above 30%. A normal tail decays; this one dips and spikes. That discontinuity is a separate population.

### Gate 2 — price must FALL (`adjust_negative_gaps_only`)

Splits and bonuses are 62 of 68 observed gaps and land on clean ratios. The 6 upward gaps match no consolidation ratio (2.305, 2.232, 1.493…) and two fall on 31-Dec, which smells like a data artefact. All six are now rejected — verified.

### Gate 3 — turnover must be continuous (`adjust_turnover_band`)

A corporate action moves price and share count inversely, so the **value** traded is unchanged. A genuine sell-off trades far more.

| Turnover ratio across the event | Corporate actions | Genuine −15% to −30% days |
|---|---|---|
| median | **0.84** | **4.29** |

A real sell-off trades 5.1× more value. The default band `[0.2, 5.0]` keeps 90% of genuine actions.

### What happens when a gate rejects

**Nothing breaks.** The row stays flagged by `detect_corporate_actions`, so `exclude_corp_action` still keeps it off the shortlist. A rejection returns that stock to today's behaviour — excluded, not wrongly adjusted. The failure mode is conservative by construction.

Measured on 100 stocks: 9 flagged, **7 adjusted**, 2 rejected by the turnover test (SCHNEIDER, SKFINDIA — both with ratios that don't match a clean split) and left excluded.

### Verified after adding the gates

```
HDFCAMC    adj 0.5020 (1:1)    HDFCBANK   adj 0.4956 (1:1)
BAJFINANCE adj 0.1005 (1:9)    KOTAKBANK  adj 0.1974 (1:4)
NESTLEIND  adj 0.4907 (1:1)    TRENT      adj 0.6665 (1:2)
  -> all still adjusted; max daily move afterwards 6.8-14.8%

AXISCADES, INDOTHAI, EPACK, PANACEABIO, SUBEXLTD, HERANBA
  -> all correctly NOT adjusted, all still flagged

Unaffected stocks whose output changed: 0
```

The residual risk is now a stock that falls more than 30% in one session *and* does so on continuous turnover. No such case exists in two years of your data.
