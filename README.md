# NSE Stock Screener — Weinstein + Delivery Analysis

## What This Tool Does

This screener replaces subjective stock picking with a **systematic, data-driven process**. It screens 1000+ NSE-listed stocks every day and presents 50 pre-computed indicators per stock in a single Excel report — so an analyst can scan the entire market in minutes instead of hours.

The core thesis: **Stocks don't move randomly. Before a major price advance, institutions quietly accumulate shares over weeks. This accumulation leaves fingerprints in the data — high delivery percentages on high volume days, with price basing near its 30-week moving average. This tool detects those fingerprints.**

It is built on **Stan Weinstein's Stage Analysis** (the most widely used trend-following framework for position trading) and enhanced with **NSE delivery data** — a signal unique to Indian markets where every day, NSE publishes how many shares were actually delivered to buyer demat accounts vs squared-off intraday. High delivery on high volume = genuine buying, not speculation.

### What You Get

A daily Excel report with **five sheets**:
- **Shortlist** — the ranked buy-list: Stage 2 / Stage 2 (Pullback) names passing the RS / delivery / liquidity filters, ranked by a blended RS + entry-quality score (chased / wide-stop / no-base entries penalised). Stale/delisted names are excluded.
- **Turnaround** — the J-curve / Stage-1 reversal scanner: stocks emerging from a long decline (deep below 52w high, near 52w low, 30WMA flat/rising), tagged `CONFIRMED` (crossed into Stage 2 on a rising WMA) vs `WATCH` (base still forming). Also excludes stale/delisted names.
- **Report** — every stock with ~50 columns of indicators + 60 days of colour-coded delivery history.
- **Daily Bands** — the delivery colour-band grid across recent sessions.
- **Sector Analysis** — sector-wise accumulation breakdown showing which sectors are receiving institutional money.

### How It Helps an Analyst

Instead of opening charts for 1000 stocks, you:
1. **Filter** the Excel by Stage, Scores, and Signals to get 20-30 candidates in seconds
2. **Validate fundamentals** — is the breakout backed by earnings growth, reasonable valuation, and promoter conviction?
3. **Scan** the color-coded daily columns to visually confirm accumulation patterns
4. **Confirm technicals** with momentum, relative strength, 200 DMA, and divergence data — all in the same row
5. **Monitor** holdings using exit signals that warn you before trends break

The report bridges the gap between **technical analysis** (Weinstein stages, WMA, momentum) and **fundamental analysis** (PE ratio, earnings growth, promoter holding) — so you never have to choose between the two. A breakout is only worth acting on when both technicals AND fundamentals align.

Every column exists to answer a specific question. The sections below explain what each indicator means and how to use it for decision-making.

## Quick Start

```bash
pip install -r requirements.txt          # first time only
python3 main.py                          # DAILY run (default) — fast incremental fetch
open Delivery_Report_*.xlsx              # review the report (Shortlist tab first)
```

Run it **after NSE end-of-day data publishes (~6–7 pm IST)**. Weekends/holidays have no new
data, so a run just re-reports the last session. The file is written to the current directory
as `Delivery_Report_<YYYY-MM-DD>.xlsx`, so run from the project folder.

## The Framework — Four Layers of Evidence

### Layer 1 — Volume Gate (First Filter)
Every day, check: **Is traded volume > 36-day MA?**
- If No → the day is irrelevant (white cell). No signal without volume.
- If Yes → proceed to check delivery quality.

Weinstein requires volume confirmation for all signals. A breakout without volume is a false breakout.

### Layer 2 — Delivery Quality (Institutional Proxy)
For high-volume days, check delivery percentage (shares actually taken to demat vs intraday squared-off):

| Band | Delivery % | Meaning |
|------|-----------|---------|
| Purple | >= 80% | Exceptional institutional buying |
| Dark Green | 60-80% | Strong accumulation |
| Light Green | 50-60% | Moderate accumulation |
| Blue | 40-50% | Mixed — some genuine interest |
| Cream | < 40% + High Vol | High volume but speculative |
| White | Low volume | Not meaningful |

**Why delivery matters**: High delivery % on high volume = investors taking delivery into demat accounts (holding), not just intraday trading. This is the closest proxy for institutional accumulation on NSE.

### Layer 3 — Weinstein Stage + 30WMA
The 30-week Weighted Moving Average (30WMA) determines the trend stage:

| Stage | Price vs WMA | WMA Slope | Action |
|-------|-------------|-----------|--------|
| Stage 1 (Basing) | Below | Flat | Watch — accumulation happening |
| Stage 2 (Uptrend) | Above | Rising | Buy — confirmed uptrend |
| Stage 3 (Topping) | Above | Flat/Falling | Sell — distribution starting |
| Stage 4 (Downtrend) | Below | Falling | Avoid |

### Layer 4 — Fundamental Validation (Quality Gate)
Once a stock passes the technical filters (Stage, Volume, Delivery), apply fundamental checks:

| Check | What to Look For | Why It Matters |
|-------|-----------------|----------------|
| **PE vs Sector PE** | PE below sector average | A breakout at 15x PE is value; at 80x PE is speculation |
| **Price vs 200 DMA** | Above 200 DMA | Most institutional mandates prohibit buying below 200 DMA |
| **Promoter Holding** | > 50% (ideally > 60%) | Insiders with skin in the game = aligned incentives |
| **Profit Growth YoY** | Positive, ideally > 20% | Earnings support makes breakouts sustainable |

A stock passing all three layers (Volume + Delivery + Stage) AND the fundamental gate is the highest quality setup. A stock failing fundamentals but passing technicals is a momentum trade — valid, but higher risk.

## All Available Indicators — What They Mean and How to Use Them

The report provides **50 indicators per stock**, grouped by purpose. Here is every indicator with its exact meaning and how an analyst should interpret it.

### A. Identity & Context (Columns 1-2)

| Indicator | What It Shows | Analyst Use |
|-----------|---------------|-------------|
| **MCAP** | Market cap category (Large/Mid/Small) | Size = risk profile. Largecaps are safer but slower; smallcaps move faster but are riskier. Use for position sizing. |
| **SEGMENT** | Sector/industry classification | Diversify across 3-5 sectors. Avoid overconcentration. Cross-reference with Sheet 2 (Sector Analysis) to pick stocks from sectors with increasing accumulation. |

### B. Weinstein Stage & Trend (Columns 3-10)

These columns tell you **where the stock is in its lifecycle** and whether a trend change is happening.

| Indicator | What It Shows | Analyst Use |
|-----------|---------------|-------------|
| **STAGE** | Current Weinstein stage (1-4) | **The most important filter.** Only buy Stage 1 (late, with alerts) or Stage 2. Sell Stage 3. Avoid Stage 4. This single column eliminates ~50% of stocks immediately. |
| **Wks Above WMA** | How many consecutive weeks price has been above 30WMA | Measures **Stage 2 maturity**. Low count (1-5) = early breakout, best risk/reward. High count (>20) = extended, tighten stops. Zero = not in uptrend. |
| **Wks Below WMA** | How many consecutive weeks price has been below 30WMA | Measures **basing duration**. For Stage 1 stocks, longer base (>15 weeks) = stronger potential breakout. Also shows how deep a Stage 4 downtrend is. |
| **Price vs WMA** | Distance from 30WMA as percentage (e.g., "Above +5.2%") | **Entry timing.** Best entries are -5% to +10% range. Above +15% = overextended, wait for pullback. Below -10% = downtrend, avoid. |
| **30WMA Slope** | Rising / Flat / Falling | **Trend confirmation.** Rising = confirmed uptrend (safest buys). Flat = basing or topping (context-dependent). Falling = downtrend (avoid). |
| **Cross Above** | Checkmark if price crossed above 30WMA this or last week | **Primary buy trigger.** This is the Weinstein Stage 1 → Stage 2 transition. A checkmark here means the stock just broke out of its base. |
| **Vol Confirmed** | Whether the cross week had above-average volume | **Breakout quality.** Green "Vol" = genuine breakout with institutional participation. Yellow "No Vol" = suspect breakout that may fail. Never buy an unconfirmed cross. |
| **Vol Ratio** | Today's volume as multiple of 36-day MA (e.g., 2.3x) | **Conviction strength.** 1.0x = average. 1.5x = notable. 2.0x+ = strong conviction day. On cross days, higher = better. On down days, higher = distribution. |

### C. Market Position (Columns 11-17)

These columns show **where the stock sits relative to its own history and the market**.

