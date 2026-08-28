"""
NSE Data Fetcher Module
Fetches historical data from NSE India archives (Bhav Copy + Delivery Data)
Supports both single ticker and batch (multi-ticker) modes
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
from datetime import datetime, timedelta
import time
import logging
import io
from collections import OrderedDict, Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _make_session():
    """Session with retry/backoff for transient network failures.

    Every network call in this module previously failed permanently on the
    first timeout/connection error/5xx response, even though these are
    common and often transient against NSE's servers - a single flaky
    request could fail an entire ticker (or a whole day's bhav copy) that
    would have succeeded on a retry a second later.
    """
    session = requests.Session()
    try:
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=['GET'],
        )
    except TypeError:
        # Older urllib3 (<1.26) uses method_whitelist instead of allowed_methods
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            method_whitelist=['GET'],
        )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('https://', adapter)
    session.mount('http://', adapter)
    return session


class NSEDataFetcher:
    """Fetch data from NSE India archives"""

    def __init__(self):
        self.base_url = "https://www.nseindia.com"
        self.archives_url = "https://archives.nseindia.com"
        self.session = _make_session()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'keep-alive',
        }
        # Cache bhav copy data to avoid re-fetching. Bounded LRU (not a plain
        # dict) - a multi-year initial backfill can pull in ~250 dates/year,
        # each holding a full-market bhav copy (~2000 rows) in memory for the
        # life of the process; an unbounded dict would keep growing for the
        # whole run with no eviction.
        #
        # SIZING MATTERS: the run scans the same date list once per ticker
        # batch, in the same order. If capacity is even one short of the number
        # of dates, LRU degenerates to a 100% miss rate — a sequential scan of
        # N+1 items through an N-slot LRU evicts each entry just before it is
        # next needed. A 730-day window is 501 trading dates, so a 500-slot
        # cache would re-download the entire history for all 22 batches
        # (~11,000 bhav copies instead of ~501). Keep this comfortably above
        # the trading-date count for the largest window in use.
        self._bhavcopy_cache_max = 700
        self.cache = OrderedDict()

        # NSE Trading Holidays (update annually)
        # Source: https://www.nseindia.com/regulations/trading-holidays
        self.trading_holidays_2025 = {
            datetime(2025, 1, 26),   # Republic Day
            datetime(2025, 3, 14),   # Mahashivratri
            datetime(2025, 3, 31),   # Holi
            datetime(2025, 4, 10),   # Mahavir Jayanti
            datetime(2025, 4, 14),   # Dr. Ambedkar Jayanti
            datetime(2025, 4, 18),   # Good Friday
            datetime(2025, 5, 1),    # Maharashtra Day
            datetime(2025, 8, 15),   # Independence Day
            datetime(2025, 8, 27),   # Ganesh Chaturthi
            datetime(2025, 10, 2),   # Gandhi Jayanti
            datetime(2025, 10, 21),  # Dussehra
            datetime(2025, 11, 1),   # Diwali (Laxmi Pujan)
            datetime(2025, 11, 5),   # Guru Nanak Jayanti
            datetime(2025, 12, 25),  # Christmas
        }

        # 2026 NSE Trading Holidays
        # Source: https://www.nseindia.com/regulations/trading-holidays
        # NOTE: Verify these dates against the official NSE calendar for 2026
        self.trading_holidays_2026 = {
            datetime(2026, 1, 26),   # Republic Day
            datetime(2026, 3, 3),    # Mahashivratri
            datetime(2026, 3, 20),   # Holi
            datetime(2026, 3, 30),   # Id-Ul-Fitr (Eid)
            datetime(2026, 4, 3),    # Good Friday
            datetime(2026, 4, 14),   # Dr. Ambedkar Jayanti
            datetime(2026, 5, 1),    # Maharashtra Day
            datetime(2026, 6, 5),    # Eid-Ul-Adha (Bakri Eid)
            datetime(2026, 8, 15),   # Independence Day
            datetime(2026, 8, 17),   # Ganesh Chaturthi
            datetime(2026, 10, 2),   # Gandhi Jayanti
            datetime(2026, 10, 9),   # Dussehra
            datetime(2026, 10, 20),  # Diwali (Laxmi Pujan)
            datetime(2026, 10, 21),  # Diwali Balipratipada
            datetime(2026, 11, 24),  # Guru Nanak Jayanti
            datetime(2026, 12, 25),  # Christmas
        }

        # Combined holidays for all supported years
        self.trading_holidays = self.trading_holidays_2025 | self.trading_holidays_2026
        self._holiday_calendar_years = {2025, 2026}
        self._warned_missing_holiday_years = set()

        # Weekends (Saturday=5, Sunday=6 are non-trading days)
        self.non_trading_weekdays = {5, 6}

    def get_stock_data(self, symbol, from_date=None, to_date=None):
        """
        Fetch historical stock data from NSE

        Args:
            symbol: Stock symbol (e.g., 'RELIANCE')
            from_date: Start date (datetime object or string 'DD-MM-YYYY')
            to_date: End date (datetime object or string 'DD-MM-YYYY')

        Returns:
            DataFrame with columns: date, close, traded_quantity, delivery_quantity
        """
        if to_date is None:
            to_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        if from_date is None:
            from_date = to_date - timedelta(days=365)

        # Convert to datetime objects if strings
        if isinstance(from_date, str):
            from_date = datetime.strptime(from_date, "%d-%m-%Y")
        if isinstance(to_date, str):
            to_date = datetime.strptime(to_date, "%d-%m-%Y")

        logger.info(f"Fetching data for {symbol} from {from_date.date()} to {to_date.date()}")

        # Get list of trading dates to fetch
        dates_to_fetch = self._get_trading_dates(from_date, to_date)
        logger.debug(f"_get_trading_dates() returned {len(dates_to_fetch)} dates")
        logger.debug(f"First date: {dates_to_fetch[0].date() if dates_to_fetch else 'None'}")
        logger.debug(f"Last date: {dates_to_fetch[-1].date() if dates_to_fetch else 'None'}")

        all_data = []

        for date in dates_to_fetch:
            logger.debug(f"Processing date: {date.date()}")
            try:
                # Fetch bhav copy for this date (with caching)
                bhav_df = self._get_or_fetch_bhavcopy(date)

                if not bhav_df.empty:
                    # Filter for the specific symbol
                    stock_data = bhav_df[bhav_df['SYMBOL'] == symbol]
                    if not stock_data.empty:
                        all_data.append(stock_data)

            except Exception as e:
                logger.debug(f"No data for {date.date()}: {str(e)}")
                continue

        if all_data:
            combined_df = pd.concat(all_data, ignore_index=True)

            # Standardize column names
            df_processed = pd.DataFrame({
                'date': pd.to_datetime(combined_df['DATE1']).dt.normalize(),
                'close': pd.to_numeric(combined_df['CLOSE_PRICE'], errors='coerce'),
                'high': pd.to_numeric(combined_df.get('HIGH_PRICE', combined_df.get('CLOSE_PRICE')), errors='coerce'),
                'low': pd.to_numeric(combined_df.get('LOW_PRICE', combined_df.get('CLOSE_PRICE')), errors='coerce'),
                'traded_quantity': pd.to_numeric(combined_df['TTL_TRD_QNTY'], errors='coerce'),
                'delivery_quantity': pd.to_numeric(combined_df['DELIV_QTY'], errors='coerce')
            })

            df_processed = df_processed.sort_values('date').reset_index(drop=True)
            logger.info(f"Successfully fetched {len(df_processed)} trading days for {symbol}")
            return df_processed
        else:
            logger.warning(f"No data found for {symbol}")
            return pd.DataFrame()

    def _get_or_fetch_bhavcopy(self, date):
        """Get bhav copy from cache or fetch if not cached"""
        date_key = date.strftime("%Y%m%d")

        if date_key in self.cache:
            self.cache.move_to_end(date_key)
            return self.cache[date_key]

        # Fetch bhav copy with delivery data
        df = self._fetch_combined_bhavcopy(date)

        if not df.empty:
            self.cache[date_key] = df
            if len(self.cache) > self._bhavcopy_cache_max:
                self.cache.popitem(last=False)

        return df

    def _fetch_combined_bhavcopy(self, date):
        """
        Fetch and combine bhav copy with delivery data for a specific date

        Returns DataFrame with columns: SYMBOL, DATE1, CLOSE, TOTTRDQTY, DELIVQTY
        """
        try:
            date_str = date.strftime("%d%m%Y")

            # Step 1: Fetch main bhav copy (price and volume data)
            bhav_url = f"{self.archives_url}/products/content/sec_bhavdata_full_{date_str}.csv"

            logger.debug(f"Fetching bhav copy for {date.date()}...")
            response = self.session.get(bhav_url, headers=self.headers, timeout=15)

            if response.status_code != 200:
                return pd.DataFrame()

            # Parse bhav copy CSV
            bhav_df = pd.read_csv(io.StringIO(response.text), skipinitialspace=True)

            # Normalize column names (remove extra spaces)
            bhav_df.columns = bhav_df.columns.str.strip()

            # Filter for EQ series only
            if 'SERIES' in bhav_df.columns:
                bhav_df = bhav_df[bhav_df['SERIES'] == 'EQ']

            # Step 2: Check if DELIV_QTY exists in bhav copy, else fetch from delivery file
            if 'DELIV_QTY' not in bhav_df.columns:
                delivery_url = f"{self.archives_url}/archives/equities/mto/MTO_{date_str}.DAT"

                time.sleep(0.2)  # Small delay between requests
                del_response = self.session.get(delivery_url, headers=self.headers, timeout=15)

                if del_response.status_code == 200:
                    # Parse delivery data
                    delivery_df = self._parse_delivery_file(del_response.text)

                    # Merge delivery data with bhav copy
                    bhav_df = bhav_df.merge(delivery_df, on='SYMBOL', how='left')
                else:
                    # No delivery data available, set to 0
                    bhav_df['DELIV_QTY'] = 0

            # Add date column
            bhav_df['DATE1'] = date

            # Select and rename columns we need
            required_cols = {
                'SYMBOL': 'SYMBOL',
                'CLOSE_PRICE': 'CLOSE_PRICE',
                'HIGH': 'HIGH_PRICE',
                'LOW': 'LOW_PRICE',
                'TTL_TRD_QNTY': 'TTL_TRD_QNTY',
                'DELIV_QTY': 'DELIV_QTY',
                'DATE1': 'DATE1'
            }

            # Check which columns exist
            available_cols = {}
            for src, dst in required_cols.items():
                if src in bhav_df.columns:
                    available_cols[src] = dst

            result_df = bhav_df[list(available_cols.keys())].copy()
            result_df.columns = list(available_cols.values())

            # Fill missing DELIV_QTY with 0
            if 'DELIV_QTY' not in result_df.columns:
                result_df['DELIV_QTY'] = 0
            else:
                result_df['DELIV_QTY'] = result_df['DELIV_QTY'].fillna(0)

            logger.debug(f"✓ Fetched {len(result_df)} stocks for {date.date()}")
            return result_df

        except Exception as e:
            # This is a whole-day bhav-copy fetch failure (affects every ticker
            # for that date), not a per-symbol miss - worth surfacing above
            # debug level so a systematic NSE outage/format change is visible
            # in the default INFO-level log instead of silently producing a
            # day of missing data across the entire universe.
            logger.warning(f"Error fetching combined bhavcopy for {date.date()}: {str(e)}")
            return pd.DataFrame()

    def _parse_delivery_file(self, content):
        """
        Parse NSE delivery data file (.DAT format)

        Format: Each line is comma-separated with delivery quantities
        """
        lines = content.strip().split('\n')
        data = []

        for line in lines:
            try:
                # Split by comma
                parts = [p.strip() for p in line.split(',')]

                # Format varies, but typically:
                # Record Type, Symbol, Series, QtyTraded, DelivQty, DelivPer
                if len(parts) >= 5:
                    # Try different column positions
                    if parts[0].upper() == '20':  # Equity delivery record type
                        symbol = parts[1].upper()
                        # Delivery quantity is typically in column 4 or 6
                        try:
                            deliv_qty = float(parts[4]) if parts[4] else 0
                        except (ValueError, IndexError):
                            try:
                                deliv_qty = float(parts[6]) if len(parts) > 6 and parts[6] else 0
                            except (ValueError, IndexError):
                                deliv_qty = 0

                        data.append({'SYMBOL': symbol, 'DELIV_QTY': deliv_qty})

            except Exception as e:
                continue

        return pd.DataFrame(data)

    def _get_trading_dates(self, from_date, to_date):
        """
        Generate list of actual trading dates (excluding weekends and NSE holidays)
        """
        dates = []
        current_date = from_date

        # The holiday calendar is hand-maintained per calendar year (see
        # __init__). Silently treating an unlisted year as "no holidays"
        # would make every trading-day count/window past 2026 slightly
        # wrong without any indication why - warn once per missing year so
        # it's visible instead of a subtle off-by-a-few-days discrepancy.
        for year in range(from_date.year, to_date.year + 1):
            if year not in self._holiday_calendar_years and year not in self._warned_missing_holiday_years:
                self._warned_missing_holiday_years.add(year)
                logger.warning(
                    f"No NSE trading holiday calendar defined for {year} - "
                    f"trading date calculations for that year will not exclude holidays"
                )

        while current_date <= to_date:
            # Skip weekends (Saturday=5, Sunday=6)
            if current_date.weekday() not in self.non_trading_weekdays:
                # Skip NSE trading holidays (compare date objects without time)
                current_date_only = datetime(current_date.year, current_date.month, current_date.day)
                if current_date_only not in self.trading_holidays:
                    # Normalize to date-only — prevents time-of-day from
                    # polluting caching/deduplication when from_date is
                    # constructed via datetime.now()
                    dates.append(datetime(current_date.year, current_date.month, current_date.day))
            current_date += timedelta(days=1)

        return dates

    def fetch_nifty_data(self, from_date=None, to_date=None):
        """
        Fetch NIFTY 50 proxy data using NIFTYBEES ETF from bhav copy.
        NIFTYBEES tracks NIFTY 50 closely and is available in daily bhav copy data.

        Args:
            from_date: Start date (datetime or string 'DD-MM-YYYY')
            to_date: End date (datetime or string 'DD-MM-YYYY')

        Returns:
            DataFrame with date and close columns, or empty DataFrame on failure
        """
        logger.info("Fetching NIFTY 50 proxy (NIFTYBEES) data...")
        nifty_df = self.get_stock_data('NIFTYBEES', from_date=from_date, to_date=to_date)
        if not nifty_df.empty:
            # Keep only date and close for RS calculation
            nifty_df = nifty_df[['date', 'close']].copy()
            logger.info(f"NIFTY proxy (NIFTYBEES): {len(nifty_df)} days")
        else:
            logger.warning("Could not fetch NIFTYBEES data for NIFTY proxy")
        return nifty_df

    def fetch_52week_batch(self, tickers: List[str]) -> Dict[str, Dict]:
        """
        Fetch authoritative 52-week high/low data AND fundamental data from NSE quote API.

        Args:
            tickers: List of stock symbols

        Returns:
            Dict mapping ticker -> {52w_high, 52w_low, 52w_high_date, 52w_low_date,
                                     pe_ratio, sector_pe}
        """
        logger.info(f"Fetching 52-week + fundamental data from NSE quote API for {len(tickers)} tickers...")

        # Use a dedicated session (not self.session) to avoid cookie conflicts
        # when run in parallel - mirrors fetch_promoter_holding_batch and
        # fetch_financial_results_batch, which already do this for the same
        # reason. Sharing self.session across ThreadPoolExecutor workers here
        # was a data race on the session's cookie jar.
        quote_session = _make_session()
        try:
            quote_session.get(self.base_url, headers=self.headers, timeout=10)
        except Exception as e:
            logger.warning(f"Could not establish NSE session for 52W fetch: {e}")
            return {}

        results = {}

        # Why-it-failed tally. Every per-symbol failure used to go to
        # logger.debug, which is off at the default INFO level — so a run where
        # all 1061 tickers failed printed "0/1061 succeeded" and nothing else,
        # with 1061 exceptions caught and discarded. The reason has to survive
        # to the summary line or there is no way to diagnose it.
        failures = Counter()

        def _fetch_single_quote(symbol):
            try:
                time.sleep(0.2)  # Rate limiting: 200ms between requests
                url = f"{self.base_url}/api/quote-equity?symbol={symbol}"
                response = quote_session.get(url, headers=self.headers, timeout=10)
                if response.status_code != 200:
                    failures[f"HTTP {response.status_code}"] += 1
                if response.status_code == 200:
                    data = response.json()
                    week_52 = data.get('priceInfo', {}).get('weekHighLow', {})
                    if week_52 and 'min' in week_52 and 'max' in week_52:
                        result = {
                            '52w_high': week_52['max'],
                            '52w_low': week_52['min'],
                            '52w_high_date': week_52.get('maxDate', ''),
                            '52w_low_date': week_52.get('minDate', ''),
                        }

                        # Extract PE ratio and related fundamentals from metadata
                        metadata = data.get('metadata', {})
                        result['pe_ratio'] = metadata.get('pdSymbolPe', None)
                        result['sector_pe'] = metadata.get('pdSectorPe', None)

                        # Try numeric conversion
                        for key in ['pe_ratio', 'sector_pe']:
                            if result[key] is not None:
                                try:
                                    result[key] = float(result[key])
                                except (ValueError, TypeError):
                                    result[key] = None

                        return symbol, result
                    failures['200 but no weekHighLow in payload'] += 1
                return symbol, None
            except Exception as e:
                failures[type(e).__name__] += 1
                logger.debug(f"Quote fetch failed for {symbol}: {e}")
                return symbol, None

        # Step 2: Threaded fetch with conservative concurrency
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(_fetch_single_quote, t): t for t in tickers}
            for future in as_completed(futures):
                try:
                    symbol, data = future.result()
                    if data:
                        results[symbol] = data
                except Exception as e:
                    failures[f"future:{type(e).__name__}"] += 1

        self._log_fetch_outcome("Quote", len(results), len(tickers), failures)
        return results

    @staticmethod
    def _log_fetch_outcome(label, n_ok, n_total, failures):
        """Report a batch fetch result, including WHY it failed.

        Logged at WARNING (not INFO) when nothing succeeded, so a total
        blackout cannot scroll past unnoticed in a long run.
        """
        msg = f"{label} data fetched: {n_ok}/{n_total} tickers succeeded"
        if failures:
            top = ', '.join(f"{c}x {r}" for r, c in failures.most_common(4))
            msg += f" | failures: {top}"
        if n_ok == 0 and n_total > 0:
            logger.warning(f"{msg}  <-- NOTHING succeeded; the dependent columns will be blank")
        elif n_ok < n_total * 0.5:
            logger.warning(msg)
        else:
            logger.info(msg)

    def fetch_promoter_holding_batch(self, tickers: List[str]) -> Dict[str, Dict]:
        """
        Fetch promoter shareholding data from NSE corp-info API.
        Shows latest promoter % and quarter-over-quarter change.

        Uses: /api/corp-info?symbol=X&corpType=shp&market=equities
        Returns quarterly shareholding pattern with promoter %.

        Args:
            tickers: List of stock symbols

        Returns:
            Dict mapping ticker -> {promoter_pct, promoter_pct_prev, promoter_change, quarter}
        """
        logger.info(f"Fetching promoter holding data for {len(tickers)} tickers...")

        # Use a dedicated session to avoid cookie conflicts when run in parallel
        promo_session = _make_session()
        try:
            promo_session.get(self.base_url, headers=self.headers, timeout=10)
        except Exception as e:
            logger.warning(f"Could not establish NSE session for promoter data: {e}")
            return {}

        results = {}
        failures = Counter()

        def _fetch_single_promoter(symbol):
            try:
                time.sleep(0.15)  # Rate limiting
                url = f"{self.base_url}/api/corp-info?symbol={symbol}&corpType=shp&market=equities"
                response = promo_session.get(url, headers=self.headers, timeout=15)
                if response.status_code != 200:
                    failures[f"HTTP {response.status_code}"] += 1
                if response.status_code == 200:
                    data = response.json()

                    if not data or not isinstance(data, dict):
                        return symbol, None

                    # Keys are quarter end dates like "31-Dec-2024", "31-Mar-2025"
                    # Sort to get most recent quarters
                    from datetime import datetime as dt
                    quarters = []
                    for date_key in data.keys():
                        try:
                            q_date = dt.strptime(date_key, "%d-%b-%Y")
                            quarters.append((q_date, date_key))
                        except ValueError:
                            continue

                    if not quarters:
                        return symbol, None

                    quarters.sort(reverse=True)  # Most recent first

                    # Extract promoter % from latest quarter
                    latest_key = quarters[0][1]
                    latest_entries = data[latest_key]

                    promoter_pct = None
                    for entry in latest_entries:
                        if 'Promoter & Promoter Group' in entry:
                            try:
                                promoter_pct = float(entry['Promoter & Promoter Group'].strip())
                            except (ValueError, TypeError):
                                pass
                            break

                    # Get previous quarter for change calculation
                    promoter_pct_prev = None
                    if len(quarters) >= 2:
                        prev_key = quarters[1][1]
                        prev_entries = data[prev_key]
                        for entry in prev_entries:
                            if 'Promoter & Promoter Group' in entry:
                                try:
                                    promoter_pct_prev = float(entry['Promoter & Promoter Group'].strip())
                                except (ValueError, TypeError):
                                    pass
                                break

                    promoter_change = None
                    if promoter_pct is not None and promoter_pct_prev is not None:
                        promoter_change = promoter_pct - promoter_pct_prev

                    return symbol, {
                        'promoter_pct': promoter_pct,
                        'promoter_pct_prev': promoter_pct_prev,
                        'promoter_change': promoter_change,
                        'quarter': latest_key,
                    }
                return symbol, None
            except Exception as e:
                failures[type(e).__name__] += 1
                logger.debug(f"Promoter data fetch failed for {symbol}: {e}")
                return symbol, None

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(_fetch_single_promoter, t): t for t in tickers}
            for future in as_completed(futures):
                try:
                    symbol, data = future.result()
                    if data and data.get('promoter_pct') is not None:
                        results[symbol] = data
                except Exception as e:
                    failures[f"future:{type(e).__name__}"] += 1

        self._log_fetch_outcome("Promoter", len(results), len(tickers), failures)
        return results

    def fetch_financial_results_batch(self, tickers: List[str]) -> Dict[str, Dict]:
        """
        Fetch quarterly financial results from NSE XBRL filings.
        Extracts profit after tax from the latest quarterly XBRL filing and computes YoY growth.

        Note: This fetches 2 XBRL files per ticker (latest + same quarter last year),
        so it's the slowest fetch operation. Runs with conservative concurrency.

        Args:
            tickers: List of stock symbols

        Returns:
            Dict mapping ticker -> {latest_profit, yoy_prev_profit, profit_growth_yoy, quarter}
        """
        logger.info(f"Fetching financial results for {len(tickers)} tickers...")

        # Use a dedicated session to avoid cookie conflicts when run in parallel
        fin_session = _make_session()
        try:
            fin_session.get(self.base_url, headers=self.headers, timeout=10)
        except Exception as e:
            logger.warning(f"Could not establish NSE session for financial data: {e}")
            return {}

        results = {}
        failures = Counter()

        def _extract_profit_from_xbrl(xbrl_url):
            """Extract ProfitLossForPeriod from XBRL XML"""
            try:
                import re
                response = fin_session.get(xbrl_url, headers=self.headers, timeout=15)
                if response.status_code != 200:
                    return None
                content = response.text

                # Capture both the value AND its contextRef, since a single XBRL
                # doc typically contains the SAME tag multiple times under
                # different contexts (current quarter, YTD/cumulative, prior
                # year, consolidated vs standalone). Blindly taking the first
                # match risks silently picking a YTD or prior-year figure and
                # reporting it as "this quarter's profit", which would corrupt
                # profit_growth_yoy with a bogus comparison.
                tag_pattern = re.compile(
                    r'<([a-zA-Z0-9:_]*ProfitLossForPeriod)\b[^>]*contextRef="([^"]+)"[^>]*>([^<]+)<',
                    re.IGNORECASE
                )
                candidates = [(ctx, val) for _, ctx, val in tag_pattern.findall(content)]
                if not candidates:
                    return None

                # Prefer a context that does NOT look like a cumulative/YTD or
                # prior-year period - those keywords commonly appear in NSE
                # XBRL contextRef ids (e.g. "OneD_PreviousYear", "Cumulative").
                # Standalone > consolidated is NOT assumed here; only period
                # scope is filtered, matching what the caller actually wants
                # (this quarter's standalone reading of ProfitLossForPeriod).
                exclude_kw = ('previousyear', 'prioryear', 'cumulative', 'ytd')
                filtered = [(ctx, val) for ctx, val in candidates
                            if not any(kw in ctx.lower() for kw in exclude_kw)]
                chosen = filtered if filtered else candidates

                if len(chosen) > 1:
                    logger.debug(
                        f"Multiple ProfitLossForPeriod contexts found in {xbrl_url}, "
                        f"using first non-cumulative/non-prior-year match: {chosen[0][0]}"
                    )

                return float(chosen[0][1])
            except Exception:
                pass
            return None

        def _fetch_single_financials(symbol):
            try:
                time.sleep(0.15)  # Rate limiting
                url = f"{self.base_url}/api/corporates-financial-results?index=equities&symbol={symbol}&period=Quarterly"
                response = fin_session.get(url, headers=self.headers, timeout=15)
                if response.status_code != 200:
                    failures[f"HTTP {response.status_code}"] += 1
                    return symbol, None

                data = response.json()
                if not data or not isinstance(data, list) or len(data) == 0:
                    return symbol, None

                # Prefer Consolidated results over Non-Consolidated
                consolidated = [d for d in data if d.get('consolidated') == 'Consolidated']
                non_consolidated = [d for d in data if d.get('consolidated') != 'Consolidated']
                # Use consolidated if available, else fall back to non-consolidated
                results_list = consolidated if consolidated else non_consolidated

                if not results_list:
                    return symbol, None

                latest = results_list[0]
                quarter_label = latest.get('relatingTo', '')
                fin_year = latest.get('financialYear', '')
                xbrl_url = latest.get('xbrl', '')

                if not xbrl_url or xbrl_url == '-':
                    return symbol, None

                # Get profit from latest quarter
                time.sleep(0.2)
                latest_profit = _extract_profit_from_xbrl(xbrl_url)

                # Find same quarter from EXACTLY one year earlier for YoY
                # comparison. Matching on "any different financialYear" would
                # silently accept a 2+ year-old quarter if the latest filing
                # for the immediately preceding year is missing/delisted from
                # the API response, understating or overstating growth against
                # a period that isn't actually a year ago.
                def _parse_start_year(fy):
                    # financialYear is typically formatted like "2024-2025"
                    try:
                        return int(str(fy).split('-')[0].strip())
                    except (ValueError, IndexError):
                        return None

                latest_start_year = _parse_start_year(fin_year)

                yoy_prev_profit = None
                for prev in results_list[1:]:
                    prev_fin_year = prev.get('financialYear', '')
                    prev_start_year = _parse_start_year(prev_fin_year)
                    is_one_year_prior = (
                        latest_start_year is not None and prev_start_year is not None
                        and prev_start_year == latest_start_year - 1
                    )
                    if prev.get('relatingTo', '') == quarter_label and is_one_year_prior:
                        prev_xbrl = prev.get('xbrl', '')
                        if prev_xbrl and prev_xbrl != '-':
                            time.sleep(0.2)
                            yoy_prev_profit = _extract_profit_from_xbrl(prev_xbrl)
                        break

                profit_growth = None
                if latest_profit is not None and yoy_prev_profit is not None and yoy_prev_profit != 0:
                    profit_growth = ((latest_profit - yoy_prev_profit) / abs(yoy_prev_profit)) * 100

                return symbol, {
                    'latest_profit': latest_profit,
                    'yoy_prev_profit': yoy_prev_profit,
                    'profit_growth_yoy': profit_growth,
                    'quarter': f"{quarter_label} ({fin_year})",
                }
            except Exception as e:
                logger.debug(f"Financial data fetch failed for {symbol}: {e}")
                return symbol, None

        # Moderate concurrency — each ticker makes 2-3 HTTP requests
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(_fetch_single_financials, t): t for t in tickers}
            for future in as_completed(futures):
                try:
                    symbol, data = future.result()
                    if data and data.get('latest_profit') is not None:
                        results[symbol] = data
                except Exception as e:
                    failures[f"future:{type(e).__name__}"] += 1

        self._log_fetch_outcome("Financial", len(results), len(tickers), failures)
        return results

    def get_stock_data_batch(self, symbols: List[str], from_date=None, to_date=None) -> Dict[str, pd.DataFrame]:
        """
        Fetch historical stock data for multiple symbols in batch mode (OPTIMIZED)
        This method fetches each date's bhav copy once and extracts all symbols from it

        Args:
            symbols: List of stock symbols (e.g., ['RELIANCE', 'TCS', 'INFY'])
            from_date: Start date (datetime object or string 'DD-MM-YYYY')
            to_date: End date (datetime object or string 'DD-MM-YYYY')

        Returns:
            Dictionary mapping symbol -> DataFrame with columns: date, close, traded_quantity, delivery_quantity
        """
        if to_date is None:
            to_date = datetime.now()
        if from_date is None:
            from_date = to_date - timedelta(days=365)

        # Convert to datetime objects if strings
        if isinstance(from_date, str):
            from_date = datetime.strptime(from_date, "%d-%m-%Y")
        if isinstance(to_date, str):
            to_date = datetime.strptime(to_date, "%d-%m-%Y")

        logger.info(f"Batch fetching data for {len(symbols)} symbols from {from_date.date()} to {to_date.date()}")

        # Get list of trading dates to fetch
        dates_to_fetch = self._get_trading_dates(from_date, to_date)
        logger.info(f"Need to fetch {len(dates_to_fetch)} trading days")

        # Initialize result dictionary
        result_data = {symbol: [] for symbol in symbols}

        # Fetch bhav copy for each date (these are already cached in self.cache)
        symbols_set = set(symbols)
        for idx, date in enumerate(dates_to_fetch, 1):
            if idx % 10 == 0 or idx == 1:
                logger.info(f"Fetching date {idx}/{len(dates_to_fetch)}: {date.date()}")

            date_key = date.strftime("%Y%m%d")
            was_cached = date_key in self.cache

            try:
                # Fetch bhav copy for this date (with caching)
                bhav_df = self._get_or_fetch_bhavcopy(date)

                if not bhav_df.empty:
                    # Group once per date instead of re-scanning the full
                    # bhav_df (all ~2000 NSE symbols) once per requested
                    # symbol - the old `bhav_df[bhav_df['SYMBOL'] == symbol]`
                    # loop was O(dates * symbols * rows_per_date), which
                    # dominated runtime for large ticker universes.
                    for symbol, stock_data in bhav_df[bhav_df['SYMBOL'].isin(symbols_set)].groupby('SYMBOL'):
                        result_data[symbol].append(stock_data)

                # Small delay to be nice to NSE servers (only when actually fetching,
                # i.e. this date wasn't already in the cache before this call)
                if not was_cached:
                    time.sleep(0.1)

            except Exception as e:
                logger.debug(f"No data for {date.date()}: {str(e)}")
                continue

        # Process results into DataFrames
        processed_results = {}
        for symbol in symbols:
            if result_data[symbol]:
                combined_df = pd.concat(result_data[symbol], ignore_index=True)

                # Standardize column names
                df_processed = pd.DataFrame({
                    'date': pd.to_datetime(combined_df['DATE1']).dt.normalize(),
                    'close': pd.to_numeric(combined_df['CLOSE_PRICE'], errors='coerce'),
                    'high': pd.to_numeric(combined_df.get('HIGH_PRICE', combined_df.get('CLOSE_PRICE')), errors='coerce'),
                    'low': pd.to_numeric(combined_df.get('LOW_PRICE', combined_df.get('CLOSE_PRICE')), errors='coerce'),
                    'traded_quantity': pd.to_numeric(combined_df['TTL_TRD_QNTY'], errors='coerce'),
                    'delivery_quantity': pd.to_numeric(combined_df['DELIV_QTY'], errors='coerce')
                })

                df_processed = df_processed.sort_values('date').reset_index(drop=True)
                processed_results[symbol] = df_processed
                logger.info(f"✓ {symbol}: {len(df_processed)} trading days")
            else:
                logger.warning(f"✗ {symbol}: No data found")
                processed_results[symbol] = pd.DataFrame()

        return processed_results
