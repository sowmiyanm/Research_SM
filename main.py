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
from datetime import datetime, timedelta
from pathlib import Path
import time
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
        to_date = datetime.now()

        # Check if we have cached data and determine mode
        if self.mode == 'incremental' or (self.mode == 'auto' and ticker):
            latest_cached_date = self.cache.get_latest_date(ticker)

            if latest_cached_date:
                # Incremental mode: fetch from last cached date
                from_date = latest_cached_date + timedelta(days=1)
                logger.info(f"Incremental mode: Fetching from {from_date.date()} to {to_date.date()}")
                return from_date, to_date, True

        # Initial mode: fetch full historical data
        lookback_days = self.config.get('lookback_days_display', 60)
        volume_ma_period = self.config.get('volume_ma_period', 36)
        weekly_wma_period = self.config.get('weekly_wma_period', 30)

        # Calculate days needed for weekly WMA
        # 30 weeks × 7 days/week = 210 days, but accounting for weekends/holidays
        # We need ~30 weeks of actual trading days, so fetch more calendar days
        weeks_buffer = weekly_wma_period + 10  # Extra buffer for holidays
        weekly_days = weeks_buffer * 7  # Convert weeks to calendar days

        # Total days = max of (display + volume MA) or (weekly WMA requirement)
        total_days = max(lookback_days + volume_ma_period + 30, weekly_days)

        from_date = to_date - timedelta(days=total_days)

        logger.info(f"Initial mode: Fetching from {from_date.date()} to {to_date.date()}")
        return from_date, to_date, False

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
                series='EQ'
            )

            if new_df.empty:
                # Try loading from cache
                cached_df = self.cache.load_ticker_data(ticker)
                if not cached_df.empty:
                    processed_df = self.calculator.process_ticker_data(cached_df, nse_52w_data=nse_52w_data, nifty_df=nifty_df, promoter_data=promoter_data, financial_data=financial_data)
                    return (ticker, processed_df, True, "Using cached data")
                return (ticker, pd.DataFrame(), False, "No data available")

            # Merge with cached data if in incremental mode
            if is_incremental:
                combined_df = self.cache.merge_new_data(ticker, new_df)
            else:
                combined_df = new_df
                self.cache.save_ticker_data(ticker, combined_df)

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
            except:
                pass
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
            series='EQ'
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
                    # Save to cache
                    self.cache.save_ticker_data(ticker, df)
                    # Process calculations
                    processed_df = self.calculator.process_ticker_data(
                        df, nse_52w_data=ticker_52w, nifty_df=nifty_df,
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

        # Fetch authoritative 52-week high/low + PE data from NSE quote API
        logger.info("Fetching 52-week high/low + fundamental data from NSE...")
        nse_52w_data = self.nse_fetcher.fetch_52week_batch(tickers)

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

        # Determine processing strategy
        from_date, to_date, is_incremental = self._calculate_fetch_window()

        # Fetch NIFTY 50 index data for relative strength calculation
        logger.info("Fetching NIFTY 50 data for relative strength...")
        nifty_df = self.nse_fetcher.fetch_nifty_data(from_date=from_date, to_date=to_date)
        if nifty_df.empty:
            # Try fetching from cache
            nifty_df = self.cache.load_ticker_data('NIFTY_50')
            if nifty_df.empty:
                logger.warning("Could not fetch NIFTY 50 data - RS calculations will be N/A")
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

            # Use batch optimized processing for initial loads
            if not is_incremental:
                try:
                    batch_results = self._process_batch_optimized(
                        batch_tickers, from_date, to_date,
                        nse_52w_data=nse_52w_data, nifty_df=nifty_df,
                        promoter_data=promoter_data, financial_data=financial_data)
                    ticker_data.update(batch_results)

                    success_count = len(batch_results)
                    fail_count = len(batch_tickers) - success_count
                    logger.info(f"Batch {batch_num + 1} complete: ✓ {success_count} succeeded, ✗ {fail_count} failed")

                    # Add failed tickers
                    for ticker in batch_tickers:
                        if ticker not in batch_results:
                            failed_tickers.append(ticker)

                except Exception as e:
                    logger.error(f"Batch {batch_num + 1} failed: {str(e)}")
                    failed_tickers.extend(batch_tickers)

            else:
                # For incremental updates, use concurrent processing per ticker
                # (since each ticker may have different date ranges)
                with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    futures = {}

                    for ticker in batch_tickers:
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

                    # Collect results as they complete
                    for future in as_completed(futures):
                        ticker = futures[future]
                        try:
                            ticker_symbol, processed_df, success, msg = future.result()

                            if success and not processed_df.empty:
                                ticker_data[ticker_symbol] = processed_df
                                logger.info(f"✓ {ticker_symbol}: {msg}")
                            else:
                                failed_tickers.append(ticker_symbol)
                                logger.warning(f"✗ {ticker_symbol}: {msg}")

                        except Exception as e:
                            logger.error(f"✗ {ticker}: {str(e)}")
                            failed_tickers.append(ticker)

                logger.info(f"Batch {batch_num + 1} complete")

        # Generate Excel report
        if ticker_data:
            logger.info("\n" + "=" * 80)
            logger.info("Generating Excel Report...")
            logger.info("=" * 80)

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

        # Show cache info
        cache_info = self.cache.get_cache_info()
        if not cache_info.empty:
            logger.info("\n" + "=" * 80)
            logger.info("CACHE INFO")
            logger.info("=" * 80)
            logger.info(f"Cached tickers: {len(cache_info)}")
            logger.info(f"Total cached records: {cache_info['records'].sum()}")

        logger.info("\nScreener completed!")


def main():
    """Entry point"""
    parser = argparse.ArgumentParser(
        description='NSE Stock Screener - Delivery + Volume + 30WMA Analysis (OPTIMIZED)'
    )
    parser.add_argument(
        '--mode',
        choices=['auto', 'initial', 'incremental'],
        default='auto',
        help='Run mode: auto (detect), initial (full load), incremental (updates only)'
    )
    parser.add_argument(
        '--clear-cache',
        action='store_true',
        help='Clear all cached data before running'
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

    try:
        screener = StockScreener(
            mode=args.mode,
            batch_size=args.batch_size,
            max_workers=args.max_workers,
            skip_financials=args.skip_financials
        )

        if args.clear_cache:
            logger.info("Clearing cache...")
            screener.cache.clear_cache()

        screener.run()
    except KeyboardInterrupt:
        logger.info("\nScreener interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
