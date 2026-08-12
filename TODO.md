# Future Enhancements - NSE Stock Screener

## 🎯 High-Priority Enhancements

### 1. **52-Week High/Low Analysis** ⭐
**Priority:** HIGH
**Effort:** LOW
**Impact:** HIGH

**New Columns to Add:**
- `52W High %`: Distance from 52-week high (e.g., "-5.2%" = 5% below high)
- `52W Low %`: Distance from 52-week low (e.g., "+45%" = 45% above low)
- `Near 52W High`: Flag if within 5% of 52-week high (Yes/No)

**Implementation:**
```python
# In calculations.py
def calculate_52week_metrics(self, df):
    # Calculate rolling 52-week (252 trading days) high and low
    df['52w_high'] = df['close'].rolling(window=252, min_periods=50).max()
    df['52w_low'] = df['close'].rolling(window=252, min_periods=50).min()
    df['52w_high_pct'] = ((df['close'] - df['52w_high']) / df['52w_high'] * 100)
    df['52w_low_pct'] = ((df['close'] - df['52w_low']) / df['52w_low'] * 100)
    df['near_52w_high'] = df['52w_high_pct'].apply(lambda x: 'Yes' if x > -5 else 'No')
    return df
```

**Investment Value:**
- Stocks near 52W highs = potential Stage 2 breakouts
- Stocks far from lows = uptrend confirmation
- **Filter:** "Near 52W High + High Delivery = Strong accumulation"

---

### 2. **Price Momentum & Rate of Change** ⭐⭐
**Priority:** HIGH
**Effort:** LOW
**Impact:** HIGH

**New Columns to Add:**
- `ROC 1W`: 1-week price change %
- `ROC 1M`: 1-month price change %
- `ROC 3M`: 3-month price change %
- `Momentum Score`: Combined momentum indicator (1-10)

**Implementation:**
```python
# In calculations.py
def calculate_momentum_metrics(self, df):
    current_price = df['close'].iloc[-1]

    # 1 week = 5 trading days
    if len(df) >= 5:
        df['roc_1w'] = ((df['close'] - df['close'].shift(5)) / df['close'].shift(5) * 100)

    # 1 month = 22 trading days
    if len(df) >= 22:
        df['roc_1m'] = ((df['close'] - df['close'].shift(22)) / df['close'].shift(22) * 100)

    # 3 months = 66 trading days
    if len(df) >= 66:
        df['roc_3m'] = ((df['close'] - df['close'].shift(66)) / df['close'].shift(66) * 100)

    return df
```

**Investment Value:**
- Quick filter for outperformers
- Identify accelerating trends
- **Filter:** "ROC 3M > 20% + Stage 2 + High Delivery = Strong uptrend"

---

### 3. **Relative Strength vs NIFTY** ⭐⭐⭐
**Priority:** HIGHEST
**Effort:** MEDIUM
**Impact:** VERY HIGH

**New Columns to Add:**
- `RS vs NIFTY (13W)`: Outperformance vs NIFTY over 13 weeks
- `RS Rank`: Percentile rank (1-100, higher = stronger)
- `RS Trend`: Improving/Stable/Declining

**Implementation:**
```python
# Requires NIFTY data download (^NSEI from NSE or Yahoo Finance)
def calculate_relative_strength(self, stock_df, nifty_df):
    # Calculate 13-week (65 trading days) performance
    stock_return = ((stock_df['close'].iloc[-1] - stock_df['close'].iloc[-65])
                    / stock_df['close'].iloc[-65] * 100)
    nifty_return = ((nifty_df['close'].iloc[-1] - nifty_df['close'].iloc[-65])
                    / nifty_df['close'].iloc[-65] * 100)

    rs_value = stock_return - nifty_return
    return rs_value
```