| Indicator | What It Shows | Analyst Use |
|-----------|---------------|-------------|
| **52W High %** | Distance from 52-week high, with date (e.g., "-5.2% (05-Jan)") | Near 0% with Stage 2 = strength, potential new high. Far from high (-30%+) = deep correction. The date tells you when the high was made — recent date = the trend was recently strong. |
| **52W Low %** | Distance from 52-week low, with date | Near 0% = at lows, weakness or deep value. High percentage (+50%+) = strong rally from bottom. The date tells you when the low was made. |
| **Near 52W High** | Yes if within 5% of 52-week high | Gold highlight. In Stage 2 with rising WMA = breakout to new highs (very bullish). In Stage 3 with flat WMA = potential distribution zone (caution). |
| **RS vs NIFTY** | Mansfield Relative Strength: `(stock_close/NIFTY_close) / (its_52W_SMA) - 1` as % | **Mansfield RS.** Positive = stock is outperforming its OWN historical relationship to NIFTY — it is gaining strength, not just strong. Negative = losing relative momentum. A Stage 2 stock with negative RS is in a weakening trend despite being above 30WMA. Always prefer RS > 0. |
| **RS Trend** | Improving / Stable / Weakening vs 10-week MA of RS | **Early warning system.** RS turning from Weakening to Improving often precedes a Stage 1 → 2 transition. RS turning Weakening in Stage 2 warns of upcoming Stage 3 transition — even before price shows it. |
| **RSI (14)** | Relative Strength Index (0-100) | <30 = oversold (potential bounce). >70 = overbought. **Context matters**: overbought in Stage 2 with rising WMA is normal (momentum); overbought in Stage 3 is dangerous (exhaustion). |
| **RSI Signal** | Overbought / Neutral / Oversold | Quick visual. Pink = overbought, green = oversold. |

### D. Fundamental & Valuation Context

| Indicator | What It Shows | Analyst Use |
|-----------|---------------|-------------|
| **PE Ratio** | Price-to-Earnings ratio | **Valuation filter.** A Stage 2 breakout at 15x PE (value zone) is far more sustainable than one at 80x PE (speculative). Separates value-driven breakouts from hype-driven ones. *Sourced from the MarketLens augment since NSE's live fundamentals API is blocked. `main.py` auto-merges it from the newest export in `marketlens_drop/` on every run — the column stays blank only until an export is dropped there.* |
| **Price vs 200DMA** | Distance from 200-day Simple Moving Average (%) | **Institutional eligibility filter.** Most global funds will not buy a stock trading below its 200 DMA. Green = above (eligible for institutional buying), pink = below. A Stage 2 stock above 200 DMA has an institutional tailwind. |

> **Removed 2026-09** (NSE fundamentals API blocked → these were 0% populated, i.e. confusing blank columns): `Sector PE`, `Promoter %`, `Profit Gr. YoY` from the Report, and `Promoter %` from the Shortlist. The duplicate `Divergence` header was renamed `Dlv Divergence` for the delivery-section one. `PE` is retained because it is filled from the MarketLens export; if a licensed fundamentals feed is added later, the others can be re-added populated.

### E. Momentum & Advanced Signals (Columns 23-29)

These columns give you **multi-timeframe momentum, hidden divergences, and pre-breakout detection** — signals that can't be seen by just looking at a chart.

| Indicator | What It Shows | Analyst Use |
|-----------|---------------|-------------|
| **ROC 1W** | Price rate of change over 5 trading days | **Short-term momentum.** Green = up, pink = down. Use to time entries: negative ROC 1W in a Stage 2 stock with positive ROC 1M/3M = pullback to buy. |
| **ROC 1M** | Price rate of change over 22 trading days | **Medium-term momentum.** The most useful single momentum reading. Positive + Stage 2 = confirmed uptrend. Turning negative = early warning. |
| **ROC 3M** | Price rate of change over 66 trading days | **Long-term momentum.** Shows the bigger picture. Negative ROC 3M with positive ROC 1W = fresh reversal (early Stage 2 candidate). All three positive = confirmed trend. |
| **Momentum** | Alignment of all three timeframes | **3-second trend read.** "All Up" (green) = full trend confirmation. "Reversing Up" = fresh uptrend starting (best entry). "Pullback" = dip in uptrend (buy opportunity). "All Down" (red) = avoid. "Breaking Down" = trend failing. |
| **Divergence** | Price-delivery divergence (Bullish/Bearish/None) | **The highest-value unique signal.** Bullish divergence (green) = price falling but delivery rising = institutions buying the dip quietly. This often appears in late Stage 1 before breakout. Bearish divergence (red) = price rising but delivery falling = rally on speculation, not conviction. Sell signal. |
| **Squeeze** | Volatility contraction (Coiling/Tight/Normal) | **Pre-breakout detector.** "Coiling" (orange) = price range has contracted significantly = the stock is building energy for a big move. Combined with Stage 1 + bullish divergence = highest conviction setup. "Tight" (yellow) = moderate contraction, worth watching. |
| **Squeeze Ratio** | ATR(10) / ATR(50) — lower = tighter squeeze | The raw number. Below 0.5 = Coiling. Below 0.75 = Tight. Above 1.0 = expanding volatility (breakout may be happening). |

