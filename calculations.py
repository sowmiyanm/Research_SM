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
        self.weekly_wma_period = config.get('weekly_wma_period', 30)
        self.weekstart_day = config.get('weekstart_day', 'Monday')

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

        # Check if current volume > MA
        df['is_high_vol'] = df.apply(
            lambda row: 'Yes' if pd.notna(row['vol_ma36']) and row['traded_quantity'] > row['vol_ma36']
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
            DataFrame with weekly_wma30 and weekstart_cross columns
        """
        df = df.copy()
        df['date'] = pd.to_datetime(df['date'])

        # Determine week ending date (last trading day of each week)
        # Week starts on Monday (or configured day)
        weekday_map = {
            'Monday': 0, 'Tuesday': 1, 'Wednesday': 2,
            'Thursday': 3, 'Friday': 4, 'Saturday': 5, 'Sunday': 6
        }
        weekstart = weekday_map.get(self.weekstart_day, 0)

        # Create week identifier
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

        # Calculate weeks above/below 30WMA (consecutive count)
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

        # Merge back to daily data
        df = df.merge(
            weekly_data[['week', 'weekly_wma30', 'cross_above', 'cross_below',
                         'weeks_above_wma', 'weeks_below_wma']],
            on='week',
            how='left'
        )

        # Calculate weekly average volume ratio for volume-confirmed cross detection
        # Group daily vol_ratio by week and compute mean
        if 'vol_ratio' in df.columns:
            weekly_vol = df.groupby('week')['vol_ratio'].mean().reset_index()
            weekly_vol.columns = ['week', 'week_avg_vol_ratio']
            df = df.merge(weekly_vol, on='week', how='left')

            # Volume-confirmed cross: cross occurred AND week's avg volume > 1.0x MA
            df['cross_above_confirmed'] = df['cross_above'] & (df['week_avg_vol_ratio'] > 1.0)
            df['cross_below_confirmed'] = df['cross_below'] & (df['week_avg_vol_ratio'] > 1.0)
        else:
            df['week_avg_vol_ratio'] = np.nan
            df['cross_above_confirmed'] = df['cross_above']
            df['cross_below_confirmed'] = df['cross_below']

        # Mark first trading day of each week (handles Monday holidays correctly)
        df['is_weekstart'] = False
        for week_val in df['week'].unique():
            week_mask = df['week'] == week_val
            first_idx = df[week_mask].index[0]
            df.loc[first_idx, 'is_weekstart'] = True

        # Weekstart cross signal (show on first trading day of week when cross occurred)
        df['weekstart_cross'] = df['is_weekstart'] & df['cross_above']

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
        # Get last N days
        recent_data = df.tail(evaluation_days)

        # Count excluding blue and white (delivery >= 50%)
        count_excl_blue = recent_data['delivery_pct'].apply(
            lambda x: 1 if pd.notna(x) and x >= 50 else 0
        ).sum()

        # Count including blue, excluding white (delivery >= 40%)
        count_incl_blue = recent_data['delivery_pct'].apply(
            lambda x: 1 if pd.notna(x) and x >= 40 else 0
        ).sum()

        # Count with high volume (delivery >= 50% AND volume > MA) - 45 days
        count_excl_blue_highvol = recent_data.apply(
            lambda row: 1 if (pd.notna(row['delivery_pct']) and row['delivery_pct'] >= 50
                             and row.get('is_high_vol') == 'Yes') else 0,
            axis=1
        ).sum()

        # Count with high volume (delivery >= 40% AND volume > MA) - 45 days
        count_incl_blue_highvol = recent_data.apply(
            lambda row: 1 if (pd.notna(row['delivery_pct']) and row['delivery_pct'] >= 40
                             and row.get('is_high_vol') == 'Yes') else 0,
            axis=1
        ).sum()

        # NEW: Recent 15-day count (delivery >= 50% AND volume > MA)
        recent_15 = df.tail(15)
        count_excl_blue_highvol_15d = recent_15.apply(
            lambda row: 1 if (pd.notna(row['delivery_pct']) and row['delivery_pct'] >= 50
                             and row.get('is_high_vol') == 'Yes') else 0,
            axis=1
        ).sum()

        # NEW: Recent 20-day count (delivery >= 50% AND volume > MA)
        recent_20 = df.tail(20)
        count_excl_blue_highvol_20d = recent_20.apply(
            lambda row: 1 if (pd.notna(row['delivery_pct']) and row['delivery_pct'] >= 50
                             and row.get('is_high_vol') == 'Yes') else 0,
            axis=1
        ).sum()

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

        # Calculate 30WMA slope (compare current vs 4 weeks ago)
        df['wma_slope'] = 'N/A'
        for i in range(20, len(df)):  # Need at least ~20 trading days (4 weeks)
            current_wma = df.iloc[i]['weekly_wma30']
            past_wma = df.iloc[i-20]['weekly_wma30']

            if pd.notna(current_wma) and pd.notna(past_wma):
                slope_pct = ((current_wma - past_wma) / past_wma) * 100

                if slope_pct > 2:
                    df.loc[i, 'wma_slope'] = 'Rising'
                elif slope_pct < -2:
                    df.loc[i, 'wma_slope'] = 'Falling'
                else:
                    df.loc[i, 'wma_slope'] = 'Flat'

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
                elif price_vs >= 0 and slope in ['Flat', 'Falling']:
                    df.loc[i, 'stage'] = 'Stage 3'  # Distribution/Topping
                else:
                    df.loc[i, 'stage'] = 'Stage 1'  # Default to accumulation

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

        # Add RSI signal classification
        df['rsi_signal'] = df['rsi'].apply(
            lambda x: 'Overbought' if pd.notna(x) and x > 70
            else ('Oversold' if pd.notna(x) and x < 30
                  else ('Neutral' if pd.notna(x) else 'N/A'))
        )

        return df

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

        if nse_52w_data is not None:
            # Use authoritative NSE 52W data
            df['52w_high'] = nse_52w_data['52w_high']
            df['52w_low'] = nse_52w_data['52w_low']
            df['52w_high_date'] = nse_52w_data.get('52w_high_date', '')
            df['52w_low_date'] = nse_52w_data.get('52w_low_date', '')
        else:
            # Fallback: rolling 252-day calculation
            df['52w_high'] = df['close'].rolling(window=252, min_periods=126).max()
            df['52w_low'] = df['close'].rolling(window=252, min_periods=126).min()
            df['52w_high_date'] = ''
            df['52w_low_date'] = ''

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

        # Extract PE ratio and related fundamentals (from NSE quote API)
        if nse_52w_data is not None:
            df['pe_ratio'] = nse_52w_data.get('pe_ratio', np.nan)
            df['sector_pe'] = nse_52w_data.get('sector_pe', np.nan)
            df['face_value'] = nse_52w_data.get('face_value', np.nan)
        else:
            df['pe_ratio'] = np.nan
            df['sector_pe'] = np.nan
            df['face_value'] = np.nan

        return df

    def calculate_relative_strength(self, df, nifty_df):
        """
        Calculate relative strength of stock vs NIFTY 50

        Mansfield Relative Strength: (stock_close / nifty_close) normalized,
        then compare current RS to its own moving average.

        Args:
            df: DataFrame with date and close columns
            nifty_df: DataFrame with date and close columns for NIFTY 50

        Returns:
            DataFrame with rs_ratio, rs_trend columns added
        """
        df = df.copy()

        if nifty_df is None or nifty_df.empty:
            df['rs_ratio'] = np.nan
            df['rs_trend'] = 'N/A'
            df['rs_signal'] = 'N/A'
            return df

        # Merge NIFTY close prices by date (normalize to date-only to avoid time mismatch)
        nifty_close = nifty_df[['date', 'close']].copy()
        nifty_close['date'] = pd.to_datetime(nifty_close['date']).dt.normalize()
        nifty_close = nifty_close.rename(columns={'close': 'nifty_close'})
        df['date'] = pd.to_datetime(df['date']).dt.normalize()
        df = df.merge(nifty_close, on='date', how='left')

        # Forward-fill NIFTY prices for any missing dates
        df['nifty_close'] = df['nifty_close'].ffill()

        # RS ratio: stock performance / NIFTY performance (normalized to 100)
        # Using rolling 52-day (~2.5 month) rate of change comparison
        lookback = 52
        if len(df) >= lookback:
            stock_roc = df['close'].pct_change(lookback)
            nifty_roc = df['nifty_close'].pct_change(lookback)
            # RS = stock ROC - nifty ROC (positive = outperforming)
            df['rs_ratio'] = (stock_roc - nifty_roc) * 100
        else:
            df['rs_ratio'] = np.nan

        # RS moving average (10-week ≈ 50 trading days) for trend
        df['rs_ma'] = df['rs_ratio'].rolling(window=50, min_periods=25).mean()

        # RS trend: is RS rising or falling vs its own MA?
        df['rs_trend'] = 'N/A'
        for i in range(len(df)):
            rs = df.iloc[i]['rs_ratio']
            rs_ma = df.iloc[i]['rs_ma']
            if pd.notna(rs) and pd.notna(rs_ma):
                if rs > rs_ma + 1:
                    df.loc[i, 'rs_trend'] = 'Improving'
                elif rs < rs_ma - 1:
                    df.loc[i, 'rs_trend'] = 'Weakening'
                else:
                    df.loc[i, 'rs_trend'] = 'Stable'

        # RS signal for screening
        df['rs_signal'] = df.apply(
            lambda row: 'Outperform' if pd.notna(row['rs_ratio']) and row['rs_ratio'] > 0
            else ('Underperform' if pd.notna(row['rs_ratio']) else 'N/A'),
            axis=1
        )

        # Clean up temp column
        df = df.drop(columns=['nifty_close', 'rs_ma'], errors='ignore')

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

            # Bullish divergence: price down/flat (<2%) but delivery rising (>3%)
            if price_roc < 2 and deliv_change > 3:
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

        # Calculate True Range (using close-to-close for simplicity since we don't have high/low)
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

        # 3. Distribution Alert (High price + Falling delivery)
        df['distribution_alert'] = 'No'
        for i in range(50, len(df)):  # Need sufficient history
            # Check if price is near 52W high
            near_high = df.iloc[i].get('near_52w_high', 'N/A')
            deliv_momentum = df.iloc[i]['deliv_momentum']

            # Distribution = Near high + Declining delivery
            if near_high == 'Yes' and deliv_momentum == 'Declining':
                df.loc[i, 'distribution_alert'] = 'Yes'

        # 4. Trend Break Detection (Lower Highs)
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
                    elif current_high < previous_high * 0.98:
                        df.loc[i, 'trend_break'] = 'Lower High'

        # 5. Stage 3 Alert (Entered distribution phase)
        df['stage_3_alert'] = '-'
        for i in range(1, len(df)):
            current_stage = df.iloc[i].get('stage', 'N/A')
            previous_stage = df.iloc[i-1].get('stage', 'N/A')

            # Alert if moving from Stage 2 to Stage 3
            if current_stage == 'Stage 3' and previous_stage == 'Stage 2':
                df.loc[i, 'stage_3_alert'] = 'Exit Signal'
            elif current_stage == 'Stage 3':
                df.loc[i, 'stage_3_alert'] = 'Stage 3'

        # 6. Volume Spike on Down Days (Distribution pattern)
        # Only flag meaningful drops (>1%) to avoid noise from trivial declines
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
        Calculate exit score (0-7 based on sell signals)
        Higher score = Stronger sell signal

        Args:
            df: DataFrame with exit signals

        Returns:
            DataFrame with exit_score added
        """
        df = df.copy()
        df['exit_score'] = 0

        for i in range(len(df)):
            score = 0

            # Factor 1: Stage 3 or 4 (distribution/downtrend)
            stage = df.iloc[i].get('stage', 'N/A')
            if stage in ['Stage 3', 'Stage 4']:
                score += 1

            # Factor 2: Distribution Alert
            if df.iloc[i].get('distribution_alert', 'No') == 'Yes':
                score += 1

            # Factor 3: Delivery Momentum Declining
            if df.iloc[i].get('deliv_momentum', 'N/A') == 'Declining':
                score += 1

            # Factor 4: Price below 10MA
            if df.iloc[i].get('price_vs_10ma', 'N/A') == 'Below':
                score += 1

            # Factor 5: Lower High (trend breaking)
            if df.iloc[i].get('trend_break', 'Neutral') == 'Lower High':
                score += 1

            # Factor 6: RSI Overbought (only bearish in Stage 3/4, not during Stage 2 uptrends)
            rsi_signal = df.iloc[i].get('rsi_signal', 'N/A')
            if rsi_signal == 'Overbought' and stage in ['Stage 3', 'Stage 4']:
                score += 1

            # Factor 7: Cross below 30WMA (primary Weinstein sell signal)
            cross_below_alert = df.iloc[i].get('cross_below_alert', '-')
            if cross_below_alert in ['SELL', 'SELL (Vol)']:
                score += 1

            df.loc[i, 'exit_score'] = score

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

            # Criterion 5: RSI not oversold (shows some buying interest)
            rsi_signal = df.iloc[i].get('rsi_signal', 'N/A')
            if rsi_signal in ['Neutral', 'Overbought']:  # Not deeply oversold
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

        # Signal: Above/Below 200 DMA
        df['dma_200_signal'] = df['price_vs_200dma'].apply(
            lambda x: 'Above' if pd.notna(x) and x >= 0
            else ('Below' if pd.notna(x) else 'N/A')
        )

        return df

    def calculate_accumulation_score(self, df):
        """
        Calculate accumulation score (0-6 based on multiple factors)

        Args:
            df: DataFrame with all calculated fields

        Returns:
            DataFrame with accum_score added
        """
        df = df.copy()
        df['accum_score'] = 0

        for i in range(len(df)):
            score = 0

            # Factor 1: Moderate positive momentum (1-month ROC between 0-15%)
            # 1 month = ~22 trading days
            # Goldilocks zone: gaining strength but not overheated
            if i >= 22:
                current_price = df.iloc[i]['close']
                price_22d_ago = df.iloc[i-22]['close']
                if pd.notna(current_price) and pd.notna(price_22d_ago) and price_22d_ago > 0:
                    roc_1m = ((current_price - price_22d_ago) / price_22d_ago) * 100
                    if 0 <= roc_1m <= 15:  # Sweet spot for accumulation
                        score += 1

            # Factor 2: High average delivery (30d ≥55%)
            if pd.notna(df.iloc[i]['deliv_avg_30d']) and df.iloc[i]['deliv_avg_30d'] >= 55:
                score += 1

            # Factor 3: Delivery trend increasing or stable
            if df.iloc[i]['deliv_trend'] in ['Increasing', 'Stable']:
                score += 1

            # Factor 4: Price above or near 30WMA (for accumulation, we want early stage)
            price_vs = df.iloc[i]['price_vs_wma_pct']
            if pd.notna(price_vs) and -5 <= price_vs <= 10:  # Within 5% below to 10% above
                score += 1

            # Factor 5: 30WMA flat or rising (not falling)
            if df.iloc[i]['wma_slope'] in ['Flat', 'Rising']:
                score += 1

            # Factor 6: Sustained volume confirmation (5 out of last 10 days)
            # Check if volume > 36MA for at least 5 out of last 10 days
            start_idx = max(0, i - 9)
            recent_10 = df.iloc[start_idx:i + 1]
            high_vol_days = (recent_10['is_high_vol'] == 'Yes').sum()
            if high_vol_days >= 5:  # 50% of last 10 days had high volume
                score += 1

            df.loc[i, 'accum_score'] = score

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

        # Sort by date
        df = df.sort_values('date').reset_index(drop=True)

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