**Investment Value:**
- Filter out weak stocks even if technically good
- Focus on market leaders (Weinstein's #1 rule)
- **Filter:** "RS Rank > 80 + Stage 2 = Top 20% performers"

**Note:** Requires daily NIFTY data fetch and storage

---

### 4. **Delivery Consistency Score** ⭐
**Priority:** HIGH
**Effort:** LOW
**Impact:** MEDIUM-HIGH

**New Columns to Add:**
- `Deliv Consistency (30d)`: % of days with delivery > 50% in last 30 days
- `Deliv Streak`: Consecutive days with high delivery
- `Operator Alert`: Flag for sudden delivery spikes (possible manipulation)

**Implementation:**
```python
def calculate_delivery_consistency(self, df):
    recent_30 = df.tail(30)

    # Consistency: % of days with delivery >= 50%
    high_deliv_days = (recent_30['delivery_pct'] >= 50).sum()
    df['deliv_consistency'] = (high_deliv_days / len(recent_30) * 100)

    # Streak calculation
    streak = 0
    for deliv in reversed(df['delivery_pct'].tail(10).tolist()):
        if deliv >= 50:
            streak += 1
        else:
            break
    df['deliv_streak'] = streak

    # Operator alert: sudden spike
    avg_deliv = df['delivery_pct'].tail(30).mean()
    latest_deliv = df['delivery_pct'].iloc[-1]
    df['operator_alert'] = 'Yes' if latest_deliv > avg_deliv * 1.5 else 'No'

    return df
```

**Investment Value:**
- Avoid pump-and-dump stocks
- Identify sustained accumulation
- **Filter:** "Deliv Consistency > 70% = Genuine accumulation"

---

### 5. **Volume Trend Analysis** ⭐
**Priority:** MEDIUM
**Effort:** LOW
**Impact:** MEDIUM

**New Columns to Add:**
- `Vol Trend`: Increasing/Stable/Decreasing
- `Vol Expansion`: Current vol vs 90-day average (e.g., "150%" = 1.5x)
- `Up Vol vs Down Vol`: Ratio of volume on up days vs down days

**Implementation:**
```python
def calculate_volume_trends(self, df):
    # Compare recent 10-day avg vs previous 20-day avg
    recent_vol = df['traded_quantity'].tail(10).mean()
    older_vol = df['traded_quantity'].tail(30).head(20).mean()

    if recent_vol > older_vol * 1.1:
        df['vol_trend'] = 'Increasing'
    elif recent_vol < older_vol * 0.9:
        df['vol_trend'] = 'Decreasing'
    else:
        df['vol_trend'] = 'Stable'

    # Volume expansion
    avg_90d = df['traded_quantity'].tail(90).mean()
    current_vol = df['traded_quantity'].iloc[-1]
    df['vol_expansion'] = (current_vol / avg_90d * 100)

    return df
```

**Investment Value:**
- Rising volume + rising price = healthy uptrend
- Falling volume in uptrend = warning sign
- **Filter:** "Vol Trend = Increasing + Price rising = Strong buying"

---

### 6. **Consolidation Detection** ⭐⭐
**Priority:** MEDIUM
**Effort:** MEDIUM
**Impact:** HIGH

**New Columns to Add:**
- `Consolidating`: Yes/No (price in tight range)
- `Consol Days`: Number of days consolidating
- `Consol Range %`: Width of consolidation (tight < 5% = better)

**Implementation:**
```python
def detect_consolidation(self, df, lookback=20):
    recent = df.tail(lookback)
    high = recent['close'].max()
    low = recent['close'].min()
    range_pct = ((high - low) / low * 100)

    # Consolidating if range < 8% over last 20 days
    df['consolidating'] = 'Yes' if range_pct < 8 else 'No'
    df['consol_range_pct'] = range_pct

    # Count consolidation days
    # (Advanced: track consecutive days within range)

    return df
```

**Investment Value:**
- Stage 1 base building detection
- Continuation pattern identification
- **Filter:** "Consolidating + High Delivery + Near 30WMA = Potential breakout"

---

### 7. **Liquidity & Trade-ability Filters**
**Priority:** MEDIUM
**Effort:** LOW
**Impact:** MEDIUM

**New Columns to Add:**
- `Avg Daily Value`: Average traded value in ₹ Crores
- `Liquidity Grade`: A/B/C/D based on volume
- `Bid-Ask Impact`: Estimated slippage %

**Implementation:**
```python
def calculate_liquidity_metrics(self, df):
    # Average daily traded value (last 30 days)
    df['avg_daily_value_cr'] = (df['traded_quantity'] * df['close']).tail(30).mean() / 10000000

    # Liquidity grading
    avg_value = df['avg_daily_value_cr'].iloc[-1]
    if avg_value >= 10:
        df['liquidity_grade'] = 'A'
    elif avg_value >= 5:
        df['liquidity_grade'] = 'B'
    elif avg_value >= 1:
        df['liquidity_grade'] = 'C'
    else:
        df['liquidity_grade'] = 'D'

    return df
```

**Investment Value:**
- Filter out penny stocks
- Ensure you can enter/exit easily
- **Filter:** "Liquidity Grade A or B = Tradeable stocks only"

---

### 8. **Volatility Metrics**
**Priority:** LOW
**Effort:** MEDIUM
**Impact:** MEDIUM

**New Columns to Add:**
- `ATR %`: Average True Range as % of price
- `Volatility Rank`: Percentile rank of current volatility
- `Beta`: Volatility vs NIFTY

**Implementation:**
```python
def calculate_volatility_metrics(self, df):
    # ATR (14-day Average True Range)
    df['high_low'] = df['high'] - df['low']  # Requires high/low data
    df['atr'] = df['high_low'].rolling(window=14).mean()
    df['atr_pct'] = (df['atr'] / df['close'] * 100)

    return df
```

**Investment Value:**
- High volatility = higher risk/reward
- Low volatility in breakout = potential explosive move
- **Filter:** "ATR% < 3% = Lower risk stocks"

**Note:** Requires HIGH/LOW price data (not currently fetched from NSE)

---

### 9. **Smart Money Indicators**
**Priority:** LOW
**Effort:** HIGH
**Impact:** MEDIUM

**New Columns to Add:**
- `Inst Holding %`: Institutional ownership
- `Inst Change (QoQ)`: Quarter-over-quarter change
- `Promoter Pledge %`: Promoter shares pledged

**Investment Value:**
- Rising institutional holding = confidence
- High promoter pledge = red flag
- **Filter:** "Inst Holding > 40% + Increasing = Institutional interest"

**Note:** Requires quarterly shareholding data from NSE/BSE reports

---

### 10. **Sector Strength**
**Priority:** LOW
**Effort:** HIGH
**Impact:** MEDIUM-HIGH

**New Columns to Add:**
- `Sector`: Sector classification
- `Sector RS`: Sector performance vs market
- `Stock vs Sector`: Outperformance vs sector

**Investment Value:**
- Identify hot sectors
- Find leaders within strong sectors
- **Filter:** "Sector RS > 0 + Stock vs Sector > 0 = Best of best"

**Note:** Requires sector index data and sector classification

---

## 📋 Implementation Priority

### Phase 1 (Quick Wins - Implement First):
1. ✅ **DONE:** High-volume delivery counts
2. **TODO:** 52-Week High/Low % (easiest, high impact)
3. **TODO:** Price Momentum (ROC 1W, 1M, 3M)
4. **TODO:** Delivery Consistency Score
5. **TODO:** Volume Trend

### Phase 2 (Medium Effort, High Value):
6. **TODO:** Relative Strength vs NIFTY
7. **TODO:** Consolidation Detection
8. **TODO:** Liquidity Filters

### Phase 3 (Advanced):
9. **TODO:** Volatility Metrics (ATR, Beta)
10. **TODO:** Smart Money Indicators (requires external data)
11. **TODO:** Sector Analysis (requires sector classification)

---

## 🎯 Powerful Filter Combinations (Future Use)

### For Long-Term Accumulation:
```
✓ Deliv Avg (30d) > 55%
✓ Deliv Consistency > 70%
✓ Stage = Stage 1 or early Stage 2
✓ RS vs NIFTY > 0
✓ Consolidating OR Near 30WMA support
```

### For Momentum Breakouts:
```
✓ 52W High % > -5% (near all-time high)
✓ ROC 3M > 15%
✓ Volume Trend = Increasing
✓ Stage = Stage 2
✓ RS Rank > 70
```

### For Low-Risk Entries:
```
✓ Consolidating = Yes
✓ Consol Days > 15 (tight base)
✓ Deliv Avg (10d) > 50%
✓ ATR% < 3% (low volatility)
✓ Price near 30WMA support
```

### For Avoiding Bad Stocks:
```
❌ Operator Alert = Yes
❌ Liquidity Grade = D
❌ Promoter Pledge > 50%
❌ Deliv Consistency < 30%
❌ Stage = Stage 4 (downtrend)
```

---

## 💾 Data Requirements for Advanced Features

### Currently Available (NSE Bhav Copy):
- ✅ Date, Close, Traded Quantity, Delivery Quantity
- ✅ All current calculations work with this data

### Additional Data Needed:

1. **HIGH/LOW Prices** (for ATR, true range)
   - Source: NSE Bhav Copy (already has this data!)
   - Action: Update `nse_data_fetcher.py` to extract HIGH_PRICE, LOW_PRICE

2. **NIFTY Daily Data** (for Relative Strength)
   - Source: NSE India API or Yahoo Finance
   - Action: Create separate fetcher for ^NSEI index data

3. **Shareholding Pattern** (for Smart Money)
   - Source: NSE quarterly reports / Company announcements
   - Action: Requires separate data pipeline (complex)

4. **Sector Classification**
   - Source: NSE master file or manual mapping
   - Action: Create `sectors.json` mapping file

---

## 🛠️ Technical Debt / Improvements

### Code Quality:
- [ ] Add unit tests for calculations
- [ ] Add integration tests for data fetching
- [ ] Improve error handling for network failures
- [ ] Add data validation (check for anomalies)

### Performance:
- [ ] Database backend for very large datasets (PostgreSQL/SQLite)
- [ ] Parallel Excel generation for faster report creation
- [ ] Optimize memory usage for 5000+ tickers

### User Experience:
- [ ] Web dashboard for interactive filtering
- [ ] Email alerts for filtered stocks
- [ ] Automated daily runs with cron
- [ ] Export to multiple formats (CSV, JSON, PDF)

---

## 📝 Notes

- All enhancements should maintain backward compatibility
- New columns should have "N/A" for insufficient data
- Excel should auto-adjust column widths
- Add new metrics to both Excel and cache storage
- Update README.md with new column explanations

---

**Last Updated:** December 26, 2025
**Version:** 1.0
**Maintained By:** Development Team