### F. Delivery Analysis (Columns 30-39)

These columns quantify **how consistently institutions are accumulating**.

| Indicator | What It Shows | Analyst Use |
|-----------|---------------|-------------|
| **Deliv Avg(10d)** | Recent 10-day average delivery % | Shows **current** institutional interest. Compare to 30d avg: if 10d > 30d, interest is accelerating. |
| **Deliv Avg(30d)** | Sustained 30-day average delivery % | Shows **sustained** interest. >= 55% = strong institutional presence. < 40% = mostly speculative activity. |
| **Deliv Trend** | Increasing / Stable / Decreasing | Direction of delivery momentum. Increasing in Stage 1/2 = bullish. Decreasing in Stage 2/3 = distribution warning. |
| **Count (>=50%)/45** | Days with delivery >= 50% in last 45 days | Raw consistency measure. Higher = more sustained accumulation. |
| **Count (>=40%)/45** | Days with delivery >= 40% in last 45 days | Broader consistency including moderate interest. |
| **Count (>=50% + HighVol)/45** | Days with delivery >= 50% AND volume > MA | **The strongest confirmation.** High delivery alone could be low-volume noise. This requires BOTH. >= 15/45 = strong accumulation. |
| **Count (>=40% + HighVol)/45** | Same but including 40%+ delivery | Broader version of above. |
| **Count (>=50% + HighVol)/15d** | Same metric but for last 15 days only | **Recency check.** Is the accumulation happening NOW or was it 30 days ago? Higher = more recent activity. |
| **Count (>=50% + HighVol)/20d** | Same metric but for last 20 days | Slightly wider recent window. |

### G. Exit Signals (Columns 40-47)

These columns tell you **when to sell or avoid**. Each maps to a specific risk.

| Indicator | What It Shows | Analyst Use |
|-----------|---------------|-------------|
| **Cross Below WMA** | `SELL (Vol)` or `SELL` or `-` | **Primary Weinstein sell signal.** `SELL (Vol)` (red) = volume-confirmed break below 30WMA. This is the mechanical exit — do not argue with it. `SELL` (yellow) = unconfirmed but still a warning. |
| **Distribution Alert** | Yes/No | (A) Near 52W high + declining delivery = institutions distributing shares to retail. (B) Stage 3/4 + declining delivery + down-day volume spikes = sustained post-breakdown distribution. Both are classic top signals. |
| **Stage 3 Alert** | Exit Signal / Stage 3 / - | "Exit Signal" (red) = stock just transitioned from Stage 2 to Stage 3. This is the earliest stage-based exit trigger. |
| **Trend Break** | Higher High / Lower High / Neutral | Lower High (yellow) = price structure is deteriorating. In Stage 2, this is an early warning. In Stage 3, it confirms distribution. |
| **Price vs 10MA** | Above / Below | Short-term trend check. Below 10MA = short-term weakness. Multiple days below 10MA in Stage 2 = pullback or potential stage change. |
| **Deliv Momentum** | Rising / Stable / Declining | Declining (yellow) = delivery participation is dropping. In Stage 2/3, this means money is leaving the stock. |
| **Vol Spike Down** | Yes/No | High volume on a significant down day (>1% drop). This is a distribution pattern — big players selling into any rally. Multiple "Yes" in a short period = heavy distribution. |

### H. Stage 1 Alerts (Columns 48-49)

These columns help find **turnaround candidates** — stocks basing in Stage 1 that show early signs of accumulation.

| Indicator | What It Shows | Analyst Use |
|-----------|---------------|-------------|
| **Stage 1 Alert** | Yes/No | Only appears for Stage 1 stocks meeting 3+ of 5 accumulation criteria. These are potential turnaround plays — add to watchlist and wait for Cross Above. |
| **Stage 1 Strength** | Score (0-5) | How many criteria are met: volume activity, delivery avg, volume-backed delivery, not at 52W lows, RSI not oversold. >= 4 (bright green) = strong setup. |

