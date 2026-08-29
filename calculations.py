"""
Calculation Module
Handles all calculations: delivery %, MA36, WMA30, signals
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class StockCalculator:
    """Performs all required calculations on stock data"""

    def __init__(self, config):
        self.config = config
        self.volume_ma_period = config.get('volume_ma_period', 36)
        self.volume_ma_multiplier = config.get('volume_ma_multiplier', 1.0)
        self.breakout_volume_multiplier = config.get('breakout_volume_multiplier', 2.0)
        self.weekly_wma_period = config.get('weekly_wma_period', 30)
        self.wma_slope_threshold = config.get('wma_slope_threshold_pct', 2.0)
        # Single-day % move above which a price gap is treated as a suspected
        # corporate action. Must stay above NSE's 20% circuit band -- see
        # detect_corporate_actions() for the measured justification.
        self.corp_action_gap_threshold = config.get('corp_action_gap_threshold_pct', 30.0)
        # Back-adjust prices/volumes across detected splits & bonuses.
        # See apply_corporate_action_adjustment(). Set false to restore the old
        # behaviour (detect and exclude, but leave prices unadjusted).
        self.adjust_corporate_actions = config.get('adjust_corporate_actions', True)
        # Only adjust price FALLS. Splits/bonuses (price down) are 62 of 68
        # observed gaps and land on clean ratios; the handful of upward gaps
        # do not match any consolidation ratio and may be data artefacts.
        self.adjust_negative_gaps_only = config.get('adjust_negative_gaps_only', True)
        # Turnover-continuity confirmation. A corporate action leaves the value
        # traded unchanged (price halves, share count doubles): measured median
        # 0.84. A genuine sell-off trades ~5x more value: measured median 4.29.
        band = config.get('adjust_turnover_band', [0.2, 5.0])
        self.adjust_turnover_band = (float(band[0]), float(band[1]))
        # Dead-band for the Improving/Weakening/Stable label on rs_trend.
        # Scale-dependent — see calculate_relative_strength.
        self.rs_trend_band = config.get('rs_trend_band', 3.0)
        # Base / pivot / stop parameters (see calculate_base_levels)
        base_cfg = config.get('base_levels', {})
        self.pivot_lookback_weeks = base_cfg.get('pivot_lookback_weeks', 52)
        self.pivot_skip_weeks = base_cfg.get('pivot_skip_weeks', 4)
        self.base_min_weeks = base_cfg.get('base_min_weeks', 5)
        self.base_max_depth_pct = base_cfg.get('base_max_depth_pct', 25.0)
        self.stop_buffer_pct = base_cfg.get('stop_buffer_pct', 2.0)
        self.fallback_stop_pct = base_cfg.get('fallback_stop_pct', 10.0)

    def calculate_delivery_percentage(self, df):
        """
        Calculate delivery percentage

        Args:
            df: DataFrame with traded_quantity and delivery_quantity

        Returns:
            DataFrame with delivery_pct column
        """
        df = df.copy()
        df['delivery_pct'] = np.where(
            df['traded_quantity'] > 0,
            (df['delivery_quantity'] / df['traded_quantity']) * 100,
            np.nan
        )
        return df

    def calculate_volume_ma(self, df):
        """
        Calculate 36-day moving average of traded volume

        Args:
            df: DataFrame with traded_quantity

        Returns:
            DataFrame with vol_ma36 and is_high_vol columns
        """
        df = df.copy()
        df['vol_ma36'] = df['traded_quantity'].rolling(window=self.volume_ma_period, min_periods=self.volume_ma_period).mean()

        # Volume ratio (how many times above/below MA)
        df['vol_ratio'] = np.where(
            pd.notna(df['vol_ma36']) & (df['vol_ma36'] > 0),
            df['traded_quantity'] / df['vol_ma36'],
            np.nan
        )

        # Check if current volume > MA × multiplier (Weinstein: 2× volume spike)
        multiplier = self.volume_ma_multiplier
        df['is_high_vol'] = df.apply(
            lambda row: 'Yes' if pd.notna(row['vol_ma36']) and row['traded_quantity'] > row['vol_ma36'] * multiplier
            else ('No' if pd.notna(row['vol_ma36']) else 'N/A'),
            axis=1
        )
        return df

    def calculate_weekly_wma(self, df):
        """
        Calculate weekly WMA30 and detect crosses

        Args:
            df: DataFrame with date and close columns

        Returns:
            DataFrame with weekly_wma30, cross_above, cross_below, weeks_above_wma,
            weeks_below_wma, wma_slope columns
        """
        df = df.copy()
        df['date'] = pd.to_datetime(df['date'])

        # IDEMPOTENCY GUARD: drop any columns this method is about to produce.
        # Without this, being handed a frame that has already been through here
        # makes the two merges below emit _x/_y suffixed columns, and the next
        # read of df['cross_above'] dies with a bare KeyError. Not reachable in
        # the current pipeline (only raw frames are cached) but it is a trap for
        # anyone who later caches processed output or re-runs the calculator
        # over its own result.
        _produced = ['weekly_wma30', 'cross_above', 'cross_below', 'weeks_above_wma',
                     'weeks_below_wma', 'wma_slope', 'week_avg_vol_ratio',
                     'cross_above_confirmed', 'cross_below_confirmed',
                     'week', 'week_end_date']
        df = df.drop(columns=[c for c in _produced if c in df.columns], errors='ignore')

        # NSE trading weeks always run Mon-Fri, so grouping by "week ending Friday"
        # already gives the correct weekly close regardless of any configured
        # week-start day - there's no other trading day a week could start on.
        df['week'] = df['date'].dt.to_period('W-FRI')  # Week ending Friday

        # Get weekly close (last close of each week)
        weekly_data = df.groupby('week').agg({
            'date': 'last',
            'close': 'last'
        }).reset_index()

        weekly_data.columns = ['week', 'week_end_date', 'weekly_close']

        # Calculate WMA30 on weekly closes
        weekly_data['weekly_wma30'] = self._weighted_moving_average(
            weekly_data['weekly_close'],
            self.weekly_wma_period
        )

        # Detect cross above AND cross below
        weekly_data['cross_above'] = False
        weekly_data['cross_below'] = False
        for i in range(1, len(weekly_data)):
            prev_close = weekly_data.iloc[i - 1]['weekly_close']
            prev_wma = weekly_data.iloc[i - 1]['weekly_wma30']
            curr_close = weekly_data.iloc[i]['weekly_close']
            curr_wma = weekly_data.iloc[i]['weekly_wma30']

            if pd.notna(prev_wma) and pd.notna(curr_wma):
                if prev_close < prev_wma and curr_close >= curr_wma:
                    weekly_data.loc[i, 'cross_above'] = True
                elif prev_close >= prev_wma and curr_close < curr_wma:
                    weekly_data.loc[i, 'cross_below'] = True

        # Calculate WMA slope at the WEEKLY level (compare current week vs 4
        # weeks ago). Previously this was done on daily rows with i-20, which is
        # unreliable: a holiday-shortened week has fewer than 5 trading days, so
        # 20 daily rows back can land in a different week than intended, and the
        # same week's WMA value repeats across all 5 days, making the daily loop
        # compare identical values 5 times per week without adding new information.
        #
        # Threshold of ±2% over 4 weeks — meaningful trend change, not noise.
        weekly_data['wma_slope'] = 'N/A'
        for i in range(4, len(weekly_data)):  # Need 4 prior weekly WMA readings
            current_wma = weekly_data.iloc[i]['weekly_wma30']
            past_wma = weekly_data.iloc[i - 4]['weekly_wma30']

            if pd.notna(current_wma) and pd.notna(past_wma) and past_wma > 0:
                slope_pct = ((current_wma - past_wma) / past_wma) * 100

                if slope_pct > self.wma_slope_threshold:
                    weekly_data.loc[i, 'wma_slope'] = 'Rising'
                elif slope_pct < -self.wma_slope_threshold:
                    weekly_data.loc[i, 'wma_slope'] = 'Falling'
                else:
                    weekly_data.loc[i, 'wma_slope'] = 'Flat'

        # Calculate weeks above/below 30WMA (consecutive count)
        # NOTE: A single week crossing below WMA resets the counter to zero.
        # This is intentional — "weeks above" measures the UNINTERRUPTED
        # streak. A stock that was above for 25 weeks and dipped below for
        # one week genuinely broke its streak. The Excel report shows both
        # counts side by side so an analyst can see: 25 weeks above before
        # the break, and now 3 weeks below.
        weekly_data['weeks_above_wma'] = 0
        weekly_data['weeks_below_wma'] = 0
        above_count = 0
        below_count = 0
        for i in range(len(weekly_data)):
            wma = weekly_data.iloc[i]['weekly_wma30']
            close = weekly_data.iloc[i]['weekly_close']
            if pd.notna(wma):
                if close >= wma:
                    above_count += 1
                    below_count = 0
                else:
                    below_count += 1
                    above_count = 0
            weekly_data.loc[weekly_data.index[i], 'weeks_above_wma'] = above_count
            weekly_data.loc[weekly_data.index[i], 'weeks_below_wma'] = below_count

        # Merge back to daily data. Cross flags are computed at the WEEKLY
        # level — they should only be TRUE on the week-end row (Friday or
        # last trading day of the week), not broadcast to every daily row.
        daily_metrics = ['week', 'weekly_wma30', 'weeks_above_wma',
                         'weeks_below_wma', 'wma_slope']
        df = df.merge(
            weekly_data[daily_metrics],
            on='week',
            how='left'
        )
        # Merge cross flags separately, keyed by date (week_end_date)
        df = df.merge(
            weekly_data[['week_end_date', 'cross_above', 'cross_below']],
            left_on='date',
            right_on='week_end_date',
            how='left'
        )
        df['cross_above'] = df['cross_above'].fillna(False)
        df['cross_below'] = df['cross_below'].fillna(False)
        if 'week_end_date' in df.columns:
            df.drop(columns=['week_end_date'], inplace=True)

        # Calculate weekly average volume ratio for volume-confirmed cross detection
        # Group daily vol_ratio by week and compute mean
        if 'vol_ratio' in df.columns:
            weekly_vol = df.groupby('week')['vol_ratio'].mean().reset_index()
            weekly_vol.columns = ['week', 'week_avg_vol_ratio']
            df = df.merge(weekly_vol, on='week', how='left')

            # Volume-confirmed cross: cross occurred AND week's avg volume > N× MA
            # (Weinstein standard: 2×, configurable via breakout_volume_multiplier)
            df['cross_above_confirmed'] = df['cross_above'] & (df['week_avg_vol_ratio'] > self.breakout_volume_multiplier)
            df['cross_below_confirmed'] = df['cross_below'] & (df['week_avg_vol_ratio'] > self.breakout_volume_multiplier)
        else:
            df['week_avg_vol_ratio'] = np.nan
            df['cross_above_confirmed'] = df['cross_above']
            df['cross_below_confirmed'] = df['cross_below']

        return df

    def _weighted_moving_average(self, series, period):
        """
        Calculate weighted moving average

        Args:
            series: Pandas Series
            period: WMA period

        Returns:
            Series with WMA values
        """
        weights = np.arange(1, period + 1)

        def wma(x):
            if len(x) < period:
                return np.nan
            return np.dot(x[-period:], weights) / weights.sum()

        return series.rolling(window=period, min_periods=period).apply(wma, raw=True)

    def get_delivery_color_band(self, delivery_pct):
        """
        Get color band for delivery percentage

        Args:
            delivery_pct: Delivery percentage value

        Returns:
            Band name (purple, dark_green, light_green, blue, white)
        """
        if pd.isna(delivery_pct):
            return 'white'

        bins = self.config.get('delivery_bins', {})

        if delivery_pct >= bins.get('purple', {}).get('min', 80):
            return 'purple'
        elif delivery_pct >= bins.get('dark_green', {}).get('min', 60):
            return 'dark_green'
        elif delivery_pct >= bins.get('light_green', {}).get('min', 50):
            return 'light_green'
        elif delivery_pct >= bins.get('blue', {}).get('min', 40):
            return 'blue'
        else:
            return 'white'

    def calculate_summary_counts(self, df, evaluation_days=45):
        """
        Calculate summary counts for last N days

        Args:
            df: DataFrame with delivery_pct and is_high_vol
            evaluation_days: Number of days to evaluate (default 45)

        Returns:
            Dictionary with count statistics
        """
        # High delivery only signals accumulation if price wasn't falling that
        # day - a block-deal exit or pledge unwind can print identical high
        # delivery + high volume on a down day, which is distribution, not
        # buying. Days where price fell are excluded from every "accumulation"
        # count below (mirrors the direction check already used in
        # calculate_price_delivery_divergence).
        price_up_or_flat = df['close'].diff().fillna(0) >= 0

        # Get last N days
        recent_data = df.tail(evaluation_days)
        recent_up = price_up_or_flat.tail(evaluation_days)

        # Count excluding blue and white (delivery >= 50%), price not down
        count_excl_blue = (
            (recent_data['delivery_pct'] >= 50) & recent_data['delivery_pct'].notna() & recent_up
        ).sum()

        # Count including blue, excluding white (delivery >= 40%), price not down
        count_incl_blue = (
            (recent_data['delivery_pct'] >= 40) & recent_data['delivery_pct'].notna() & recent_up
        ).sum()

        # Count with high volume (delivery >= 50% AND volume > MA), price not down - 45 days
        count_excl_blue_highvol = recent_data.apply(
            lambda row: 1 if (pd.notna(row['delivery_pct']) and row['delivery_pct'] >= 50
                             and row.get('is_high_vol') == 'Yes') else 0,
            axis=1
        )
        count_excl_blue_highvol = (count_excl_blue_highvol.values & recent_up.values).sum()

        # Count with high volume (delivery >= 40% AND volume > MA), price not down - 45 days
        count_incl_blue_highvol = recent_data.apply(
            lambda row: 1 if (pd.notna(row['delivery_pct']) and row['delivery_pct'] >= 40
                             and row.get('is_high_vol') == 'Yes') else 0,
            axis=1
        )
        count_incl_blue_highvol = (count_incl_blue_highvol.values & recent_up.values).sum()

        # NEW: Recent 15-day count (delivery >= 50% AND volume > MA), price not down
        recent_15 = df.tail(15)
        recent_up_15 = price_up_or_flat.tail(15)
        count_excl_blue_highvol_15d = recent_15.apply(
            lambda row: 1 if (pd.notna(row['delivery_pct']) and row['delivery_pct'] >= 50
                             and row.get('is_high_vol') == 'Yes') else 0,
            axis=1
        )
        count_excl_blue_highvol_15d = (count_excl_blue_highvol_15d.values & recent_up_15.values).sum()

        # NEW: Recent 20-day count (delivery >= 50% AND volume > MA), price not down
        recent_20 = df.tail(20)
        recent_up_20 = price_up_or_flat.tail(20)
        count_excl_blue_highvol_20d = recent_20.apply(
            lambda row: 1 if (pd.notna(row['delivery_pct']) and row['delivery_pct'] >= 50
                             and row.get('is_high_vol') == 'Yes') else 0,
            axis=1
        )
        count_excl_blue_highvol_20d = (count_excl_blue_highvol_20d.values & recent_up_20.values).sum()

        return {
            'count_purple_darkgreen_lightgreen': int(count_excl_blue),
            'count_including_blue': int(count_incl_blue),
            'count_excl_blue_highvol': int(count_excl_blue_highvol),
            'count_incl_blue_highvol': int(count_incl_blue_highvol),
            'count_excl_blue_highvol_15d': int(count_excl_blue_highvol_15d),
            'count_excl_blue_highvol_20d': int(count_excl_blue_highvol_20d),
            'evaluation_days': evaluation_days
        }

    def calculate_weinstein_metrics(self, df):
        """
        Calculate Weinstein stage analysis metrics

        Args:
            df: DataFrame with date, close, and weekly_wma30

        Returns:
            DataFrame with Stage, price_vs_wma, wma_slope added
        """
        df = df.copy()

        # Calculate price position relative to 30WMA
        df['price_vs_wma_pct'] = np.where(
            pd.notna(df['weekly_wma30']),
            ((df['close'] - df['weekly_wma30']) / df['weekly_wma30'] * 100),
            np.nan
        )

        df['price_vs_wma'] = df['price_vs_wma_pct'].apply(
            lambda x: f"Above {x:+.1f}%" if pd.notna(x) and x >= 0
            else (f"Below {x:+.1f}%" if pd.notna(x) else "N/A")
        )

        # Calculate Weinstein Stage
        df['stage'] = 'N/A'
        for i in range(len(df)):
            price_vs = df.iloc[i]['price_vs_wma_pct']
            slope = df.iloc[i]['wma_slope']

            if pd.notna(price_vs) and slope != 'N/A':
                if price_vs < 0 and slope == 'Falling':
                    df.loc[i, 'stage'] = 'Stage 4'  # Markdown/Downtrend
                elif price_vs < 0 and slope == 'Flat':
                    df.loc[i, 'stage'] = 'Stage 1'  # Accumulation/Basing
                elif price_vs >= 0 and slope == 'Rising':
                    df.loc[i, 'stage'] = 'Stage 2'  # Markup/Uptrend
                elif price_vs < 0 and slope == 'Rising':
                    # Pullback within an established uptrend — WMA still
                    # rising but price dipped below it. This is a normal
                    # Stage 2 pullback, distinct from clean Stage 2 (price
                    # above rising WMA). The sub-label helps analysts
                    # distinguish a buying opportunity (pullback) from a
                    # stock that's already extended above the WMA.
                    df.loc[i, 'stage'] = 'Stage 2 (Pullback)'
                elif price_vs >= 0 and slope in ['Flat', 'Falling']:
                    df.loc[i, 'stage'] = 'Stage 3'  # Distribution/Topping

        return df

    def calculate_triple_confirm(self, df):
        """
        Triple Confirm: price above the 30WMA, volume above its 36-day
        average, and delivery elevated (>=50%), all on the same day.

        This is a stricter, price-direction-aware signal than the existing
        delivery/volume color-band grid (which flags volume+delivery quality
        with no check on which way price is trending).

        Args:
            df: DataFrame with price_vs_wma_pct, is_high_vol, delivery_pct

        Returns:
            DataFrame with triple_confirm ('Yes'/'No') column added
        """
        df = df.copy()
        df['triple_confirm'] = np.where(
            (df['price_vs_wma_pct'] >= 0) &
            (df['is_high_vol'] == 'Yes') &
            pd.notna(df['delivery_pct']) & (df['delivery_pct'] >= 50),
            'Yes', 'No'
        )
        return df

    def calculate_delivery_trends(self, df):
        """
        Calculate delivery percentage trends

        Args:
            df: DataFrame with delivery_pct

        Returns:
            DataFrame with delivery averages and trend
        """
        df = df.copy()

        # Calculate 10-day and 30-day averages
        df['deliv_avg_10d'] = df['delivery_pct'].rolling(window=10, min_periods=5).mean()
        df['deliv_avg_30d'] = df['delivery_pct'].rolling(window=30, min_periods=15).mean()

        # Calculate delivery trend (comparing 10d vs 30d average)
        df['deliv_trend'] = 'N/A'
        for i in range(len(df)):
            avg_10d = df.iloc[i]['deliv_avg_10d']
            avg_30d = df.iloc[i]['deliv_avg_30d']

            if pd.notna(avg_10d) and pd.notna(avg_30d):
                diff = avg_10d - avg_30d

                if diff > 3:
                    df.loc[i, 'deliv_trend'] = 'Increasing'
                elif diff < -3:
                    df.loc[i, 'deliv_trend'] = 'Decreasing'
                else:
                    df.loc[i, 'deliv_trend'] = 'Stable'

        return df

    def calculate_rsi(self, df, period=14):
        """
        Calculate Relative Strength Index (RSI)

        Args:
            df: DataFrame with close prices
            period: RSI period (default 14)

        Returns:
            DataFrame with rsi and rsi_signal columns added
        """
        df = df.copy()

        # Calculate price changes
        delta = df['close'].diff()

        # Separate gains and losses
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)

        # Calculate average gain and loss using EMA (Exponential Moving Average)
        # This is the standard RSI calculation method
        avg_gain = gain.ewm(com=period-1, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(com=period-1, min_periods=period, adjust=False).mean()

        # Calculate RS and RSI
        rs = avg_gain / avg_loss
        df['rsi'] = 100 - (100 / (1 + rs))

        # avg_gain == avg_loss == 0 means price was completely flat over the
        # whole window (not missing data) - 0/0 produces NaN here, which
        # would otherwise fall through to the 'N/A' label below and get
        # treated the same as "not enough history yet". A flat price has
        # genuinely neutral momentum, so it should read as RSI 50/Neutral.
        flat_price = (avg_gain == 0) & (avg_loss == 0)
        df.loc[flat_price, 'rsi'] = 50.0

        # Add RSI signal classification
        df['rsi_signal'] = df['rsi'].apply(
            lambda x: 'Overbought' if pd.notna(x) and x > 70
            else ('Oversold' if pd.notna(x) and x < 30
                  else ('Neutral' if pd.notna(x) else 'N/A'))
        )

        return df

    def detect_corporate_actions(self, df):
        """
        Flag stocks with suspected corporate actions (splits, bonuses) that
        create artificial price gaps in historical data.

        Detection: look for single-day close-price changes beyond
        corp_action_gap_threshold_pct (default 30%).

        Why 30% and not 15%: NSE applies 20% price bands to most non-F&O
        stocks, so a small/mid cap hitting the upper or lower circuit prints
        a clean ±20.0% move that is NOT a corporate action. Measured over a
        296-ticker sample, a 15% threshold flagged 83 stocks of which only 8
        were genuine splits/bonuses — 74 of the 83 were 15-25% moves, mostly
        exactly ±20.0% circuit hits. Because the shortlist excludes any stock
        with a flag anywhere in its history, that quarantined ~25% of the
        universe to catch 8 real events. At 30% the same sample yields 8 of 8
        genuine actions and zero false positives (real splits/bonuses show up
        at -45% to -90%: a 1:2 bonus is -50%, 1:5 is -80%).

        Adds columns:
          corp_action_suspected   — 'Yes' if any gap day found
          corp_action_gap_dates   — semicolon-separated list of gap dates

        The Excel report should grey-out or warn on these rows because
        historical price levels before the gap are not comparable to
        current levels without adjustment.
        """
        df = df.copy()
        df['corp_action_suspected'] = 'No'
        df['corp_action_gap_dates'] = ''
        df['corp_action_gap_info'] = ''  # always present (see REQUIRED_COLUMNS note)

        if len(df) < 2:
            return df

        # Compute day-over-day close change
        close_prev = df['close'].shift(1)
        close_curr = df['close']

        # pct_change: avoid inf when prev close is 0
        with np.errstate(divide='ignore', invalid='ignore'):
            pct_change = np.abs((close_curr - close_prev) / close_prev.replace(0, np.nan)) * 100

        gap_threshold = self.corp_action_gap_threshold

        gap_mask = pd.notna(pct_change) & (pct_change > gap_threshold)

        # Exclude first data row (no prior close to compare)
        if len(df) > 0:
            gap_mask.iloc[0] = False

        if gap_mask.any():
            gap_dates = df.loc[gap_mask, 'date'].dt.strftime('%Y-%m-%d').tolist()
            df.loc[gap_mask, 'corp_action_suspected'] = 'Yes'
            for idx in gap_mask[gap_mask].index:
                df.loc[idx, 'corp_action_gap_dates'] = df.loc[idx, 'date'].strftime('%Y-%m-%d')
            df['corp_action_gap_info'] = '; '.join(gap_dates) if gap_dates else ''

            # Also flag all rows BEFORE the earliest gap as suspect
            # (historical prices are pre-adjustment)
            earliest_gap_idx = gap_mask[gap_mask].index[0]
            df.loc[:earliest_gap_idx, 'corp_action_suspected'] = 'Yes'

        return df

    def apply_corporate_action_adjustment(self, df):
        """Back-adjust prices and volumes across detected corporate actions.

        WHY: NSE bhav copy is unadjusted at source. A 1:1 bonus prints as a
        clean -50% overnight gap, which every downstream indicator then reads
        as a crash — HDFCAMC showed "52W High -56%" and Stage 1 when it was
        actually trading near its adjusted highs. Excluding those stocks (the
        old behaviour) kept them out of the shortlist but also removed ~35 real
        companies from the investable universe.

        HOW: the gap ratio IS the adjustment factor. For HDFCAMC the close went
        5336 -> 2679, a ratio of 0.502 — so every price before that date is
        multiplied by 0.502 to bring it onto the post-bonus scale, and every
        share count before it is divided by 0.502 (the share count doubled).
        Multiple actions compound, so the factor for row j is the product of
        the ratios of all gaps occurring after j.

        Observed ratios land on clean corporate-action fractions, which is a
        useful sanity check that these are real actions and not crashes:
            HDFCAMC 0.502 (1:1)   V2RETAIL 0.1019 (1:9)
            ZFCVINDIA 0.1654 (1:5)  TATAINVEST 0.1043 (1:9)

        IMPORTANT: this runs in memory only. The cache keeps raw NSE data, so
        the adjustment can never compound across runs, and reverting is just a
        config flag. delivery_pct is a ratio of two quantities that scale
        together, so it is mathematically unchanged.

        Adds `adj_factor` (1.0 where nothing was adjusted).
        """
        df = df.copy()
        df['adj_factor'] = 1.0
        # 'unresolved' = a price discontinuity that is STILL present after this
        # method has done what it can. This, not corp_action_suspected, is what
        # the shortlist should exclude on: a stock we successfully corrected is
        # safe to trade, whereas one we flagged but could not fix still has a
        # broken price series.
        df['corp_action_unresolved'] = 'No'

        def _mark_unresolved(frame):
            """Re-measure gaps on whatever prices we ended up with."""
            if len(frame) < 2:
                return frame
            with np.errstate(divide='ignore', invalid='ignore'):
                p = (frame['close'] / frame['close'].shift(1).replace(0, np.nan) - 1.0).abs() * 100
            still = pd.notna(p) & (p > self.corp_action_gap_threshold)
            if len(still) > 0:
                still.iloc[0] = False
            if still.any():
                frame['corp_action_unresolved'] = 'Yes'
            return frame

        if not self.adjust_corporate_actions or len(df) < 2:
            return _mark_unresolved(df)

        close = df['close']
        prev = close.shift(1)
        with np.errstate(divide='ignore', invalid='ignore'):
            ratio = close / prev.replace(0, np.nan)
            pct = (ratio - 1.0).abs() * 100

        gap = pd.notna(pct) & (pct > self.corp_action_gap_threshold)
        if len(gap) > 0:
            gap.iloc[0] = False

        # ── Gate 2: only adjust price FALLS ──────────────────────────────
        if self.adjust_negative_gaps_only:
            rejected_up = gap & (ratio > 1.0)
            if rejected_up.any():
                logger.info(f"Not adjusting {int(rejected_up.sum())} upward gap(s) "
                            f"(adjust_negative_gaps_only) - left flagged instead")
            gap = gap & (ratio < 1.0)

        # ── Gate 3: turnover-continuity confirmation ─────────────────────
        # A corporate action moves price and share count inversely, so the
        # VALUE traded is continuous across the ex-date (measured median 0.84).
        # A genuine sell-off large enough to clear the 30% gate would show
        # panic volume instead (measured median 4.29 on -15%..-30% days).
        # Failing this test does NOT mark the stock clean - the row stays
        # flagged by detect_corporate_actions, so exclude_corp_action still
        # protects the shortlist. The fallback is today's behaviour, not a
        # wrong adjustment.
        lo, hi = self.adjust_turnover_band
        if gap.any() and 'traded_quantity' in df.columns:
            turnover = df['close'] * df['traded_quantity']
            with np.errstate(divide='ignore', invalid='ignore'):
                tno_ratio = turnover / turnover.shift(1).replace(0, np.nan)
            confirmed = gap & pd.notna(tno_ratio) & tno_ratio.between(lo, hi)
            unconfirmed = gap & ~confirmed
            if unconfirmed.any():
                for idx in unconfirmed[unconfirmed].index:
                    logger.warning(
                        f"Gap of {pct.loc[idx]:.1f}% NOT adjusted - turnover ratio "
                        f"{tno_ratio.loc[idx]:.2f} outside [{lo}, {hi}], so this looks "
                        f"more like genuine trading than a corporate action. "
                        f"Left flagged for exclusion instead."
                    )
            gap = confirmed

        if not gap.any():
            return _mark_unresolved(df)

        # factor[j] = product of gap ratios strictly AFTER j
        n = len(df)
        factor = np.ones(n)
        run = 1.0
        for j in range(n - 2, -1, -1):
            if bool(gap.iloc[j + 1]) and pd.notna(ratio.iloc[j + 1]):
                run *= float(ratio.iloc[j + 1])
            factor[j] = run

        # Guard: a factor of 0 or a non-finite value would wipe the series out.
        if not np.all(np.isfinite(factor)) or np.any(factor <= 0):
            logger.warning("Corporate-action adjustment produced a non-finite/zero factor "
                           "- leaving prices unadjusted for this ticker")
            return _mark_unresolved(df)

        for col in ('close', 'high', 'low'):
            if col in df.columns:
                df[col] = df[col] * factor
        # Share counts move inversely to price
        for col in ('traded_quantity', 'delivery_quantity'):
            if col in df.columns:
                df[col] = df[col] / factor

        df['adj_factor'] = factor
        n_adj = int((factor != 1.0).sum())
        logger.info(f"Applied corporate-action adjustment to {n_adj} rows "
                    f"({int(gap.sum())} action(s); factors "
                    f"{sorted({round(float(r), 4) for r in ratio[gap].dropna()})})")
        return _mark_unresolved(df)

    def calculate_52week_metrics(self, df, nse_52w_data=None):
        """
        Calculate 52-week high/low metrics

        Args:
            df: DataFrame with close prices
            nse_52w_data: Optional dict with NSE authoritative 52W data
                         {52w_high, 52w_low, 52w_high_date, 52w_low_date}

        Returns:
            DataFrame with 52-week metrics added
        """
        df = df.copy()

        # Compute a genuine trailing 252-trading-day high/low per row using
        # intraday high/low columns when available (from bhav copy); fall
        # back to close-based extremes for older cached data. The NSE
        # snapshot (52W_HIGH/52W_LOW from quote API) is only authoritative
        # for the current calendar 52-week window and is applied via
        # nse_52w_data below.
        if 'high' in df.columns and 'low' in df.columns:
            df['52w_high'] = df['high'].rolling(window=252, min_periods=126).max()
            df['52w_low'] = df['low'].rolling(window=252, min_periods=126).min()
        else:
            df['52w_high'] = df['close'].rolling(window=252, min_periods=126).max()
            df['52w_low'] = df['close'].rolling(window=252, min_periods=126).min()
        df['52w_high_date'] = ''
        df['52w_low_date'] = ''

        if nse_52w_data is not None and len(df) > 0:
            # The NSE snapshot is authoritative only for TODAY - it reflects the
            # current 52-week window, not the window that existed on any past
            # date. Broadcasting it across the whole column would be look-ahead
            # bias (every historical row would "know" future price extremes), so
            # it's applied only to the most recent row.
            last_idx = df.index[-1]
            df.loc[last_idx, '52w_high'] = nse_52w_data['52w_high']
            df.loc[last_idx, '52w_low'] = nse_52w_data['52w_low']
            df.loc[last_idx, '52w_high_date'] = nse_52w_data.get('52w_high_date', '')
            df.loc[last_idx, '52w_low_date'] = nse_52w_data.get('52w_low_date', '')

        # Calculate distance from 52W high (negative = below, positive = above/at)
        df['52w_high_pct'] = np.where(
            pd.notna(df['52w_high']),
            ((df['close'] - df['52w_high']) / df['52w_high'] * 100),
            np.nan
        )

        # Calculate distance from 52W low (positive = above)
        df['52w_low_pct'] = np.where(
            pd.notna(df['52w_low']),
            ((df['close'] - df['52w_low']) / df['52w_low'] * 100),
            np.nan
        )

        # Flag if near 52W high (within 5%)
        df['near_52w_high'] = df['52w_high_pct'].apply(
            lambda x: 'Yes' if pd.notna(x) and x > -5 else ('No' if pd.notna(x) else 'N/A')
        )

        # Extract PE ratio, sector PE, and face value from NSE quote API.
        # These are point-in-time values only valid TODAY — broadcasting them
        # to every historical row would contaminate any backtest over cached
        # data (a stock trading at PE=8 in 2024 but PE=35 today would show
        # PE=35 on its 2024 rows).
        df['pe_ratio'] = np.nan
        df['sector_pe'] = np.nan
        if nse_52w_data is not None and len(df) > 0:
            last_idx = df.index[-1]
            df.loc[last_idx, 'pe_ratio'] = nse_52w_data.get('pe_ratio', np.nan)
            df.loc[last_idx, 'sector_pe'] = nse_52w_data.get('sector_pe', np.nan)

        return df

    def calculate_relative_strength(self, df, nifty_df):
        """
        Calculate Mansfield Relative Strength of stock vs NIFTY 50.

        True Mansfield RS:
          Raw RS = (stock_close / nifty_close) * 100
          Mansfield RS = (raw_RS / 52-week_SMA_of_raw_RS - 1) * 100

        A positive reading means the stock is outperforming its OWN historical
        relationship to the index — it is gaining strength, not just strong in
        absolute terms. The 52-week (~260 trading day) smoothing is the
        standard Mansfield lookback for medium-term trend.

        Args:
            df: DataFrame with date and close columns
            nifty_df: DataFrame with date and close columns for NIFTY 50

        Returns:
            DataFrame with rs_ratio, rs_trend, rs_signal columns added
        """
        df = df.copy()

        if nifty_df is None or nifty_df.empty:
            df['rs_ratio'] = np.nan
            df['rs_trend'] = 'N/A'
            df['rs_signal'] = 'N/A'
            return df

        # Merge NIFTY close prices by date
        nifty_close = nifty_df[['date', 'close']].copy()
        nifty_close['date'] = pd.to_datetime(nifty_close['date']).dt.normalize()
        nifty_close = nifty_close.rename(columns={'close': 'nifty_close'})
        df['date'] = pd.to_datetime(df['date']).dt.normalize()
        df = df.merge(nifty_close, on='date', how='left')
        df['nifty_close'] = df['nifty_close'].ffill()

        # Step 1: raw RS = (stock_close / nifty_close) * 100
        df['raw_rs'] = np.where(
            pd.notna(df['nifty_close']) & (df['nifty_close'] > 0),
            (df['close'] / df['nifty_close']) * 100,
            np.nan
        )

        # Step 2: 52-week (~260 trading day) SMA of raw RS
        mansfield_period = 260
        df['raw_rs_ma'] = df['raw_rs'].rolling(
            # min_periods == window: every rs_ratio value is computed against a
            # FULL 52-week average. Allowing a half-window (the previous 130)
            # meant rows 130-259 were measured against a shorter baseline than
            # rows 260+, so the series was internally inconsistent — fine for
            # today's last row, wrong for any backtest that reads history.
            # Every cached ticker has 350+ rows, so this costs no live coverage.
            window=mansfield_period, min_periods=mansfield_period
        ).mean()

        # Step 3: Mansfield RS = (raw_RS / its_52W_SMA - 1) * 100
        df['rs_ratio'] = np.where(
            pd.notna(df['raw_rs_ma']) & (df['raw_rs_ma'] > 0),
            ((df['raw_rs'] / df['raw_rs_ma']) - 1) * 100,
            np.nan
        )

        # RS 10-week (~50 day) moving average for trend direction
        df['rs_ma'] = df['rs_ratio'].rolling(window=50, min_periods=25).mean()

        # RS trend: is RS rising or falling vs its own short-term MA?
        #
        # BAND MUST MATCH THE SCALE OF rs_ratio. The old +/-1 was calibrated for
        # the previous 52-day ROC-difference definition. Mansfield RS is a much
        # wider series, so +/-1 now sits below the 25th percentile of the normal
        # deviation and almost nothing reads 'Stable':
        #
        #   |rs_ratio - its 50d mean|:  p25 2.44   p50 5.36   p75 9.69   p90 15.73
        #     band +/-1 -> 10% Stable   (measured: Improving 60 / Weakening 36 / Stable 14)
        #     band +/-3 -> 30% Stable
        #     band +/-5 -> 47% Stable
        #
        # +/-3 keeps a meaningful middle without making the label sticky. Exposed
        # as config because it is scale-dependent: change the RS formula and this
        # has to move with it.
        band = self.rs_trend_band
        df['rs_trend'] = 'N/A'
        for i in range(len(df)):
            rs = df.iloc[i]['rs_ratio']
            rs_ma = df.iloc[i]['rs_ma']
            if pd.notna(rs) and pd.notna(rs_ma):
                if rs > rs_ma + band:
                    df.loc[i, 'rs_trend'] = 'Improving'
                elif rs < rs_ma - band:
                    df.loc[i, 'rs_trend'] = 'Weakening'
                else:
                    df.loc[i, 'rs_trend'] = 'Stable'

        # RS signal for screening
        df['rs_signal'] = df.apply(
            lambda row: 'Outperform' if pd.notna(row['rs_ratio']) and row['rs_ratio'] > 0
            else ('Underperform' if pd.notna(row['rs_ratio']) else 'N/A'),
            axis=1
        )

        # Clean up temp columns
        df = df.drop(columns=['nifty_close', 'raw_rs', 'raw_rs_ma', 'rs_ma'], errors='ignore')

        return df

    def calculate_price_delivery_divergence(self, df):
        """
        Detect divergence between price direction and delivery trend.
        Bullish divergence: price falling/flat but delivery rising → accumulation
        Bearish divergence: price rising but delivery falling → distribution

        Args:
            df: DataFrame with close and delivery_pct

        Returns:
            DataFrame with divergence columns added
        """
        df = df.copy()
        df['divergence'] = 'N/A'

        lookback = 20  # ~1 month

        for i in range(lookback, len(df)):
            # Price direction: compare current close to close 20 days ago
            price_now = df.iloc[i]['close']
            price_then = df.iloc[i - lookback]['close']

            if pd.isna(price_now) or pd.isna(price_then) or price_then == 0:
                continue

            price_roc = ((price_now - price_then) / price_then) * 100

            # Delivery direction: compare recent 10d avg vs previous 10d avg
            recent_deliv = df['delivery_pct'].iloc[i - 9:i + 1].mean()
            earlier_deliv = df['delivery_pct'].iloc[i - lookback:i - 10].mean()

            if pd.isna(recent_deliv) or pd.isna(earlier_deliv):
                continue

            deliv_change = recent_deliv - earlier_deliv

            # Bullish divergence: price down/flat (between -10% and +2%)
            # but delivery rising (>3%). A crash beyond -10% in 20 days is
            # genuine selling, not accumulation — no divergence story.
            if -10 <= price_roc < 2 and deliv_change > 3:
                df.loc[i, 'divergence'] = 'Bullish'
            # Bearish divergence: price up (>2%) but delivery falling (<-3%)
            elif price_roc > 2 and deliv_change < -3:
                df.loc[i, 'divergence'] = 'Bearish'
            else:
                df.loc[i, 'divergence'] = 'None'

        return df

    def calculate_squeeze(self, df):
        """
        Detect consolidation squeeze using ATR contraction.
        When 10-day ATR / 50-day ATR drops below threshold, the stock is coiling
        for a potential breakout.

        Args:
            df: DataFrame with close prices

        Returns:
            DataFrame with squeeze columns added
        """
        df = df.copy()

        # Calculate True Range using HIGH/LOW/prev-close when available,
        # falling back to close-to-close for older cached data without
        # high/low columns. This gives a proper Wilder-style TR that
        # captures intraday volatility rather than just close-to-close gaps.
        if 'high' in df.columns and 'low' in df.columns:
            prev_close = df['close'].shift(1)
            tr1 = df['high'] - df['low']
            tr2 = (df['high'] - prev_close).abs()
            tr3 = (df['low'] - prev_close).abs()
            # max across the three components, row-wise
            df['tr'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        else:
            df['tr'] = df['close'].diff().abs()

        # ATR 10 and ATR 50
        df['atr_10'] = df['tr'].rolling(window=10, min_periods=10).mean()
        df['atr_50'] = df['tr'].rolling(window=50, min_periods=50).mean()

        # Squeeze ratio
        df['squeeze_ratio'] = np.where(
            pd.notna(df['atr_50']) & (df['atr_50'] > 0),
            df['atr_10'] / df['atr_50'],
            np.nan
        )

        # Squeeze signal
        df['squeeze'] = df['squeeze_ratio'].apply(
            lambda x: 'Coiling' if pd.notna(x) and x < 0.5
            else ('Tight' if pd.notna(x) and x < 0.75
                  else ('Normal' if pd.notna(x) else 'N/A'))
        )

        # Clean up temp columns
        df = df.drop(columns=['tr', 'atr_10', 'atr_50'], errors='ignore')

        return df

    def calculate_multi_timeframe_roc(self, df):
        """
        Calculate rate of change across 1-week, 1-month, and 3-month timeframes.

        Args:
            df: DataFrame with close prices

        Returns:
            DataFrame with roc_1w, roc_1m, roc_3m columns added
        """
        df = df.copy()

        # 1-Week ROC (5 trading days)
        df['roc_1w'] = np.where(
            (df.index >= 5) & (df['close'].shift(5) > 0),
            ((df['close'] - df['close'].shift(5)) / df['close'].shift(5)) * 100,
            np.nan
        )

        # 1-Month ROC (22 trading days)
        df['roc_1m'] = np.where(
            (df.index >= 22) & (df['close'].shift(22) > 0),
            ((df['close'] - df['close'].shift(22)) / df['close'].shift(22)) * 100,
            np.nan
        )

        # 3-Month ROC (66 trading days)
        df['roc_3m'] = np.where(
            (df.index >= 66) & (df['close'].shift(66) > 0),
            ((df['close'] - df['close'].shift(66)) / df['close'].shift(66)) * 100,
            np.nan
        )

        # Momentum alignment signal
        df['momentum_align'] = 'N/A'
        for i in range(len(df)):
            r1w = df.iloc[i]['roc_1w']
            r1m = df.iloc[i]['roc_1m']
            r3m = df.iloc[i]['roc_3m']

            if pd.isna(r1w) or pd.isna(r1m) or pd.isna(r3m):
                continue

            if r1w > 0 and r1m > 0 and r3m > 0:
                df.loc[i, 'momentum_align'] = 'All Up'
            elif r1w < 0 and r1m < 0 and r3m < 0:
                df.loc[i, 'momentum_align'] = 'All Down'
            elif r1w > 0 and r1m > 0 and r3m < 0:
                df.loc[i, 'momentum_align'] = 'Reversing Up'
            elif r1w < 0 and r1m > 0 and r3m > 0:
                df.loc[i, 'momentum_align'] = 'Pullback'
            elif r1w < 0 and r1m < 0 and r3m > 0:
                df.loc[i, 'momentum_align'] = 'Breaking Down'
            else:
                df.loc[i, 'momentum_align'] = 'Mixed'

        return df

    def calculate_exit_signals(self, df):
        """
        Calculate sell signals for distribution and trend reversal detection

        Args:
            df: DataFrame with all calculated fields

        Returns:
            DataFrame with exit signal columns added
        """
        df = df.copy()

        # 1. Price vs 10-day MA (Short-term weakness)
        df['ma_10d'] = df['close'].rolling(window=10, min_periods=5).mean()
        df['price_vs_10ma'] = df.apply(
            lambda row: 'Below' if pd.notna(row['ma_10d']) and row['close'] < row['ma_10d']
            else ('Above' if pd.notna(row['ma_10d']) else 'N/A'),
            axis=1
        )

        # 2. Delivery Momentum (Declining delivery = Distribution)
        # Compare last 10 days avg vs previous 10 days avg
        df['deliv_momentum'] = 'N/A'
        for i in range(20, len(df)):
            recent_10 = df['delivery_pct'].iloc[i-9:i+1].mean()
            previous_10 = df['delivery_pct'].iloc[i-19:i-9].mean()

            if pd.notna(recent_10) and pd.notna(previous_10):
                diff = recent_10 - previous_10
                if diff < -5:  # Significant decline
                    df.loc[i, 'deliv_momentum'] = 'Declining'
                elif diff > 5:  # Significant increase
                    df.loc[i, 'deliv_momentum'] = 'Rising'
                else:
                    df.loc[i, 'deliv_momentum'] = 'Stable'

        # 3. Volume Spike on Down Days (Distribution pattern)
        # Only flag meaningful drops (>1%) to avoid noise from trivial declines
        # MUST run before Distribution Alert (step 4), which reads vol_spike_down.
        df['vol_spike_down'] = 'No'
        for i in range(1, len(df)):
            prev_close = df.iloc[i-1]['close']
            curr_close = df.iloc[i]['close']
            is_high_vol = df.iloc[i].get('is_high_vol', 'No')

            if pd.notna(prev_close) and prev_close > 0:
                price_change_pct = ((curr_close - prev_close) / prev_close) * 100
                # High volume on significant down day (>1% drop) = potential distribution
                if price_change_pct < -1 and is_high_vol == 'Yes':
                    df.loc[i, 'vol_spike_down'] = 'Yes'

        # 4. Distribution Alert (detects institutions selling into strength OR
        # continuing to distribute after the breakdown)
        df['distribution_alert'] = 'No'
        for i in range(50, len(df)):  # Need sufficient history
            near_high = df.iloc[i].get('near_52w_high', 'N/A')
            deliv_momentum = df.iloc[i]['deliv_momentum']
            stage = df.iloc[i].get('stage', 'N/A')
            vol_spike = df.iloc[i].get('vol_spike_down', 'No')

            # Pattern A: Classic distribution — near highs with declining
            # delivery (institutions selling into retail buying).
            if near_high == 'Yes' and deliv_momentum == 'Declining':
                df.loc[i, 'distribution_alert'] = 'Yes'

            # Pattern B: Post-breakdown distribution — stock already in Stage
            # 3/4 with delivery momentum still declining AND volume spikes on
            # down days. This catches distribution that started below 52W highs
            # (e.g. after a failed rally) and would have been invisible before.
            elif (stage in ['Stage 3', 'Stage 4']
                  and deliv_momentum == 'Declining'
                  and vol_spike == 'Yes'):
                df.loc[i, 'distribution_alert'] = 'Yes'

        # 5. Trend Break Detection (Lower Highs)
        # 3% threshold over a 20+20 day window is ~5% over 10 days — noisy
        # intra-Stage-2 consolidation routinely triggers this and the now-removed
        # Exit Score counted it as a full factor. 5% reduces the false-positive
        # rate while still catching genuine lower-high breakouts.
        df['trend_break'] = 'Neutral'
        for i in range(20, len(df)):
            # Get recent highs (last 20 days)
            recent_20 = df['close'].iloc[max(0, i-19):i+1]

            if len(recent_20) >= 20:
                # Current high
                current_high = recent_20.iloc[-10:].max()
                # Previous high
                previous_high = recent_20.iloc[:10].max()

                if pd.notna(current_high) and pd.notna(previous_high):
                    if current_high > previous_high * 1.02:  # 2% threshold
                        df.loc[i, 'trend_break'] = 'Higher High'
                    elif current_high < previous_high * 0.95:  # 5% threshold (was 2%)
                        df.loc[i, 'trend_break'] = 'Lower High'

        # 6. Stage 3 Alert (Entered distribution phase)
        # "Exit Signal" persists for a window of days after the transition,
        # not just the single transition day where stage flips to Stage 3.
        STAGE3_ALERT_WINDOW = 10  # trading days
        df['stage_3_alert'] = '-'
        days_since_transition = 0
        observed_transition = False  # only fire after an actual Stage 2→3 transition
        for i in range(1, len(df)):
            current_stage = df.iloc[i].get('stage', 'N/A')
            previous_stage = df.iloc[i-1].get('stage', 'N/A')

            if current_stage == 'Stage 3' and previous_stage in ['Stage 2', 'Stage 2 (Pullback)']:
                # Fresh transition into Stage 3 — start the alert window
                days_since_transition = 0
                observed_transition = True
                df.loc[i, 'stage_3_alert'] = 'Exit Signal'
            elif (current_stage == 'Stage 3' and observed_transition
                  and days_since_transition < STAGE3_ALERT_WINDOW):
                days_since_transition += 1
                df.loc[i, 'stage_3_alert'] = 'Exit Signal'
            elif current_stage == 'Stage 3':
                days_since_transition += 1
                df.loc[i, 'stage_3_alert'] = 'Stage 3'
            else:
                days_since_transition = 0
                if current_stage != 'Stage 3':
                    observed_transition = False

        # 7. Cross Below 30WMA (Primary Weinstein sell signal)
        df['cross_below_alert'] = '-'
        for i in range(len(df)):
            cross_below = df.iloc[i].get('cross_below', False)
            cross_below_conf = df.iloc[i].get('cross_below_confirmed', False)
            if cross_below_conf:
                df.loc[i, 'cross_below_alert'] = 'SELL (Vol)'  # Volume-confirmed = strong
            elif cross_below:
                df.loc[i, 'cross_below_alert'] = 'SELL'  # Unconfirmed = still a warning

        return df

    def calculate_exit_score(self, df):
        """
        REMOVED — Exit Score (0-10) has been retired.
        The composite score was a weighted black box with the same problems
        as the Accumulation Score: equal weighting across factors, a -0.95%
        Lower High on a 20-day window counted the same as a Stage 3 transition,
        and the single number hid which risk was actually firing.

        The replacement is the individual exit-signal columns already rendered
        on the Report sheet — Cross Below WMA, Distribution Alert, Stage 3
        Alert, Trend Break, Deliv Momentum, Vol Spike Down — read together
        rather than collapsed into one opaque number.

        Kept as a no-op stub so callers don't break.
        """
        df = df.copy()
        df['exit_score'] = 0
        return df

    def calculate_stage1_alert(self, df):
        """
        Calculate Stage 1 Alert - identifies stocks in basing phase showing exceptional volume activity
        These are potential turnaround/accumulation candidates

        Args:
            df: DataFrame with all calculated fields

        Returns:
            DataFrame with stage1_alert and stage1_strength added
        """
        df = df.copy()
        df['stage1_alert'] = 'No'
        df['stage1_strength'] = 0

        for i in range(len(df)):
            stage = df.iloc[i].get('stage', 'N/A')

            # Only evaluate if in Stage 1
            if stage != 'Stage 1':
                continue

            strength = 0

            # Criterion 1: Recent volume activity (5+ out of last 10 days)
            start_idx = max(0, i - 9)
            recent_10 = df.iloc[start_idx:i + 1]
            high_vol_days = (recent_10['is_high_vol'] == 'Yes').sum()
            if high_vol_days >= 5:
                strength += 1

            # Criterion 2: Recent delivery average ≥45% (lower threshold for Stage 1)
            deliv_avg_10d = df.iloc[i].get('deliv_avg_10d')
            if pd.notna(deliv_avg_10d) and deliv_avg_10d >= 45:
                strength += 1

            # Criterion 3: Volume-backed delivery in last 15 days (≥50% + HighVol)
            # Check last 15 days for meaningful accumulation
            start_idx_15 = max(0, i - 14)
            recent_15 = df.iloc[start_idx_15:i + 1]
            highvol_highdeliv = recent_15.apply(
                lambda row: 1 if (pd.notna(row['delivery_pct']) and row['delivery_pct'] >= 50
                                 and row.get('is_high_vol') == 'Yes') else 0,
                axis=1
            ).sum()
            if highvol_highdeliv >= 6:  # At least 40% of last 15 days
                strength += 1

            # Criterion 4: Not making new lows (price > 52W low by at least 5%)
            low_52w_pct = df.iloc[i].get('52w_low_pct')
            if pd.notna(low_52w_pct) and low_52w_pct > 5:
                strength += 1

            # Criterion 5: RSI neutral — some buying interest, not yet extended.
            #
            # 'Overbought' used to score here too, on the reasoning "not deeply
            # oversold". But RSI above 70 on a stock that is by definition still
            # BASING (below a flat 30WMA) describes a sharp bounce inside the
            # base, not quiet accumulation — the opposite of the Stage 1 setup
            # this alert is meant to find. Neutral is the condition that
            # actually supports the thesis.
            rsi_signal = df.iloc[i].get('rsi_signal', 'N/A')
            if rsi_signal == 'Neutral':
                strength += 1

            df.loc[i, 'stage1_strength'] = strength

            # Alert if strength >= 3 (at least 3 out of 5 criteria met)
            if strength >= 3:
                df.loc[i, 'stage1_alert'] = 'Yes'

        return df

    def calculate_200dma(self, df):
        """
        Calculate 200-day Simple Moving Average and price position relative to it.
        Every institutional fund globally uses this as a long-term trend filter.

        Args:
            df: DataFrame with close prices

        Returns:
            DataFrame with dma_200 and price_vs_200dma columns added
        """
        df = df.copy()

        # 200-day SMA
        df['dma_200'] = df['close'].rolling(window=200, min_periods=100).mean()

        # Price position relative to 200 DMA (percentage)
        df['price_vs_200dma'] = np.where(
            pd.notna(df['dma_200']) & (df['dma_200'] > 0),
            ((df['close'] - df['dma_200']) / df['dma_200'] * 100),
            np.nan
        )

        return df

    def calculate_base_levels(self, df):
        """
        Identify the trading base (consolidation range) and derive the two
        levels a Weinstein entry actually needs: where to buy, and where to
        get out.

        WHY A SKIP WINDOW: the pivot is measured over weeks
        [-pivot_lookback_weeks .. -pivot_skip_weeks], i.e. the recent
        `pivot_skip_weeks` are EXCLUDED. Without that, a stock that has just
        broken out redefines its own pivot to the breakout high, and
        'Dist to Pivot' collapses to ~0% for every name that has already
        moved. Skipping the last few weeks keeps the pivot anchored to the
        pre-breakout resistance line, which is the level Weinstein buys
        through and the number that tells you whether you are early or
        chasing.

        STOP RULE (Weinstein): initial stop sits below the base; as the stock
        advances the 30WMA rises and becomes the binding line, which is the
        stop you trail. Taking max(base_low, 30WMA) reproduces that
        automatically — early on the base low is higher, later the WMA is.

        Adds:
          pivot_price          — resistance line of the base (buy trigger)
          dist_to_pivot_pct    — <0 not yet triggered, >0 already extended
          base_length_weeks    — weeks price stayed inside the base
          base_depth_pct       — base height as % of pivot (tight = better)
          stop_level           — max(base low, 30WMA) less a buffer
          dist_to_stop_pct     — how much room to the stop, as % of price
        """
        df = df.copy()
        for col in ('pivot_price', 'dist_to_pivot_pct', 'base_depth_pct',
                    'stop_level', 'dist_to_stop_pct'):
            df[col] = np.nan
        df['base_length_weeks'] = 0

        if df.empty or 'week' not in df.columns:
            return df

        lookback_w = self.pivot_lookback_weeks
        skip_w = self.pivot_skip_weeks
        max_depth = self.base_max_depth_pct
        buffer = self.stop_buffer_pct / 100.0
        fallback = self.fallback_stop_pct / 100.0

        # Weekly OHLC. Fall back to close when intraday high/low are absent
        # (older cache files) so the levels still compute, just less precisely.
        high_src = 'high' if 'high' in df.columns else 'close'
        low_src = 'low' if 'low' in df.columns else 'close'
        weekly = df.groupby('week').agg(
            w_high=(high_src, 'max'),
            w_low=(low_src, 'min'),
        ).reset_index()

        # Week index per daily row, so each row uses only weeks that had
        # already completed as of that row (no look-ahead).
        week_pos = {w: i for i, w in enumerate(weekly['week'])}
        highs = weekly['w_high'].to_numpy()
        lows = weekly['w_low'].to_numpy()

        for i in range(len(df)):
            wi = week_pos.get(df.iloc[i]['week'])
            if wi is None:
                continue

            end = wi - skip_w            # exclusive upper bound of the base window
            start = max(0, end - lookback_w)
            if end - start < self.base_min_weeks:
                continue

            win_high = highs[start:end]
            win_low = lows[start:end]
            if len(win_high) == 0 or not np.isfinite(win_high).any():
                continue

            pivot = float(np.nanmax(win_high))
            if not np.isfinite(pivot) or pivot <= 0:
                continue

            # Walk back from the end of the window counting weeks that stayed
            # inside the band [pivot*(1-max_depth), pivot]. That run length is
            # the base; where it stops is the base floor.
            floor = pivot * (1.0 - max_depth / 100.0)
            length = 0
            base_low = np.inf
            for k in range(end - 1, start - 1, -1):
                if np.isfinite(lows[k]) and lows[k] >= floor and np.isfinite(highs[k]) and highs[k] <= pivot * 1.001:
                    length += 1
                    base_low = min(base_low, float(lows[k]))
                else:
                    break

            if length < self.base_min_weeks or not np.isfinite(base_low):
                continue

            close = df.iloc[i]['close']
            if pd.isna(close) or close <= 0:
                continue

            df.loc[i, 'pivot_price'] = round(pivot, 2)
            df.loc[i, 'dist_to_pivot_pct'] = ((close - pivot) / pivot) * 100
            df.loc[i, 'base_length_weeks'] = length
            df.loc[i, 'base_depth_pct'] = ((pivot - base_low) / pivot) * 100

            # Stop: whichever of the base floor / 30WMA is higher, less buffer.
            wma = df.iloc[i].get('weekly_wma30')
            anchor = base_low
            if pd.notna(wma) and wma > anchor:
                anchor = float(wma)
            stop = anchor * (1.0 - buffer)

            # A stop must sit below the current price. For a Stage 2 pullback
            # the 30WMA can be above price, which would otherwise produce a
            # nonsensical stop above the entry — fall back to a fixed
            # percentage below price in that case.
            if stop >= close:
                stop = min(base_low * (1.0 - buffer), close * (1.0 - fallback))
            if stop >= close:
                stop = close * (1.0 - fallback)

            df.loc[i, 'stop_level'] = round(stop, 2)
            df.loc[i, 'dist_to_stop_pct'] = ((close - stop) / close) * 100

        return df

    def calculate_accumulation_score(self, df):
        """
        REMOVED — Accumulation Score (0-7) has been retired.
        The composite score was a weighted black box that could hide which
        specific factor was driving the rating, and with equal weighting across
        factors it penalized pullback entries (a -1% monthly ROC got zero for
        Factor 1 even when every other signal was strong).

        The replacement is holistic: the Report sheet shows all the raw data
        (delivery %, volume, RS vs NIFTY, momentum alignment, divergence,
        squeeze, etc.) side by side so the analyst can see the full picture
        rather than relying on a single opaque number. The Shortlist ranks on
        RS vs NIFTY plus a bonus for fresh cross-above / Triple Confirm signals
        — simpler, transparent, and aligned with Weinstein's core rule of
        buying market leaders.

        Kept as a no-op stub so callers don't break.
        """
        df = df.copy()
        df['accum_score'] = 0
        return df

    def process_ticker_data(self, df, nse_52w_data=None, nifty_df=None,
                            promoter_data=None, financial_data=None):
        """
        Process all calculations for a ticker

        Args:
            df: Raw DataFrame with date, close, traded_quantity, delivery_quantity
            nse_52w_data: Optional dict with NSE authoritative 52W data + PE data
            nifty_df: Optional DataFrame with NIFTY 50 data for relative strength
            promoter_data: Optional dict with promoter holding data
            financial_data: Optional dict with quarterly financial results

        Returns:
            Processed DataFrame with all calculated fields
        """
        if df.empty:
            return df

        # Degrade gracefully on frames that lack the volume/delivery columns
        # (index series like NIFTY_50 carry only date+close). Previously these
        # raised a bare KeyError deep inside calculate_delivery_percentage,
        # which told the caller nothing about what was actually missing.
        df = df.copy()
        for _req in ('traded_quantity', 'delivery_quantity'):
            if _req not in df.columns:
                logger.warning(f"'{_req}' missing - filling with NaN. Delivery/volume "
                               f"signals will be N/A for this series.")
                df[_req] = np.nan
        if 'close' not in df.columns:
            logger.error("'close' column missing - cannot process this series")
            return df

        # Sort by date, and DE-DUPLICATE defensively.
        #
        # merge_new_data() already de-duplicates, but that is a single line of
        # defence for something quietly destructive: a duplicated trading day
        # halves the real span of every rolling window. Measured on RELIANCE
        # with its history fed in twice — 52w_high 1592 -> 1464 (-8%),
        # dma_200 1398 -> 1327, and RSI 41.5 -> 31.6, which is enough to flip
        # an Oversold classification. Nothing downstream would notice.
        #
        # Duplicates can still arrive from a hand-edited cache file or two
        # concurrent runs writing the same ticker, so guard here too and say
        # so out loud rather than silently absorbing them.
        df = df.sort_values('date')
        if 'date' in df.columns:
            n_before = len(df)
            df = df.drop_duplicates(subset=['date'], keep='last')
            n_dropped = n_before - len(df)
            if n_dropped:
                logger.warning(
                    f"Dropped {n_dropped} duplicate trading day(s) before calculation "
                    f"({n_before} -> {len(df)} rows). Check the cache file for this ticker."
                )
        df = df.reset_index(drop=True)

        # Detect corporate actions (splits/bonuses) — must run before any
        # technical indicator that depends on historically comparable prices
        df = self.detect_corporate_actions(df)

        # ...then actually FIX them, so every indicator below sees a single,
        # continuous price series. Runs immediately after detection and before
        # anything reads `close`. In-memory only; the cache stays raw.
        df = self.apply_corporate_action_adjustment(df)

        # Calculate delivery percentage
        df = self.calculate_delivery_percentage(df)

        # Calculate volume MA and signals
        df = self.calculate_volume_ma(df)

        # Calculate weekly WMA and crosses
        df = self.calculate_weekly_wma(df)

        # Add color band (considering both delivery % and volume)
        def get_color_with_volume(row):
            delivery_pct = row['delivery_pct']
            is_high_vol = row['is_high_vol']

            # Low volume days → white (not meaningful)
            if is_high_vol == 'No':
                return 'white'

            # High volume + Low delivery (<40%) → cream (accumulation phase)
            if is_high_vol == 'Yes' and pd.notna(delivery_pct) and delivery_pct < 40:
                return 'cream'

            # High volume + Good delivery → standard color bands
            if is_high_vol == 'Yes':
                return self.get_delivery_color_band(delivery_pct)

            return 'white'

        df['color_band'] = df.apply(get_color_with_volume, axis=1)

        # Calculate Weinstein metrics
        df = self.calculate_weinstein_metrics(df)

        # Calculate Triple Confirm signal (price > 30WMA + high volume + high delivery)
        df = self.calculate_triple_confirm(df)

        # Calculate delivery trends
        df = self.calculate_delivery_trends(df)

        # Calculate RSI (Relative Strength Index)
        df = self.calculate_rsi(df, period=14)

        # Calculate 52-week high/low metrics
        df = self.calculate_52week_metrics(df, nse_52w_data=nse_52w_data)

        # Calculate relative strength vs NIFTY 50
        df = self.calculate_relative_strength(df, nifty_df)

        # Calculate price-delivery divergence
        df = self.calculate_price_delivery_divergence(df)

        # Calculate consolidation squeeze
        df = self.calculate_squeeze(df)

        # Calculate multi-timeframe momentum
        df = self.calculate_multi_timeframe_roc(df)

        # Calculate 200 DMA
        df = self.calculate_200dma(df)

        # Base / pivot / stop levels (needs weekly_wma30 from calculate_weekly_wma)
        df = self.calculate_base_levels(df)

        # Calculate accumulation score
        df = self.calculate_accumulation_score(df)

        # Calculate exit signals (sell signals)
        df = self.calculate_exit_signals(df)

        # Calculate exit score
        df = self.calculate_exit_score(df)

        # Calculate Stage 1 Alert
        df = self.calculate_stage1_alert(df)

        # Add promoter holding data (from NSE API)
        if promoter_data is not None:
            df['promoter_pct'] = promoter_data.get('promoter_pct', np.nan)
            df['promoter_change'] = promoter_data.get('promoter_change', np.nan)
        else:
            df['promoter_pct'] = np.nan
            df['promoter_change'] = np.nan

        # Add quarterly financial results (from NSE API)
        if financial_data is not None:
            df['profit_growth_yoy'] = financial_data.get('profit_growth_yoy', np.nan)
            df['latest_quarter'] = financial_data.get('quarter', '')
        else:
            df['profit_growth_yoy'] = np.nan
            df['latest_quarter'] = ''

        logger.info(f"Processed {len(df)} days of data")
        return df
