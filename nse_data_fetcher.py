"""
NSE Data Fetcher Module
Fetches historical data from NSE India archives (Bhav Copy + Delivery Data)
Supports both single ticker and batch (multi-ticker) modes
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
import time
import logging
import io
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class NSEDataFetcher:
    """Fetch data from NSE India archives"""

    def __init__(self):
        self.base_url = "https://www.nseindia.com"
        self.archives_url = "https://archives.nseindia.com"
        self.session = requests.Session()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'keep-alive',
        }
        self.cache = {}  # Cache bhav copy data to avoid re-fetching

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

        # Weekends (Saturday=5, Sunday=6 are non-trading days)
        self.non_trading_weekdays = {5, 6}

    def get_stock_data(self, symbol, from_date=None, to_date=None, series="EQ"):
        """
        Fetch historical stock data from NSE

        Args:
            symbol: Stock symbol (e.g., 'RELIANCE')
            from_date: Start date (datetime object or string 'DD-MM-YYYY')
            to_date: End date (datetime object or string 'DD-MM-YYYY')
            series: Stock series (default 'EQ' for equity)

        Returns:
            DataFrame with columns: date, close, traded_quantity, delivery_quantity
        """
        if to_date is None:
            to_date = datetime.now()  # Today - will gracefully skip if not available
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
                'date': pd.to_datetime(combined_df['DATE1']),
                'close': combined_df['CLOSE_PRICE'].astype(float),
                'traded_quantity': combined_df['TTL_TRD_QNTY'].astype(float),
                'delivery_quantity': combined_df['DELIV_QTY'].astype(float)
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
            return self.cache[date_key]

        # Fetch bhav copy with delivery data
        df = self._fetch_combined_bhavcopy(date)

        if not df.empty:
            self.cache[date_key] = df

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
            logger.debug(f"Error fetching combined bhavcopy for {date.date()}: {str(e)}")
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
                    if parts[0].upper() in ['1', '2', '3']:  # Record type
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

        while current_date <= to_date:
            # Skip weekends (Saturday=5, Sunday=6)
            if current_date.weekday() not in self.non_trading_weekdays:
                # Skip NSE trading holidays (compare date objects without time)
                current_date_only = datetime(current_date.year, current_date.month, current_date.day)
                if current_date_only not in self.trading_holidays:
                    dates.append(current_date)
            current_date += timedelta(days=1)

        return dates

    def is_fno_stock(self, symbol):
        """
        Check if a stock is in F&O segment

        Args:
            symbol: Stock symbol

        Returns:
            bool: True if stock is in F&O, False otherwise
        """
        try:
            url = f"{self.base_url}/api/equity-stockIndices?index=SECURITIES%20IN%20F%26O"
            response = self.session.get(url, headers=self.headers, timeout=10)

            if response.status_code == 200:
                data = response.json()
                if 'data' in data:
                    fno_symbols = [stock['symbol'] for stock in data['data']]
                    return symbol in fno_symbols

            return False
        except Exception as e:
            logger.debug(f"Could not check F&O status for {symbol}: {str(e)}")
            return False

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
                                     pe_ratio, sector_pe, face_value}
        """
        logger.info(f"Fetching 52-week + fundamental data from NSE quote API for {len(tickers)} tickers...")

        # Step 1: Get session cookies by visiting NSE homepage
        try:
            self.session.get(self.base_url, headers=self.headers, timeout=10)
        except Exception as e:
            logger.warning(f"Could not establish NSE session for 52W fetch: {e}")
            return {}

        results = {}

        def _fetch_single_quote(symbol):
            try:
                time.sleep(0.2)  # Rate limiting: 200ms between requests
                url = f"{self.base_url}/api/quote-equity?symbol={symbol}"
                response = self.session.get(url, headers=self.headers, timeout=10)
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
                        result['face_value'] = metadata.get('pdFaceValue', None)

                        # Try numeric conversion
                        for key in ['pe_ratio', 'sector_pe', 'face_value']:
                            if result[key] is not None:
                                try:
                                    result[key] = float(result[key])
                                except (ValueError, TypeError):
                                    result[key] = None

                        return symbol, result
                return symbol, None
            except Exception as e:
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
                except Exception:
                    pass

        logger.info(f"Quote data fetched: {len(results)}/{len(tickers)} tickers succeeded")
        return results

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
        promo_session = requests.Session()
        try:
            promo_session.get(self.base_url, headers=self.headers, timeout=10)
        except Exception as e:
            logger.warning(f"Could not establish NSE session for promoter data: {e}")
            return {}

        results = {}

        def _fetch_single_promoter(symbol):
            try:
                time.sleep(0.15)  # Rate limiting
                url = f"{self.base_url}/api/corp-info?symbol={symbol}&corpType=shp&market=equities"
                response = promo_session.get(url, headers=self.headers, timeout=15)
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
                logger.debug(f"Promoter data fetch failed for {symbol}: {e}")
                return symbol, None

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(_fetch_single_promoter, t): t for t in tickers}
            for future in as_completed(futures):
                try:
                    symbol, data = future.result()
                    if data and data.get('promoter_pct') is not None:
                        results[symbol] = data
                except Exception:
                    pass

        logger.info(f"Promoter data fetched: {len(results)}/{len(tickers)} tickers succeeded")
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
        fin_session = requests.Session()
        try:
            fin_session.get(self.base_url, headers=self.headers, timeout=10)
        except Exception as e:
            logger.warning(f"Could not establish NSE session for financial data: {e}")
            return {}

        results = {}

        def _extract_profit_from_xbrl(xbrl_url):
            """Extract ProfitLossForPeriod from XBRL XML"""
            try:
                import re
                response = fin_session.get(xbrl_url, headers=self.headers, timeout=15)
                if response.status_code == 200:
                    content = response.text
                    matches = re.findall(r'<[^>]*ProfitLossForPeriod[^>]*>([^<]+)<', content, re.IGNORECASE)
                    if matches:
                        # First match is typically the quarterly standalone figure
                        return float(matches[0])
            except Exception:
                pass
            return None

        def _fetch_single_financials(symbol):
            try:
                time.sleep(0.15)  # Rate limiting
                url = f"{self.base_url}/api/corporates-financial-results?index=equities&symbol={symbol}&period=Quarterly"
                response = fin_session.get(url, headers=self.headers, timeout=15)
                if response.status_code != 200:
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

                # Find same quarter from previous year for YoY comparison
                yoy_prev_profit = None
                for prev in results_list[1:]:
                    if (prev.get('relatingTo', '') == quarter_label
                            and prev.get('financialYear', '') != fin_year):
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
                except Exception:
                    pass

        logger.info(f"Financial data fetched: {len(results)}/{len(tickers)} tickers succeeded")
        return results

    def get_stock_data_batch(self, symbols: List[str], from_date=None, to_date=None, series="EQ") -> Dict[str, pd.DataFrame]:
        """
        Fetch historical stock data for multiple symbols in batch mode (OPTIMIZED)
        This method fetches each date's bhav copy once and extracts all symbols from it

        Args:
            symbols: List of stock symbols (e.g., ['RELIANCE', 'TCS', 'INFY'])
            from_date: Start date (datetime object or string 'DD-MM-YYYY')
            to_date: End date (datetime object or string 'DD-MM-YYYY')
            series: Stock series (default 'EQ' for equity)

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
        for idx, date in enumerate(dates_to_fetch, 1):
            if idx % 10 == 0 or idx == 1:
                logger.info(f"Fetching date {idx}/{len(dates_to_fetch)}: {date.date()}")

            try:
                # Fetch bhav copy for this date (with caching)
                bhav_df = self._get_or_fetch_bhavcopy(date)

                if not bhav_df.empty:
                    # Extract data for all symbols at once
                    for symbol in symbols:
                        stock_data = bhav_df[bhav_df['SYMBOL'] == symbol]
                        if not stock_data.empty:
                            result_data[symbol].append(stock_data)

                # Small delay to be nice to NSE servers (only when actually fetching)
                if date.strftime("%Y%m%d") not in self.cache:
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
                    'date': pd.to_datetime(combined_df['DATE1']),
                    'close': combined_df['CLOSE_PRICE'].astype(float),
                    'traded_quantity': combined_df['TTL_TRD_QNTY'].astype(float),
                    'delivery_quantity': combined_df['DELIV_QTY'].astype(float)
                })

                df_processed = df_processed.sort_values('date').reset_index(drop=True)
                processed_results[symbol] = df_processed
                logger.info(f"✓ {symbol}: {len(df_processed)} trading days")
            else:
                logger.warning(f"✗ {symbol}: No data found")
                processed_results[symbol] = pd.DataFrame()

        return processed_results