### I. Stock + Daily Data (Columns 50+)

| Indicator | What It Shows | Analyst Use |
|-----------|---------------|-------------|
| **STOCK** | Ticker symbol | Identifier |
| **Date columns (60 days)** | `Delivery% \| Yes/No` with color coding | **Visual pattern recognition.** Look for clusters of purple/dark green (sustained accumulation). Recent shift from white to colored = fresh interest. Mostly white = no institutional participation. |

## Scoring Systems (removed in 2026-08)

The Accumulation Score (0-7) and Exit Score (0-10) composite scoring systems have been
retired. Each was a weighted black box — equal-weight factors penalized pullback entries
(a -1% monthly ROC got zero for Factor 1 even with every other signal strong), and the
Lower High false positives on a 20-day window fed the Exit Score at full weight.
The one-number output hid *which* factor was driving the rating.

The replacement is **holistic**: the Report sheet shows all the raw data side by side.
The Shortlist now ranks on RS vs NIFTY percentile (Weinstein's core rule — buy market
leaders), with bonus points for fresh cross-above (+8/+12) and Triple Confirm (+5)
signals — transparent, aligned with the method, and not hiding anything behind a score.

## Shortlist Ranking (current)

The Shortlist sheet ranks candidates by:

1. **RS vs NIFTY percentile** (primary — 100% weight). Higher RS = higher rank.
2. **Bonus for fresh signals**: +12 for volume-confirmed cross above 30WMA this week,
   +8 for unconfirmed cross above, +5 for Triple Confirm firing today.
3. **Filters**: Stage 2 or Stage 2 (Pullback), RS ≥ min_rs, Dlv30 ≥ min_deliv,
   ADV ≥ min_adv (median), corp-action stocks excluded.

## Analyst Playbook

### Finding Buy Candidates

```
Step 1: Filter Stage = 1 or 2                              → eliminates ~50%
Step 2: Check RS vs NIFTY > 0 (outperforming market)        → genuine strength
Step 3: Look for Cross Above = ✓Vol (volume-confirmed)      → timing the entry
Step 4: Check Momentum = "All Up" or "Reversing Up"         → multi-timeframe confirmation
Step 5: Check Divergence = "Bullish"                        → delivery up while price flat
Step 6: Verify Wks Above WMA < 10                           → early enough, good risk/reward
Step 7: Check Price vs 200DMA = Above                       → institutional eligibility
Step 8: Check Profit Growth YoY > 0%                        → earnings support
Step 9: Check PE Ratio < Sector PE                          → not overvalued vs peers
Step 10: Scan daily columns for recent purple/dark green     → visual confirmation
Step 11: Check Dist to Pivot ≤ 5%                           → near entry zone
```

**Highest conviction setup**: Stage 2 + Volume-confirmed cross + RS outperforming + Momentum "All Up" + Bullish divergence + Above 200 DMA + Profit growth > 20% + PE below sector PE + At/near pivot.

**Value breakout**: Stage 2 + PE significantly below Sector PE + Profit Growth > 20% + Promoter > 50% + Above 200 DMA. This is a fundamentally sound breakout — earnings growing, insiders holding, price cheap vs peers.

**Pre-breakout setup**: Stage 1 + Stage 1 Alert = Yes + Squeeze = "Coiling" + Bullish divergence + Wks Below > 15 (long base). Wait for Cross Above before entry.

### Monitoring Holdings

```
Check daily:
  - Cross Below WMA? (especially "SELL (Vol)" = immediate exit)
  - Divergence = "Bearish"? (delivery falling while price rises = distribution)
  - RS Trend = "Weakening"? (losing relative strength vs market)
  - Price vs 200DMA turning negative? (losing institutional eligibility)

Check weekly:
  - Stage 3 Alert = "Exit Signal"? (stage transition)
  - Wks Above WMA > 20? (extended — tighten stops)
  - Momentum shifting to "Pullback" or "Breaking Down"?

Check quarterly (after results season):
  - Profit Growth YoY turning negative? (fundamental deterioration)
  - Promoter % declining? (insiders losing confidence — strongest red flag)
  - PE Ratio expanding far above Sector PE? (becoming overvalued)
```

### Finding Turnaround Candidates (Stage 1)

```
Filter Stage = 1
Filter Stage 1 Alert = Yes, Strength >= 4
Check Squeeze = "Coiling" or "Tight" (volatility contracting)
Check Divergence = "Bullish" (price flat/down but delivery rising)
Check Wks Below WMA > 15 (long enough base)
Wait for Cross Above 30WMA before entry — do NOT buy before the cross
```

