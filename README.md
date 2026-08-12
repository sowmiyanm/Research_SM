# NSE Stock Screener — Weinstein + Delivery Analysis

## What This Tool Does

This screener replaces subjective stock picking with a **systematic, data-driven process**. It screens 1000+ NSE-listed stocks every day and presents 50 pre-computed indicators per stock in a single Excel report — so an analyst can scan the entire market in minutes instead of hours.

The core thesis: **Stocks don't move randomly. Before a major price advance, institutions quietly accumulate shares over weeks. This accumulation leaves fingerprints in the data — high delivery percentages on high volume days, with price basing near its 30-week moving average. This tool detects those fingerprints.**

It is built on **Stan Weinstein's Stage Analysis** (the most widely used trend-following framework for position trading) and enhanced with **NSE delivery data** — a signal unique to Indian markets where every day, NSE publishes how many shares were actually delivered to buyer demat accounts vs squared-off intraday. High delivery on high volume = genuine buying, not speculation.

### What You Get

A daily Excel report with two sheets:
- **Sheet 1 (Report)**: Every stock with 50 columns of indicators + 60 days of color-coded delivery history
- **Sheet 2 (Sector Analysis)**: Sector-wise accumulation breakdown showing which sectors are receiving institutional money

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
pip install -r requirements.txt
python main.py                    # Auto-detect mode (initial or incremental)
open Delivery_Report_*.xlsx       # Review the generated report
```

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
| **RS vs NIFTY** | Relative strength: stock's 52-day return minus NIFTY's 52-day return | **The most underused indicator.** Positive = outperforming market. Negative = underperforming. A Stage 2 stock with negative RS is just riding a bull market — it's not genuinely strong. Always prefer RS > 0. |
| **RS Trend** | Improving / Stable / Weakening | **Early warning system.** RS turning from Weakening to Improving often precedes a Stage 1 → 2 transition. RS turning Weakening in Stage 2 warns of upcoming Stage 3 transition — even before price shows it. |
| **RSI (14)** | Relative Strength Index (0-100) | <30 = oversold (potential bounce). >70 = overbought. **Context matters**: overbought in Stage 2 with rising WMA is normal (momentum); overbought in Stage 3 is dangerous (exhaustion). |
| **RSI Signal** | Overbought / Neutral / Oversold | Quick visual. Pink = overbought, green = oversold. |

### D. Fundamental & Valuation Context (Columns 18-22)

These columns add **fundamental depth** so you can distinguish between technically strong stocks that are genuinely undervalued vs overpriced, and whether the breakout is backed by earnings and promoter conviction.

| Indicator | What It Shows | Analyst Use |
|-----------|---------------|-------------|
| **PE Ratio** | Price-to-Earnings ratio from NSE | **Valuation filter.** A Stage 2 breakout at 15x PE (value zone) is far more sustainable than one at 80x PE (speculative). Green = significantly below sector PE. Pink = significantly above. Use to separate value-driven breakouts from hype-driven ones. |
| **Sector PE** | Average PE of the stock's sector | **Relative valuation benchmark.** Compare PE Ratio against this. PE below 80% of Sector PE = undervalued relative to peers. PE above 150% of Sector PE = premium pricing, needs strong growth to justify. |
| **Price vs 200DMA** | Distance from 200-day Simple Moving Average (%) | **Institutional eligibility filter.** Most global institutional funds will not buy stocks trading below their 200 DMA — it's a hardcoded rule in many mandates. Green = above (eligible for institutional buying). Pink = below (most funds won't touch it). A Stage 2 stock above 200 DMA gets institutional tailwind; one below it is fighting against fund mandates. |
| **Promoter %** | Promoter and promoter group shareholding (%) | **Insider conviction signal.** Promoters have the deepest insider knowledge of their own company. High promoter holding (>60%, green) = skin in the game, aligned incentives. Low promoter holding (<30%, pink) = potential governance risk or lack of conviction. When combined with delivery data, rising promoter % + high delivery = the highest conviction fundamental signal in Indian markets. |
| **Profit Growth YoY** | Latest quarter's profit after tax vs same quarter last year (%) | **Earnings quality check.** A breakout backed by improving earnings is far more sustainable than pure momentum. Green (>20%) = strong earnings growth — the breakout has fundamental support. Pink (<-20%) = significant earnings decline — the breakout may be speculative. A Stage 2 stock with "All Up" momentum AND >20% profit growth = the highest quality setup. |

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
| **Accum Score** | Multi-factor accumulation score (0-6) | **One-number quality rating.** 5-6 = high conviction buy candidate. 4 = solid. 3 = moderate. <= 2 = not in accumulation. Sort descending to find best candidates. |
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
| **Exit Score** | Combined sell signal strength (0-7) | **Overall danger level.** >= 4 (red) = strong sell, act immediately. 2-3 (yellow) = warning, tighten stops. 0-1 = healthy. |
| **Cross Below WMA** | `SELL (Vol)` or `SELL` or `-` | **Primary Weinstein sell signal.** `SELL (Vol)` (red) = volume-confirmed break below 30WMA. This is the mechanical exit — do not argue with it. `SELL` (yellow) = unconfirmed but still a warning. |
| **Distribution Alert** | Yes/No | Near 52W high + declining delivery momentum = institutions distributing shares to retail. Classic top signal. |
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

## Scoring Systems

### Accumulation Score (0-6) — "Should I buy this?"

| Factor | Criteria | Why |
|--------|----------|-----|
| 1-Month ROC | 0% to 15% | Not falling, not parabolic — Goldilocks zone |
| 30d Avg Delivery | >= 55% | Sustained institutional interest |
| Delivery Trend | Increasing or Stable | Not distributing |
| Price vs WMA | -5% to +10% | Early stage, not overextended |
| WMA Slope | Flat or Rising | Trend support present |
| Volume Consistency | 5+ of last 10 days > MA | Sustained participation, not one-off spike |

### Exit Score (0-7) — "Should I sell this?"

| Factor | What triggers it |
|--------|-----------------|
| Stage 3 or 4 | In distribution or downtrend phase |
| Cross below 30WMA | Primary Weinstein sell signal |
| Distribution alert | Near 52W high + falling delivery |
| Declining delivery momentum | Institutional money leaving |
| Price below 10-day MA | Short-term weakness |
| Lower high pattern | Trend structure breaking down |
| RSI overbought in Stage 3/4 | Exhaustion at the top |

## Analyst Playbook

### Finding Buy Candidates

```
Step 1: Filter Stage = 1 or 2                              → eliminates ~50%
Step 2: Filter Accum Score >= 4                             → narrows to quality setups
Step 3: Look for Cross Above = checkmark + Vol Confirmed    → timing the entry
Step 4: Check RS vs NIFTY > 0 (outperforming market)        → genuine strength
Step 5: Check Momentum = "All Up" or "Reversing Up"         → multi-timeframe confirmation
Step 6: Check Divergence != "Bearish"                       → no hidden distribution
Step 7: Verify Wks Above WMA < 10                           → early enough, good risk/reward
Step 8: Check Price vs 200DMA = "Above"                     → institutional eligibility
Step 9: Check Profit Growth YoY > 0%                        → earnings support
Step 10: Check PE Ratio < Sector PE                         → not overvalued vs peers
Step 11: Scan daily columns for recent purple/dark green     → visual confirmation
```

**Highest conviction setup**: Stage 2 + Accum >= 5 + Volume-confirmed cross + RS outperforming + Momentum "All Up" + Bullish divergence + Above 200 DMA + Profit growth > 20% + PE below sector PE.

**Value breakout**: Stage 2 + PE significantly below Sector PE + Profit Growth > 20% + Promoter > 50% + Above 200 DMA. This is a fundamentally sound breakout — earnings growing, insiders holding, price cheap vs peers.

**Pre-breakout setup**: Stage 1 + Stage 1 Alert = Yes + Squeeze = "Coiling" + Bullish divergence + Wks Below > 15 (long base). Wait for Cross Above before entry.

### Monitoring Holdings

```
Check daily:
  - Exit Score climbing? (>= 2 = attention, >= 4 = sell)
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
  |  Accumulation Score           |
  |  Exit Score + Alerts          |
  +-------------------------------+
             |
             v
       Excel Report (2 sheets)
