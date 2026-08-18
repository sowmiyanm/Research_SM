"""
Data Cache Module
Stores historical stock data locally to enable incremental updates
Saves data in both pickle (fast) and Excel (readable) formats
"""

import pandas as pd
import numpy as np
import os
import logging
from datetime import datetime
import pickle
import tempfile

logger = logging.getLogger(__name__)

# Minimum required columns for a valid cache file. 'high' and 'low' are
# available from newer bhav copy fetches; older cache files without them
# are still valid (calculations will fall back to close-to-close TR).
REQUIRED_COLUMNS = ['date', 'close', 'traded_quantity', 'delivery_quantity']


def _has_required_columns(df, ticker, source, required_columns=REQUIRED_COLUMNS):
    """Guard against a corrupt/stale cache file silently propagating a
    DataFrame missing columns every downstream calculation assumes exist -
    without this check, a truncated pickle or a hand-edited Excel cache
    would surface as a confusing KeyError deep inside calculations.py
    instead of a clear cache-level warning naming the actual file at fault.
    """
    missing = [c for c in required_columns if c not in df.columns]
    if missing:
        logger.warning(f"{source} cache for {ticker} is missing required columns {missing} - treating as no cache")
        return False
    return True



class DataCache:
    """Manages local cache of stock data for incremental updates"""

    def __init__(self, cache_dir="./data_cache"):
        self.cache_dir = cache_dir
        self.excel_cache_dir = os.path.join(cache_dir, "excel")
        os.makedirs(cache_dir, exist_ok=True)
        os.makedirs(self.excel_cache_dir, exist_ok=True)

    def get_ticker_cache_path(self, ticker):
        """Get file path for ticker cache"""
        return os.path.join(self.cache_dir, f"{ticker}.pkl")

    def get_ticker_excel_path(self, ticker):
        """Get file path for ticker Excel cache"""
        return os.path.join(self.excel_cache_dir, f"{ticker}_historical.xlsx")

    def load_ticker_data(self, ticker, required_columns=REQUIRED_COLUMNS):
        """
        Load cached data for a ticker (tries pickle first, then Excel backup)

        Args:
            required_columns: schema to validate against. Defaults to the
                full stock schema; pass a smaller list (e.g. ['date', 'close'])
                for index data like NIFTY_50, which has no volume/delivery.

        Returns:
            DataFrame with historical data, or empty DataFrame if no cache
        """
        # Try loading from pickle first (faster)
        cache_path = self.get_ticker_cache_path(ticker)

        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'rb') as f:
                    df = pickle.load(f)
                if not _has_required_columns(df, ticker, "Pickle", required_columns):
                    logger.info("Attempting to load from Excel backup...")
                else:
                    logger.info(f"Loaded {len(df)} cached records from pickle for {ticker}")
                    return df
            except Exception as e:
                logger.warning(f"Error loading pickle cache for {ticker}: {e}")
                logger.info("Attempting to load from Excel backup...")

        # Fallback to Excel if pickle fails or doesn't exist
        excel_path = self.get_ticker_excel_path(ticker)
        if os.path.exists(excel_path):
            try:
                df = pd.read_excel(excel_path)
                # Convert date column back to datetime
                df['date'] = pd.to_datetime(df['date'])
                # Remove delivery_pct if it exists (will be recalculated)
                if 'delivery_pct' in df.columns:
                    df = df.drop(columns=['delivery_pct'])
                if not _has_required_columns(df, ticker, "Excel", required_columns):
                    return pd.DataFrame()
                logger.info(f"Loaded {len(df)} cached records from Excel for {ticker}")
                return df
            except Exception as e:
                logger.warning(f"Error loading Excel cache for {ticker}: {e}")
                return pd.DataFrame()
        else:
            logger.info(f"No cache found for {ticker}")
            return pd.DataFrame()

    def has_cache(self, ticker):
        """Cheap check for whether a ticker has any cached data (pickle or Excel)"""
        return os.path.exists(self.get_ticker_cache_path(ticker)) or \
            os.path.exists(self.get_ticker_excel_path(ticker))

    def save_ticker_data(self, ticker, df):
        """
        Save ticker data to cache (both pickle and Excel)

        Args:
            ticker: Stock ticker
            df: DataFrame with columns: date, close, traded_quantity, delivery_quantity
        """
        # Save pickle atomically (fast for loading): write to a temp file in the
        # same directory, then os.replace() so a crash mid-write never leaves a
        # truncated/corrupt cache file behind.
        cache_path = self.get_ticker_cache_path(ticker)
        try:
            fd, tmp_path = tempfile.mkstemp(dir=self.cache_dir, prefix=f".{ticker}.", suffix=".tmp")
            try:
                with os.fdopen(fd, 'wb') as f:
                    pickle.dump(df, f)
                os.replace(tmp_path, cache_path)
            except Exception:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                raise
            logger.info(f"Saved {len(df)} records to pickle cache for {ticker}")
        except Exception as e:
            logger.error(f"Error saving pickle cache for {ticker}: {e}")

        # Save Excel (readable backup)
        excel_path = self.get_ticker_excel_path(ticker)
        try:
            # Create a copy for Excel export with formatted date
            df_excel = df.copy()
            df_excel['date'] = pd.to_datetime(df_excel['date']).dt.strftime('%Y-%m-%d')

            # Calculate delivery percentage for Excel
            df_excel['delivery_pct'] = df_excel.apply(
                lambda row: round((row['delivery_quantity'] / row['traded_quantity']) * 100, 2)
                if row['traded_quantity'] > 0 else np.nan, axis=1
            )

            # Reorder columns for better readability.
            # 'high'/'low' MUST be included when present: the Excel file is the
            # fallback the cache loads from when a pickle is missing or corrupt.
            # Omitting them made the backup lossy, and a pickle failure would
            # then silently downgrade 52-week extremes to close-based and the
            # squeeze ATR to close-to-close, with no warning anywhere.
            cols = ['date', 'close', 'high', 'low',
                    'traded_quantity', 'delivery_quantity', 'delivery_pct']
            cols = [c for c in cols if c in df_excel.columns]
            df_excel = df_excel[cols]

            df_excel.to_excel(excel_path, index=False, sheet_name=ticker)
            logger.info(f"Saved {len(df)} records to Excel cache for {ticker}")
        except Exception as e:
            logger.warning(f"Error saving Excel cache for {ticker}: {e}")

    def get_latest_date(self, ticker):
        """
        Get the latest date for which we have data for a ticker

        Returns:
            datetime object or None if no cache
        """
        df = self.load_ticker_data(ticker)

        if not df.empty:
            latest_date = df['date'].max()
            # Normalise to midnight: legacy cache files stored the wall-clock
            # time of the run in the date column, which would otherwise leak a
            # spurious time-of-day into the incremental fetch window.
            return pd.to_datetime(latest_date).normalize()
        return None

    def merge_new_data(self, ticker, new_df):
        """
        Merge new data with cached data

        Args:
            ticker: Stock ticker
            new_df: DataFrame with new data

        Returns:
            Combined DataFrame with deduplicated data
        """
        cached_df = self.load_ticker_data(ticker)

        # Normalise BOTH sides to midnight before de-duplicating. Legacy cache
        # files written before dates were normalised at ingestion stored the
        # wall-clock time of the run (e.g. 2025-11-07T21:19:19.687191). A fresh
        # fetch writes 2025-11-07T00:00:00, so drop_duplicates(subset=['date'])
        # saw two different values and kept BOTH — silently doubling every
        # overlapping trading day and halving the real span of every rolling
        # window (36-day volume MA, 252-day 52-week high, weekly WMA bars...).
        # Normalising here makes the merge correct regardless of what vintage
        # of cache file is on disk, and save_ticker_data below then rewrites
        # the file in normalised form.
        if not new_df.empty and 'date' in new_df.columns:
            new_df = new_df.copy()
            new_df['date'] = pd.to_datetime(new_df['date']).dt.normalize()
        if not cached_df.empty and 'date' in cached_df.columns:
            cached_df = cached_df.copy()
            cached_df['date'] = pd.to_datetime(cached_df['date']).dt.normalize()

        if cached_df.empty:
            # No cache, return new data as is
            combined = new_df
        else:
            # Combine and remove duplicates
            combined = pd.concat([cached_df, new_df], ignore_index=True)

            # Remove duplicates based on date, keeping the latest
            combined = combined.sort_values('date').drop_duplicates(subset=['date'], keep='last')

        combined = combined.sort_values('date').reset_index(drop=True)

        # Save updated cache
        self.save_ticker_data(ticker, combined)

        return combined

    def clear_cache(self, ticker=None):
        """
        Clear cache for a specific ticker or all tickers (both pickle and Excel)

        Args:
            ticker: Ticker to clear (None = clear all)
        """
        if ticker:
            # Clear pickle cache
            cache_path = self.get_ticker_cache_path(ticker)
            if os.path.exists(cache_path):
                os.remove(cache_path)
                logger.info(f"Cleared pickle cache for {ticker}")

            # Clear Excel cache
            excel_path = self.get_ticker_excel_path(ticker)
            if os.path.exists(excel_path):
                os.remove(excel_path)
                logger.info(f"Cleared Excel cache for {ticker}")
        else:
            # Clear all pickle cache files
            for filename in os.listdir(self.cache_dir):
                if filename.endswith('.pkl'):
                    os.remove(os.path.join(self.cache_dir, filename))

            # Clear all Excel cache files
            if os.path.exists(self.excel_cache_dir):
                for filename in os.listdir(self.excel_cache_dir):
                    if filename.endswith('.xlsx'):
                        os.remove(os.path.join(self.excel_cache_dir, filename))

            logger.info("Cleared all cache files (pickle and Excel)")

    def get_cache_info(self):
        """Get information about cached tickers"""
        info = []

        for filename in os.listdir(self.cache_dir):
            if filename.endswith('.pkl'):
                ticker = filename.replace('.pkl', '')
                df = self.load_ticker_data(ticker)

                if not df.empty:
                    info.append({
                        'ticker': ticker,
                        'records': len(df),
                        'from_date': df['date'].min(),
                        'to_date': df['date'].max()
                    })

        return pd.DataFrame(info)