### Sector Rotation (Sheet 2)

The **Sector Analysis** sheet shows:
- Daily color band breakdown by sector (last 5 days)
- 5-day trend (increasing/stable/decreasing accumulation)
- Sector ranking by institutional quality (Purple + Dark Green count)

**Use it to**: identify which sectors are receiving fresh institutional money and which are seeing distribution. Pick stocks from top-ranked sectors with increasing trends.

## Data Pipeline

```
NSE Archives         NSE Quote API             NSE Quote API            NIFTYBEES
(Bhav Copy)          (quote-equity)            (trade_info +            (Bhav Copy)
     |                    |                    financial_results)            |
     v                    v                          |                      v
Daily OHLCV +       52W High/Low                     v                 NIFTY 50 Proxy
Delivery Data       PE Ratio                  Promoter Holding %       for Relative
     |              Sector PE                 Quarterly Profit PAT     Strength
     |              Face Value                       |                      |
     +-------+----------+----------+-----------------+----------+-----------+
             v
       calculations.py
  +-------------------------------+
  |  Delivery % + Color Band      |
  |  Volume MA36 + Ratio          |
  |  Weekly 30WMA + Cross         |
  |  Stage Classification         |
  |  RSI (14)                     |
  |  52W High/Low + Dates         |
  |  PE Ratio + Sector PE         |
  |  Price vs 200 DMA             |
  |  Promoter Holding %           |
  |  Profit Growth YoY            |
  |  Relative Strength vs NIFTY   |
  |  Multi-TF Momentum (ROC)      |
  |  Price-Delivery Divergence    |
  |  Consolidation Squeeze        |
  |  Entry/Exit Level Signals     |
  +-------------------------------+
             |
             v
       Excel Report (5 sheets)
```

### Data Sources
- **Bhav Copy** (`archives.nseindia.com`): Close, traded qty, delivery qty for all stocks daily
- **Quote API** (`nseindia.com/api/quote-equity`): 52-week high/low with dates, PE ratio, sector PE, face value
- **Quote API — Trade Info** (`quote-equity?section=trade_info`): Promoter and promoter group shareholding %
- **Quote API — Financial Results** (`quote-equity?section=financial_results`): Quarterly profit after tax for YoY growth
- **NIFTYBEES ETF**: Used as NIFTY 50 proxy for relative strength (available in bhav copy)

## Configuration

`config.json` (current):
```json
{
  "lookback_days_display": 60,
  "evaluation_days": 45,
  "volume_ma_period": 36,
  "volume_ma_multiplier": 1.0,
  "breakout_volume_multiplier": 2.0,
  "weekly_wma_period": 30,
  "wma_slope_threshold_pct": 2.0,

  "corp_action_gap_threshold_pct": 30.0,   // >this single-day move = candidate corp action
  "adjust_corporate_actions": true,        // back-adjust splits/bonuses in-memory
  "adjust_negative_gaps_only": true,       // only down-gaps qualify
  "adjust_turnover_band": [0.2, 5.0],      // turnover-continuity gate
  "rs_trend_band": 3.0,                    // ± band for RS "Stable" on the Mansfield scale

  "stale_days_threshold": 4,               // exclude names this many days behind newest
  "delisted_days_threshold": 60,

  "delivery_bins": { "...": "colour thresholds" },

  "shortlist": {
    "min_adv_crore": 5,
    "stages": ["Stage 2", "Stage 2 (Pullback)"],
    "min_rs": 0,
    "min_deliv_30d": 45,
    "exclude_corp_action": true,           // exclude only UNRESOLVED corp actions
    "ranking": {
      "max_chase_pct": 10.0, "max_risk_pct": 18.0,
      "chase_penalty": 25.0, "risk_penalty": 25.0, "no_base_penalty": 30.0
    },
    "top_n": 100
  },

  "turnaround": {
    "min_adv_crore": 3,
    "min_below_high_pct": 25,              // >= this far below 52w high
    "max_above_low_pct": 40,              // <= this far above 52w low
    "stages": ["Stage 1", "Stage 2", "Stage 2 (Pullback)"],
    "exclude_corp_action": true,
    "top_n": 60
  }
}
```

## Command Line