```

### Data Sources
- **Bhav Copy** (`archives.nseindia.com`): Close, traded qty, delivery qty for all stocks daily
- **Quote API** (`nseindia.com/api/quote-equity`): 52-week high/low with dates, PE ratio, sector PE, face value
- **Quote API — Trade Info** (`quote-equity?section=trade_info`): Promoter and promoter group shareholding %
- **Quote API — Financial Results** (`quote-equity?section=financial_results`): Quarterly profit after tax for YoY growth
- **NIFTYBEES ETF**: Used as NIFTY 50 proxy for relative strength (available in bhav copy)

## Configuration

`config.json`:
```json
{
  "lookback_days_display": 60,
  "evaluation_days": 45,
  "volume_ma_period": 36,
  "weekly_wma_period": 30,
  "delivery_bins": { ... }
}
```

## Command Line

```bash
python main.py                          # Auto mode (recommended)
python main.py --mode initial           # Force full reload
python main.py --clear-cache            # Clear cache and reload
python main.py --batch-size 100 --max-workers 8  # Performance tuning
```

## Performance

| Scenario | Time |
|----------|------|
| 1000 tickers, initial load | 5-8 min |
| 1000 tickers, daily update | 1-2 min |
| 50 tickers, initial load | 30-60 sec |

## Project Structure

```
main.py                 Orchestration — batch processing, NIFTY fetch, 52W fetch, fundamentals fetch
nse_data_fetcher.py     NSE data — bhav copy, quote API, promoter holdings, financial results
calculations.py         All calculations — delivery, WMA, stage, RS, momentum, divergence, squeeze, 200DMA
excel_generator.py      Excel report — 50 columns, formatting, colors, layout
data_cache.py           Dual cache — pickle (fast) + Excel (readable)
config.json             Thresholds and settings
tickers.txt             Stock list (one per line)
fno_tickers.txt         F&O stocks (grey highlighting)
```

## Calculations Reference

```
Delivery %       = delivery_quantity / traded_quantity * 100
Volume Ratio     = traded_quantity / SMA(traded_quantity, 36)
Weekly WMA       = Weighted MA on weekly closes (weights 1..30)
WMA Slope        = (current_wma - wma_4weeks_ago) / wma_4weeks_ago * 100
                   > 2% = Rising, < -2% = Falling, else Flat
Cross Above      = prev_week_close < prev_WMA AND curr_week_close >= curr_WMA
Cross Confirmed  = Cross Above AND week_avg_volume_ratio > 1.0
RS vs NIFTY      = stock_52d_ROC - nifty_52d_ROC (positive = outperform)
RSI (14)         = Standard EMA-based RSI
52W High/Low     = From NSE quote API (authoritative), fallback to rolling calc
PE Ratio         = From NSE quote API (metadata.pdSymbolPe)
Sector PE        = From NSE quote API (metadata.pdSectorPe)
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
