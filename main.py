#!/usr/bin/env python3
"""
NSE Stock Delivery + Volume + 30WMA Screener
Main orchestration script

Supports two modes:
1. Initial mode: Fetch last 60+ days of data (first run)
2. Incremental mode: Fetch only new data since last run (daily updates)
"""

import json
import logging
import sys
import argparse
import os
import shutil
import glob
from datetime import datetime, timedelta
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict
import pandas as pd

from nse_data_fetcher import NSEDataFetcher
from calculations import StockCalculator
from excel_generator import ExcelReportGenerator
from data_cache import DataCache

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('stock_screener.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class StockScreener:
    """Main stock screener application"""

    def __init__(self, config_file='config.json', mode='auto', batch_size=50, max_workers=4,
                 skip_financials=False):
        """
        Initialize screener with configuration

        Args:
            config_file: Path to configuration file
            mode: 'auto', 'initial', or 'incremental'
                - auto: Automatically detect based on cache
                - initial: Force full historical load
                - incremental: Only fetch new data
            batch_size: Number of tickers to process in each batch
            max_workers: Maximum concurrent processing threads
            skip_financials: Skip fetching quarterly financial results (saves ~3-5 min)
        """
        self.config = self._load_config(config_file)
        self.nse_fetcher = NSEDataFetcher()
        self.calculator = StockCalculator(self.config)
        self.excel_generator = ExcelReportGenerator(self.config)
        self.cache = DataCache()
        self.mode = mode
        self.batch_size = batch_size
        self.max_workers = max_workers
        self.skip_financials = skip_financials

    # ══════════════════════════════════════════════════════════════════
    #  Cache safety net — backup / restore / prune
    # ══════════════════════════════════════════════════════════════════

    def _backup_cache(self):
        """Snapshot the cache directory before a destructive rebuild.

        A monthly rebuild deletes ~1,000 ticker histories and re-downloads
        501 bhav copies over 40-70 minutes. Runs DO die partway — one already
        has (it stopped at ticker 823 and left a truncated Excel file behind).
        Without a snapshot, an interrupted rebuild leaves a partial universe
        and no way back.

        Returns the backup path, or None if there was nothing to back up.
        """
        cache_dir = self.cache.cache_dir
        if not os.path.isdir(cache_dir) or not os.listdir(cache_dir):
            logger.info("No existing cache to back up")
            return None

        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup = f"{cache_dir.rstrip('/')}_backup_{stamp}"
        logger.info(f"Backing up cache -> {backup} (this can take a moment)")
        try:
            shutil.copytree(cache_dir, backup)
            n_pkl = len(glob.glob(os.path.join(backup, '*.pkl')))
            logger.info(f"Backup complete: {n_pkl} ticker files")
            return backup
        except Exception as e:
            logger.error(f"Cache backup FAILED: {e}")
            return None

    def _restore_cache(self, backup):
        """Roll the cache back to a snapshot after a failed rebuild."""
        if not backup or not os.path.isdir(backup):
            logger.error("Cannot restore — backup missing")
            return False
        cache_dir = self.cache.cache_dir
        try:
            broken = f"{cache_dir.rstrip('/')}_failed_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            if os.path.isdir(cache_dir):
                shutil.move(cache_dir, broken)
            shutil.move(backup, cache_dir)
            logger.warning(f"Cache RESTORED from backup. Failed attempt kept at {broken}")
            return True
        except Exception as e:
            logger.error(f"Cache restore FAILED: {e} — backup is still at {backup}")
            return False

    def _prune_backups(self, keep=2):
        """Keep only the most recent N backups so they don't accumulate."""
        pattern = f"{self.cache.cache_dir.rstrip('/')}_backup_*"
        backups = sorted(glob.glob(pattern))
        for old in backups[:-keep] if len(backups) > keep else []:
            try:
                shutil.rmtree(old)
                logger.info(f"Pruned old backup {os.path.basename(old)}")
            except Exception as e:
                logger.warning(f"Could not prune {old}: {e}")

    # ══════════════════════════════════════════════════════════════════
    #  Post-run health check
    # ══════════════════════════════════════════════════════════════════

    def _health_check(self, tickers, ticker_data):
        """Verify the run actually produced a complete, current, clean cache.

        This exists because a partial run is otherwise INVISIBLE. A process
        killed mid-run prints nothing at all, and a ticker whose fetch returns
        nothing falls back to cached data and is reported as a success (✓).
        That combination is how 229 tickers sat 9 trading days stale for two
        weeks without anything flagging it.

        Returns a dict of results; logs WARNINGs for anything wrong.
        """
        logger.info("\n" + "=" * 80)
        logger.info("HEALTH CHECK")
        logger.info("=" * 80)

        expected = set(tickers)
        cached = {os.path.basename(p)[:-4] for p in glob.glob(os.path.join(self.cache.cache_dir, '*.pkl'))}
        cached.discard('NIFTY_50')
        missing = sorted(expected - cached)

        # Freshness + duplicates, computed from the in-memory frames (free)
        last_dates, dupes = {}, {}
        for t, df in ticker_data.items():
            if df is None or df.empty or 'date' not in df.columns:
                continue
            d = pd.to_datetime(df['date'])
            last_dates[t] = d.max()
            n = int(d.duplicated().sum())
            if n:
                dupes[t] = n

        newest = max(last_dates.values()) if last_dates else None

        # Split "behind" into two very different problems:
        #
        #   STALE     — days behind, a re-run catches it up. Actionable.
        #   DELISTED  — months behind. The symbol has been delisted, suspended
        #               or renamed (ZOMATO -> ETERNAL, TATAMOTORS demerged,
        #               GENSOL suspended). Re-running will NEVER fix these.
        #
        # Reporting them together would put ~30 permanent warnings on every
        # single run, and a warning you always see is a warning you stop
        # reading — which would defeat the point of this whole check.
        DELISTED_DAYS = self.config.get('delisted_days_threshold', 60)
        stale, delisted = [], []
        if newest is not None:
            for t, v in last_dates.items():
                behind = (newest - v).days
                if behind >= DELISTED_DAYS:
                    delisted.append((t, v))
                elif behind >= 3:
                    stale.append((t, v))
        stale.sort(key=lambda x: x[1])
        delisted.sort(key=lambda x: x[1])

        # Corrupt Excel backups (truncated by an interrupted non-atomic write)
        corrupt = []
        try:
            import zipfile
            for p in glob.glob(os.path.join(self.cache.excel_cache_dir, '*.xlsx')):
                if not zipfile.is_zipfile(p):
                    corrupt.append(os.path.basename(p))
        except Exception:
            pass

        coverage = 100.0 * len(cached & expected) / len(expected) if expected else 0.0
        logger.info(f"Coverage    : {len(cached & expected)}/{len(expected)} tickers cached ({coverage:.1f}%)")
        logger.info(f"Newest date : {newest.date() if newest is not None else 'n/a'}")
        logger.info(f"Stale (3d+) : {len(stale)}")
        logger.info(f"Delisted?   : {len(delisted)} ({DELISTED_DAYS}d+ behind)")
        logger.info(f"Duplicates  : {len(dupes)} tickers")
        logger.info(f"Corrupt xlsx: {len(corrupt)}")

        # ── Actionable problems (WARNING) ──
        if missing:
            logger.warning(f"MISSING from cache ({len(missing)}): "
                           f"{', '.join(missing[:15])}{'...' if len(missing) > 15 else ''}")
        if stale:
            logger.warning(f"STALE — not on {newest.date()} ({len(stale)}). Oldest: "
                           + ', '.join(f"{t} {v.date()}" for t, v in stale[:8]))
            logger.warning("  Re-run to catch these up. Check the 'As Of' column before "
                           "trusting signals for any of them.")
        if dupes:
            logger.warning(f"DUPLICATE trading days in {len(dupes)} tickers: {list(dupes)[:8]} "
                           f"— rolling windows are wrong for these. Rebuild them.")
        if corrupt:
            logger.warning(f"CORRUPT Excel backups ({len(corrupt)}): {corrupt[:8]}. "
                           f"The pickle is still authoritative; delete these so they get rewritten.")

        # ── Not actionable by re-running: report at INFO so it doesn't drown
        #    the warnings above, but keep it visible so the list can be pruned.
        if delisted:
            logger.info(
                f"Likely delisted / renamed / suspended ({len(delisted)}) — a re-run will NOT "
                f"fix these; consider removing them from tickers.txt:"
            )
            logger.info("  " + ', '.join(f"{t} ({v.date()})" for t, v in delisted[:20])
                        + ('...' if len(delisted) > 20 else ''))

        if not (missing or stale or dupes or corrupt):
            extra = f" ({len(delisted)} delisted tickers ignored)" if delisted else ""
            logger.info(f"All clear — cache is complete, current and clean{extra}.")

        return {'coverage': coverage, 'missing': missing, 'stale': stale,
                'delisted': delisted, 'dupes': dupes, 'corrupt': corrupt, 'newest': newest}

    def _load_config(self, config_file):
        """Load configuration from JSON file"""
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
            logger.info(f"Configuration loaded from {config_file}")
            return config
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            sys.exit(1)

    def _read_ticker_file(self, filename):
        """Read tickers from text file, ignoring comments and blank lines"""
        tickers = []
        try:
            with open(filename, 'r') as f:
                for line in f:
                    line = line.strip()
                    # Ignore comments and blank lines
                    if line and not line.startswith('#'):
                        tickers.append(line.upper())
            logger.info(f"Read {len(tickers)} tickers from {filename}")
            return tickers
        except FileNotFoundError:
            logger.warning(f"File not found: {filename}")
            return []
        except Exception as e:
            logger.error(f"Error reading {filename}: {e}")
            return []

    def _calculate_fetch_window(self, ticker=None):
        """
        Calculate date range for data fetching

        Args:
            ticker: Optional ticker to check for cached data

        Returns:
            (from_date, to_date, is_incremental)
        """
        # Use today's date - NSE publishes same-day data after market close
        # The fetcher will gracefully skip if data is not yet available
        to_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        # Check if we have cached data and determine mode
        if self.mode == 'incremental' or (self.mode == 'auto' and ticker):
            latest_cached_date = self.cache.get_latest_date(ticker)

            if latest_cached_date:
                # Incremental mode: fetch from last cached date
                from_date = latest_cached_date + timedelta(days=1)
                logger.info(f"Incremental mode: Fetching from {from_date.date()} to {to_date.date()}")
                return from_date, to_date, True

        # Initial mode: fetch full historical data (~2 years = ~500 trading days)
        # 730 calendar days covers ~500 trading days accounting for
        # weekends and market holidays
        history_calendar_days = 730
        lookback_days = self.config.get('lookback_days_display', 60)
        volume_ma_period = self.config.get('volume_ma_period', 36)

        total_days = max(history_calendar_days, lookback_days + volume_ma_period + 30)

        from_date = to_date - timedelta(days=total_days)

        logger.info(f"Initial mode: Fetching from {from_date.date()} to {to_date.date()}")
        return from_date, to_date, False

    def _merge_marketlens_augment(self, ticker_data):
        """Overlay PE from the newest MarketLens drop-folder export onto each
        ticker's latest row. NSE's PE quote API is blocked, so pe_ratio comes
        back NaN from calculations; MarketLens fills that gap. A live NSE value,
        if one ever arrives, is preferred — we only fill where pe_ratio is NaN."""
        try:
            from marketlens_augment import augmentation_frame
            aug = augmentation_frame()
        except Exception as e:
            logger.warning(f"MarketLens augment unavailable ({e}); PE will be blank")
            return

        if not aug:
            logger.info("MarketLens: no export in marketlens_drop/ — PE left blank")
            return

        filled = 0
        for ticker, df in ticker_data.items():
            if df is None or df.empty:
                continue
            row = aug.get(ticker)
            if not row:
                continue
            pe = row.get('pe')
            if pe is None or pd.isna(pe):
                continue
            last_idx = df.index[-1]
            if 'pe_ratio' not in df.columns or pd.isna(df.at[last_idx, 'pe_ratio']):
                df.at[last_idx, 'pe_ratio'] = pe
                filled += 1
        logger.info(f"MarketLens: PE filled for {filled}/{len(ticker_data)} tickers "
                    f"from {len(aug)} export rows")

    def _process_single_ticker(self, ticker, from_date, to_date, is_incremental,
                               nse_52w_data=None, nifty_df=None,
                               promoter_data=None, financial_data=None):
        """
        Process a single ticker (used for concurrent processing)

        Args:
            ticker: Stock symbol
            from_date: Start date
            to_date: End date
            is_incremental: Whether this is incremental update
            nse_52w_data: Optional dict with NSE 52W data for this ticker
            nifty_df: Optional NIFTY 50 DataFrame for relative strength

        Returns:
            Tuple (ticker, processed_df, success, error_msg)
        """
        try:
            if is_incremental and from_date > to_date:
                # Already up to date, load from cache
                cached_df = self.cache.load_ticker_data(ticker)
                if not cached_df.empty:
                    processed_df = self.calculator.process_ticker_data(cached_df, nse_52w_data=nse_52w_data, nifty_df=nifty_df, promoter_data=promoter_data, financial_data=financial_data)
                    return (ticker, processed_df, True, "Already up to date")
                return (ticker, pd.DataFrame(), False, "No cached data")

            # Fetch new data from NSE
            new_df = self.nse_fetcher.get_stock_data(
                ticker,
                from_date=from_date,
                to_date=to_date,
            )

            if new_df.empty:
                # Try loading from cache
                cached_df = self.cache.load_ticker_data(ticker)
                if not cached_df.empty:
                    processed_df = self.calculator.process_ticker_data(cached_df, nse_52w_data=nse_52w_data, nifty_df=nifty_df, promoter_data=promoter_data, financial_data=financial_data)
                    return (ticker, processed_df, True, "Using cached data")
                return (ticker, pd.DataFrame(), False, "No data available")

            # Always merge through the cache rather than overwriting it outright —
            # an "initial" fetch can still run against a ticker that already has a
            # longer cached history (e.g. re-running --mode initial), and a raw
            # overwrite would silently discard everything outside the new window.
            combined_df = self.cache.merge_new_data(ticker, new_df)

            # Process calculations
            processed_df = self.calculator.process_ticker_data(combined_df, nse_52w_data=nse_52w_data, nifty_df=nifty_df, promoter_data=promoter_data, financial_data=financial_data)

            return (ticker, processed_df, True, f"{len(new_df)} new records")

        except Exception as e:
            # Try loading from cache as fallback
            try:
                cached_df = self.cache.load_ticker_data(ticker)
                if not cached_df.empty:
                    processed_df = self.calculator.process_ticker_data(cached_df, nse_52w_data=nse_52w_data, nifty_df=nifty_df, promoter_data=promoter_data, financial_data=financial_data)
                    return (ticker, processed_df, True, f"Error but cached: {str(e)}")
            except Exception as fallback_err:
                # `except Exception`, not a bare `except`: a bare clause also
                # catches KeyboardInterrupt and SystemExit, so Ctrl-C during the
                # cache-fallback of a 1,000-ticker run was silently swallowed and
                # the run carried on to the next ticker.
                logger.debug(f"{ticker}: cache fallback also failed: {fallback_err}")
            return (ticker, pd.DataFrame(), False, str(e))

    def _process_batch_optimized(self, tickers: List[str], from_date, to_date,
                                nse_52w_data=None, nifty_df=None,
                                promoter_data=None, financial_data=None) -> Dict[str, pd.DataFrame]:
        """
        Process a batch of tickers using optimized batch fetching

        Args:
            tickers: List of ticker symbols
            from_date: Start date
            to_date: End date
            nse_52w_data: Optional dict of 52W data keyed by ticker
            nifty_df: Optional NIFTY 50 DataFrame for relative strength

        Returns:
            Dictionary mapping ticker -> processed DataFrame
        """
        logger.info(f"Processing batch of {len(tickers)} tickers using optimized batch mode")

        # Fetch all tickers in batch (one bhav copy fetch per date)
        batch_data = self.nse_fetcher.get_stock_data_batch(
            tickers,
            from_date=from_date,
            to_date=to_date,
        )

        nse_52w_data = nse_52w_data or {}
        promoter_data = promoter_data or {}
        financial_data = financial_data or {}

        # Process each ticker's data with calculations
        processed_data = {}
        for ticker, df in batch_data.items():
            try:
                ticker_52w = nse_52w_data.get(ticker)
                ticker_promoter = promoter_data.get(ticker)
                ticker_financials = financial_data.get(ticker)
                if not df.empty:
                    # Merge with existing cache rather than overwriting —
                    # a fresh "initial" fetch window may be shorter than the
                    # history already on disk
                    combined_df = self.cache.merge_new_data(ticker, df)
                    # Process calculations
                    processed_df = self.calculator.process_ticker_data(
                        combined_df, nse_52w_data=ticker_52w, nifty_df=nifty_df,
                        promoter_data=ticker_promoter, financial_data=ticker_financials)
                    processed_data[ticker] = processed_df
                else:
                    # Try loading from cache
                    cached_df = self.cache.load_ticker_data(ticker)
                    if not cached_df.empty:
                        processed_df = self.calculator.process_ticker_data(
                            cached_df, nse_52w_data=ticker_52w, nifty_df=nifty_df,
                            promoter_data=ticker_promoter, financial_data=ticker_financials)
                        processed_data[ticker] = processed_df
            except Exception as e:
                logger.error(f"Error processing {ticker}: {str(e)}")
                continue

        return processed_data

    def run(self):
        """Main execution flow - OPTIMIZED VERSION with batch processing"""
        start_time = time.time()

        logger.info("=" * 80)
        logger.info("NSE Stock Screener Started (OPTIMIZED MODE)")
        logger.info(f"Mode: {self.mode.upper()}")
        logger.info(f"Batch size: {self.batch_size} | Max workers: {self.max_workers}")
        logger.info("=" * 80)

        # Read ticker list
        tickers = self._read_ticker_file('tickers.txt')
        if not tickers:
            logger.error("No tickers to process. Exiting.")
            return

        # Read FNO tickers
        fno_tickers = set(self._read_ticker_file('fno_tickers.txt'))

        # Fetch authoritative 52-week high/low + PE data from NSE quote API.
        # When NSE is blocking (403) — common for non-India IPs — fall back to
        # Yahoo Finance which serves 52W high/low without auth.
        logger.info("Fetching 52-week high/low + fundamental data from NSE...")
        nse_52w_data = self.nse_fetcher.fetch_52week_batch(tickers)
        if not nse_52w_data:
            logger.info("NSE 52-week fetch returned no data; falling back to Yahoo Finance...")
            nse_52w_data = self.nse_fetcher.fetch_52week_batch_yahoo(tickers)

        # Fetch promoter + financial data in parallel (both are slow API calls)
        from concurrent.futures import ThreadPoolExecutor as _TPE

        def _fetch_promoter():
            logger.info("Fetching promoter holding data from NSE...")
            return self.nse_fetcher.fetch_promoter_holding_batch(tickers)

        def _fetch_financials():
            if self.skip_financials:
                logger.info("Skipping financial results fetch (--skip-financials)")
                return {}
            logger.info("Fetching quarterly financial results from NSE...")
            return self.nse_fetcher.fetch_financial_results_batch(tickers)

        with _TPE(max_workers=2) as parallel_executor:
            promoter_future = parallel_executor.submit(_fetch_promoter)
            financial_future = parallel_executor.submit(_fetch_financials)
            promoter_data = promoter_future.result()
            financial_data = financial_future.result()

        # Determine the full-history window (used for any ticker with no cache yet,
        # regardless of mode). NOTE: is_incremental from this call is NOT a global
        # decision — with ticker=None it always reflects the "no cache to check"
        # case. Per-ticker incremental vs. initial handling happens in the batch
        # loop below via DataCache.has_cache().
        from_date, to_date, _ = self._calculate_fetch_window()

        # Fetch NIFTY 50 index data for relative strength calculation
        logger.info("Fetching NIFTY 50 data for relative strength...")
        nifty_df = self.nse_fetcher.fetch_nifty_data(from_date=from_date, to_date=to_date)
        if nifty_df.empty:
            # Try fetching from cache
            nifty_df = self.cache.load_ticker_data('NIFTY_50', required_columns=['date', 'close'])
            if nifty_df.empty:
                logger.error("NIFTY 50 fetch failed AND no cache available - RS vs NIFTY "
                             "will be N/A for the entire universe this run (visible as a "
                             "warning banner on the Shortlist sheet)")
                nifty_df = None
            else:
                logger.info(f"Loaded NIFTY 50 from cache: {len(nifty_df)} days")
        else:
            self.cache.save_ticker_data('NIFTY_50', nifty_df)
            logger.info(f"Fetched NIFTY 50: {len(nifty_df)} days")

        ticker_data = {}
        failed_tickers = []

        # OPTIMIZED: Process tickers in batches
        total_batches = (len(tickers) + self.batch_size - 1) // self.batch_size

        for batch_num in range(total_batches):
            batch_start = batch_num * self.batch_size
            batch_end = min(batch_start + self.batch_size, len(tickers))
            batch_tickers = tickers[batch_start:batch_end]

            logger.info(f"\n{'=' * 80}")
            logger.info(f"Processing Batch {batch_num + 1}/{total_batches}: {len(batch_tickers)} tickers")
            logger.info(f"Tickers: {', '.join(batch_tickers[:5])}{'...' if len(batch_tickers) > 5 else ''}")
            logger.info(f"{'=' * 80}")

            # Decide per-ticker whether this is an incremental update or needs a
            # full historical fetch. In 'auto' mode this is based on whether the
            # ticker actually has cached data -- NOT a single decision for the
            # whole run, so routine runs after the first one take the fast,
            # incremental path instead of re-fetching full history every time.
            if self.mode == 'initial':
                batch_full = batch_tickers
                batch_incremental = []
            elif self.mode == 'incremental':
                batch_full = []
                batch_incremental = batch_tickers
            else:  # auto
                batch_full = [t for t in batch_tickers if not self.cache.has_cache(t)]
                batch_incremental = [t for t in batch_tickers if self.cache.has_cache(t)]

            batch_results = {}

            # Tickers with no cache yet: fetch full history via the optimized batch path
            if batch_full:
                try:
                    full_results = self._process_batch_optimized(
                        batch_full, from_date, to_date,
                        nse_52w_data=nse_52w_data, nifty_df=nifty_df,
                        promoter_data=promoter_data, financial_data=financial_data)
                    batch_results.update(full_results)
                except Exception as e:
                    logger.error(f"Batch {batch_num + 1} full-fetch group failed: {str(e)}")
                    failed_tickers.extend(batch_full)

            # Tickers with existing cache: fetch only new data since last cached date
            if batch_incremental:
                with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    futures = {}

                    for ticker in batch_incremental:
                        ticker_from_date, ticker_to_date, ticker_is_incr = self._calculate_fetch_window(ticker)
                        ticker_52w = nse_52w_data.get(ticker)
                        ticker_promoter = promoter_data.get(ticker)
                        ticker_financials = financial_data.get(ticker)
                        future = executor.submit(
                            self._process_single_ticker,
                            ticker, ticker_from_date, ticker_to_date, ticker_is_incr,
                            nse_52w_data=ticker_52w, nifty_df=nifty_df,
                            promoter_data=ticker_promoter, financial_data=ticker_financials
                        )
                        futures[future] = ticker

                    for future in as_completed(futures):
                        ticker = futures[future]
                        try:
                            ticker_symbol, processed_df, success, msg = future.result()

                            if success and not processed_df.empty:
                                batch_results[ticker_symbol] = processed_df
                                logger.info(f"✓ {ticker_symbol}: {msg}")
                            else:
                                failed_tickers.append(ticker_symbol)
                                logger.warning(f"✗ {ticker_symbol}: {msg}")

                        except Exception as e:
                            logger.error(f"✗ {ticker}: {str(e)}")
                            failed_tickers.append(ticker)

            ticker_data.update(batch_results)
            success_count = len(batch_results)
            fail_count = len(batch_tickers) - success_count
            logger.info(f"Batch {batch_num + 1} complete: ✓ {success_count} succeeded, ✗ {fail_count} failed")

            for ticker in batch_tickers:
                if ticker not in batch_results and ticker not in failed_tickers:
                    failed_tickers.append(ticker)

        # Generate Excel report
        if ticker_data:
            logger.info("\n" + "=" * 80)
            logger.info("Generating Excel Report...")
            logger.info("=" * 80)

            self._merge_marketlens_augment(ticker_data)

            try:
                output_file = self.excel_generator.generate_report(
                    ticker_data,
                    fno_tickers,
                    ticker_order=tickers  # Pass original ticker order
                )
                logger.info(f"\n✓ Report generated successfully: {output_file}")
            except Exception as e:
                logger.error(f"Error generating Excel report: {e}")
                import traceback
                traceback.print_exc()
        else:
            logger.warning("No data to generate report")

        # Summary
        elapsed_time = time.time() - start_time
        logger.info("\n" + "=" * 80)
        logger.info("SUMMARY")
        logger.info("=" * 80)
        logger.info(f"Total tickers: {len(tickers)}")
        logger.info(f"Successfully processed: {len(ticker_data)}")
        logger.info(f"Failed: {len(failed_tickers)}")
        logger.info(f"Total time: {elapsed_time:.1f} seconds ({elapsed_time/60:.1f} minutes)")
        logger.info(f"Average time per ticker: {elapsed_time/len(tickers):.2f} seconds")

        if failed_tickers:
            logger.info(f"\nFailed tickers ({len(failed_tickers)}): {', '.join(failed_tickers[:20])}{'...' if len(failed_tickers) > 20 else ''}")

        # Always health-check: a partial run is otherwise indistinguishable
        # from a complete one.
        health = self._health_check(tickers, ticker_data)

        logger.info("\nScreener completed!")
        return health


def main():
    """Entry point"""
    parser = argparse.ArgumentParser(
        description='NSE Stock Screener - Delivery + Volume + 30WMA Analysis (OPTIMIZED)'
    )
    parser.add_argument(
        '--mode',
        choices=['daily', 'monthly', 'auto', 'initial', 'incremental'],
        default='daily',
        help=(
            'daily   : fetch only new trading days since the last run (fast, use this most days). '
            'monthly : back up the cache, wipe it, and rebuild the full 2-year history from '
            'scratch — automatically rolls back if the rebuild fails. '
            '(auto/initial/incremental are the older equivalents and still work.)'
        )
    )
    parser.add_argument(
        '--clear-cache',
        action='store_true',
        help='Clear all cached data before running (implied by --mode monthly)'
    )
    parser.add_argument(
        '--no-backup',
        action='store_true',
        help='Skip the pre-rebuild cache backup in --mode monthly (not recommended)'
    )
    parser.add_argument(
        '--min-coverage',
        type=float,
        default=80.0,
        help='Monthly rebuild must end with at least this %% of tickers cached, '
             'else the backup is restored (default: 80)'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=50,
        help='Number of tickers to process in each batch (default: 50)'
    )
    parser.add_argument(
        '--max-workers',
        type=int,
        default=4,
        help='Maximum concurrent threads for processing (default: 4)'
    )
    parser.add_argument(
        '--skip-financials',
        action='store_true',
        help='Skip fetching quarterly financial results (saves ~3-5 min)'
    )

    args = parser.parse_args()

    # Map the friendly modes onto the internal fetch strategy.
    #   daily   -> auto     (cached tickers go incremental, new ones full)
    #   monthly -> initial  (full window for every ticker) + wipe + safety net
    is_monthly = args.mode == 'monthly'
    internal_mode = {'daily': 'auto', 'monthly': 'initial'}.get(args.mode, args.mode)

    backup = None
    try:
        screener = StockScreener(
            mode=internal_mode,
            batch_size=args.batch_size,
            max_workers=args.max_workers,
            skip_financials=args.skip_financials
        )

        if is_monthly:
            logger.info("=" * 80)
            logger.info("MONTHLY REBUILD — full 2-year history will be re-downloaded")
            logger.info("Expect roughly 40-70 minutes and ~0.7 GB of downloads")
            logger.info("=" * 80)
            if not args.no_backup:
                backup = screener._backup_cache()
            logger.info("Clearing cache for a clean rebuild...")
            screener.cache.clear_cache()

        elif args.clear_cache:
            logger.info("Clearing cache...")
            screener.cache.clear_cache()

        health = screener.run()

        # Safety net: if a monthly rebuild ended up with a badly incomplete
        # cache (process killed, network died, NSE blocked us), put the old
        # cache back rather than leaving a half-built one in place.
        if is_monthly and backup and health:
            if health['coverage'] < args.min_coverage:
                logger.error(
                    f"Rebuild finished with only {health['coverage']:.1f}% coverage "
                    f"(minimum {args.min_coverage}%) — ROLLING BACK to the pre-rebuild cache."
                )
                screener._restore_cache(backup)
                logger.error("Rolled back. Re-run --mode monthly when the connection is stable.")
                sys.exit(2)
            logger.info(f"Rebuild healthy ({health['coverage']:.1f}% coverage) — keeping it.")
            screener._prune_backups(keep=2)

    except KeyboardInterrupt:
        logger.warning("\nScreener interrupted by user")
        if is_monthly and backup:
            logger.warning("Monthly rebuild was interrupted — restoring the pre-rebuild cache.")
            try:
                StockScreener(mode='auto')._restore_cache(backup)
            except Exception as e:
                logger.error(f"Restore failed: {e}. Your backup is intact at {backup}")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        if is_monthly and backup:
            logger.error("Monthly rebuild crashed — restoring the pre-rebuild cache.")
            try:
                StockScreener(mode='auto')._restore_cache(backup)
            except Exception as e2:
                logger.error(f"Restore failed: {e2}. Your backup is intact at {backup}")
        sys.exit(1)


if __name__ == '__main__':
    main()