```bash
# DAILY (default) — fetch only new sessions since last run. Use this most days.
python3 main.py
python3 main.py --mode daily

# MONTHLY — back up the cache, wipe it, rebuild the full 2-year history from scratch.
# Auto-rolls-back if the rebuild ends below --min-coverage (default 80%). ~40-70 min.
python3 main.py --mode monthly

# Other flags
python3 main.py --clear-cache                     # clear cache before running
python3 main.py --skip-financials                 # skip quarterly-results fetch (faster)
python3 main.py --batch-size 100 --max-workers 8  # performance tuning
python3 main.py --no-backup                       # (monthly) skip pre-rebuild backup — not recommended
python3 main.py --min-coverage 70                 # (monthly) rollback threshold
```

- **Daily** is safe to run repeatedly — it only pulls sessions you don't already have.
- **Monthly** is the "true-up": run it roughly once a month (or if you suspect drift). It's
  protected — the old cache is backed up first and automatically restored if the rebuild fails
  or comes back too sparse.
- `(daily → auto, monthly → initial)` internally; the older `--mode auto/initial/incremental`
  names still work.

## Augmenting with MarketLens (optional)

NSE's fundamentals (PE, dividend yield, …) aren't in the free bhav-copy feed, so they can be
layered in from an NSE **Market Lens** export you download yourself (do NOT scrape it — export
manually; automated collection breaches NSE's terms).

1. In Market Lens, build a screen with `Current Market Price > 0` (returns the whole universe)
   and **export it to CSV**.
2. Drop the file into `marketlens_drop/` (auto-created on first run).
3. Run the screener normally:
   ```bash
   python3 main.py
   ```
   On every run `main.py` picks up the **newest** file in `marketlens_drop/` and merges **PE**
   onto each ticker before the report is written (filling only where NSE returned nothing, so a
   live value is never overwritten). No renaming needed — drop a fresh export each day. If the
   folder is empty the run still succeeds; the PE column just stays blank.

To inspect an export before relying on it, run the standalone helper:
   ```bash
   python3 marketlens_augment.py         # picks the NEWEST file in marketlens_drop/
   ```
   It reports PE / Dividend Yield / Market Cap / Sector coverage keyed by ticker, and
   **cross-checks** the price data feeding the screener by recomputing 1D/1W/1M return + volume
   from the cache and comparing to Market Lens. High 1W/1M correlation = your prices agree with
   NSE's; big per-ticker outliers = stale or mis-adjusted names to inspect.

`test_marketlens_import.py` is a lighter probe that just reports what a given export contains
and how cleanly it joins to your universe.

## Guards Against False Positives

The ranked sheets are protected against the classic ways a screener misleads:

- **Stale / delisted exclusion** — Shortlist and Turnaround skip any ticker whose last cached
  date lags the universe's newest by more than `stale_days_threshold`, so a symbol frozen in
  Stage 2 on old data is never shown as a live buy. The excluded count prints in the sheet title.
- **Corporate-action adjustment** — splits/bonuses are back-adjusted only when a gap clears
  three gates (>30% single-day move, negative-only, turnover-continuity). Unresolved cases are
  flagged and kept off the Shortlist rather than silently mis-priced.
- **Entry-quality penalties** — RS alone cannot lift a chased / wide-stop / no-base name to the
  top; explicit penalties demote un-actionable entries.
- **RS-outage banner** — a *full RS outage* means NIFTY failed to fetch **and** no NIFTY cache
  was available, so RS vs NIFTY is N/A for every stock that run (rare once the NIFTY cache
  exists). When it happens the **Shortlist** title shows a red warning and bypasses the RS
  filter rather than silently ranking on delivery/entry only. The **Turnaround** sheet stays
  fail-safe in this case — with RS missing, a name can only reach `CONFIRMED` via a
  volume-confirmed 30WMA cross, so nothing is falsely confirmed — but note it does **not** print
  the banner itself (see residuals below).
- **Full-history guards** — Stage 2 / RS require complete WMA (30w) and Mansfield (260d)
  windows; short-history rows can't be classified as valid signals.

> **Known residuals (flagged, accepted — not gated):**
>
> 1. **Corporate-action mis-adjustment.** A genuine >30% news-driven crash that trades on
>    continuous turnover can still be mis-adjusted as a split/bonus, erasing the decline and
>    potentially flipping Stage 4 → Stage 2. NSE publishes no corporate-action feed the pipeline
>    consumes, so this is left as a manual check rather than a wrong automated gate: **sanity-check
>    any name that suddenly looks "healthy" after a large recent gap-down** before acting on it.
>
> 2. **RS-outage banner is Shortlist-only.** During a rare full RS outage (see above), the
>    Turnaround and Report tabs still compute correctly and fail-safe, but do **not** show the
>    outage banner. Impact is transparency, not integrity — no false signal results; you simply
>    won't be warned on those tabs that RS was missing. If a run looks off, check the Shortlist
>    tab's banner to confirm whether RS was available that run.

## Performance

| Scenario | Time |
|----------|------|
| 1000 tickers, initial load | 5-8 min |
| 1000 tickers, daily update | 1-2 min |
| 50 tickers, initial load | 30-60 sec |

## Project Structure

```
main.py                    Orchestration — batch processing, NIFTY fetch, 52W fetch, backup/rollback, health check, CLI
nse_data_fetcher.py        NSE data — bhav copy, quote API, promoter holdings, financial results, Yahoo 52w fallback
calculations.py            All calculations — delivery, WMA, stage, RS, momentum, divergence, squeeze, 200DMA, corp-action adjustment
excel_generator.py         Excel report — 5 sheets (Shortlist, Turnaround, Report, Daily Bands, Sector Analysis)
data_cache.py              Dual cache — pickle (fast) + Excel (readable)
marketlens_augment.py      Pick up a Market Lens export from marketlens_drop/, merge PE/yield/mcap/sector, validate returns/volume
test_marketlens_import.py  Probe an export: report columns, field coverage, join rate
config.json                Thresholds and settings
tickers.txt                Stock list (one per line)
fno_tickers.txt            F&O stocks (grey highlighting)
marketlens_drop/           Drop your Market Lens CSV export here (auto-created)
```

### Handling Ticker Renames

NSE occasionally renames tickers (mergers, rebranding). When this happens:

1. Update the old name in `tickers.txt` to the new one
2. Rename the cache: `mv data_cache/OLDNAME.pkl data_cache/NEWNAME.pkl`
3. Rename the Excel backup: `mv data_cache/excel/OLDNAME_historical.xlsx data_cache/excel/NEWNAME_historical.xlsx`
4. Re-run — the pipeline picks up the cached history under the new name

No code changes needed. The health check will flag the old name as "likely delisted" if you forget.

## Calculations Reference

```
Delivery %       = delivery_quantity / traded_quantity * 100
Volume Ratio     = traded_quantity / SMA(traded_quantity, 36)
Weekly WMA       = Weighted MA on weekly closes (weights 1..30)
WMA Slope        = (current_wma - wma_4weeks_ago) / wma_4weeks_ago * 100
                   > 2% = Rising, < -2% = Falling, else Flat
Cross Above      = prev_week_close < prev_WMA AND curr_week_close >= curr_WMA
Cross Confirmed  = Cross Above AND week_avg_volume_ratio > breakout_volume_multiplier (2.0)
                   Note: is_high_vol (used in the daily delivery/accumulation grid and
                   Triple Confirm) uses a separate, lower threshold — volume_ma_multiplier
                   (1.0) — since Weinstein's 2x rule governs breakout-week confirmation,
                   not everyday delivery quality.
Triple Confirm   = price_vs_wma_pct >= 0 AND is_high_vol AND delivery_pct >= 50 (same day)
RS vs NIFTY      = (close/NIFTY_close) / SMA(close/NIFTY_close, 260) - 1 as a %
RSI (14)         = Standard EMA-based RSI
52W High/Low     = From NSE quote API (authoritative), fallback to rolling calc
PE Ratio         = From MarketLens export (NSE quote-API PE is blocked); auto-merged by main.py
Sector PE        = Removed 2026-09 (NSE quote API blocked → 0% populated)
200 DMA          = SMA(close, 200) — institutional trend filter
Price vs 200DMA  = (close - 200DMA) / 200DMA * 100
Promoter %       = From NSE quote API (securityWiseDP.promoterAndPromoterGroup)
Profit Growth    = (latest_quarter_PAT - same_quarter_prev_year_PAT) / |prev_PAT| * 100
ROC 1W/1M/3M     = (close_now - close_N_ago) / close_N_ago * 100
Divergence       = Price ROC(20d) vs Delivery trend(20d) — opposing = divergence
Squeeze Ratio    = ATR(10) / ATR(50) — below 0.5 = coiling, below 0.75 = tight
```

## Requirements

- Python 3.8+
- pandas, numpy, requests, openpyxl
- Internet connection to NSE India

## License

Educational and personal use only.
