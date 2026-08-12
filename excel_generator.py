"""
Excel Generator Module
Generates formatted Excel reports with delivery analysis
"""

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class ExcelReportGenerator:
    """Generates Excel reports with delivery analysis"""

    def __init__(self, config):
        self.config = config
        self.lookback_days = config.get('lookback_days_display', 60)
        self.evaluation_days = config.get('evaluation_days', 45)
        self.date_format = config.get('date_format', 'DD-MM-YYYY')
        self.display_order = config.get('display_order', 'descending')

        # Load ticker metadata
        self.ticker_metadata = self._load_ticker_metadata()

        # Color definitions
        self.colors = {
            'purple': PatternFill(start_color=config['delivery_bins']['purple']['color'],
                                 end_color=config['delivery_bins']['purple']['color'],
                                 fill_type='solid'),
            'dark_green': PatternFill(start_color=config['delivery_bins']['dark_green']['color'],
                                     end_color=config['delivery_bins']['dark_green']['color'],
                                     fill_type='solid'),
            'light_green': PatternFill(start_color=config['delivery_bins']['light_green']['color'],
                                      end_color=config['delivery_bins']['light_green']['color'],
                                      fill_type='solid'),
            'blue': PatternFill(start_color=config['delivery_bins']['blue']['color'],
                               end_color=config['delivery_bins']['blue']['color'],
                               fill_type='solid'),
            'white': PatternFill(start_color=config['delivery_bins']['white']['color'],
                                end_color=config['delivery_bins']['white']['color'],
                                fill_type='solid'),
            'cream': PatternFill(start_color='FFFACD',  # Light cream/lemon chiffon
                                end_color='FFFACD',
                                fill_type='solid'),
            'grey': PatternFill(start_color=config.get('fno_grey_color', 'D3D3D3'),
                               end_color=config.get('fno_grey_color', 'D3D3D3'),
                               fill_type='solid'),
            'gold': PatternFill(start_color='FFD700',  # Gold for near 52W high
                               end_color='FFD700',
                               fill_type='solid')
        }

    def generate_report(self, ticker_data_dict, fno_tickers, output_filename=None, ticker_order=None):
        """
        Generate Excel report

        Args:
            ticker_data_dict: Dictionary {ticker: processed_dataframe}
            fno_tickers: List of FNO ticker symbols
            output_filename: Output file name (optional)
            ticker_order: List of tickers in desired order (optional, preserves input order)

        Returns:
            Path to generated Excel file
        """
        if output_filename is None:
            output_filename = f"Delivery_Report_{datetime.now().strftime('%Y-%m-%d')}.xlsx"

        logger.info(f"Generating Excel report: {output_filename}")

        wb = Workbook()
        ws = wb.active
        ws.title = "Report"

        # Build the main report
        self._build_report_sheet(ws, ticker_data_dict, fno_tickers, ticker_order)

        # Add Sector Analysis sheet
        ws_sector = wb.create_sheet("Sector Analysis")
        self._build_sector_analysis_sheet(ws_sector, ticker_data_dict)

        # Save workbook
        wb.save(output_filename)
        logger.info(f"Report saved: {output_filename}")

        return output_filename

    def _build_report_sheet(self, ws, ticker_data_dict, fno_tickers, ticker_order=None):
        """Build the main report sheet"""

        # Get trading dates from first ticker (all should have same dates)
        if not ticker_data_dict:
            logger.warning("No ticker data to process")
            return

        # Get all unique trading dates and take last N days
        all_dates = set()
        for df in ticker_data_dict.values():
            if not df.empty:
                all_dates.update(df['date'].tolist())

        trading_dates = sorted(list(all_dates))[-self.lookback_days:]

        if self.display_order == 'descending':
            trading_dates = sorted(trading_dates, reverse=True)
        else:
            trading_dates = sorted(trading_dates)

        # Header row setup
        current_row = 1

        # Commentary row
        ws.cell(row=current_row, column=1, value="Commentary")
        ws.merge_cells(start_row=current_row, start_column=1,
                      end_row=current_row, end_column=50)  # Extended to cover all columns before dates
        current_row += 1

        # Daily band totals header (optional)
        current_row = self._add_daily_band_totals(ws, current_row, trading_dates, ticker_data_dict)

        # Main header row
        header_row = current_row
        ws.cell(row=header_row, column=1, value="MCAP")  # Market Cap
        ws.cell(row=header_row, column=2, value="SEGMENT")  # Industry/Department
        ws.cell(row=header_row, column=3, value="STAGE")
        ws.cell(row=header_row, column=4, value="Wks Above WMA")
        ws.cell(row=header_row, column=5, value="Wks Below WMA")
        ws.cell(row=header_row, column=6, value="Price vs WMA")
        ws.cell(row=header_row, column=7, value="30WMA Slope")
        ws.cell(row=header_row, column=8, value="Cross Above")
        ws.cell(row=header_row, column=9, value="Vol Confirmed")
        ws.cell(row=header_row, column=10, value="Vol Ratio")
        ws.cell(row=header_row, column=11, value="52W High %")
        ws.cell(row=header_row, column=12, value="52W Low %")
        ws.cell(row=header_row, column=13, value="Near 52W High")
        ws.cell(row=header_row, column=14, value="RS vs NIFTY")
        ws.cell(row=header_row, column=15, value="RS Trend")
        ws.cell(row=header_row, column=16, value="RSI (14)")
        ws.cell(row=header_row, column=17, value="RSI Signal")

        # FUNDAMENTAL COLUMNS (NEW)
        ws.cell(row=header_row, column=18, value="PE Ratio")
        ws.cell(row=header_row, column=19, value="Sector PE")
        ws.cell(row=header_row, column=20, value="Price vs 200DMA")
        ws.cell(row=header_row, column=21, value="Promoter %")
        ws.cell(row=header_row, column=22, value="Profit Growth YoY")

        # MOMENTUM & DIVERGENCE COLUMNS
        ws.cell(row=header_row, column=23, value="ROC 1W")
        ws.cell(row=header_row, column=24, value="ROC 1M")
        ws.cell(row=header_row, column=25, value="ROC 3M")
        ws.cell(row=header_row, column=26, value="Momentum")
        ws.cell(row=header_row, column=27, value="Divergence")
        ws.cell(row=header_row, column=28, value="Squeeze")
        ws.cell(row=header_row, column=29, value="Squeeze Ratio")

        # Summary columns (MOVED BEFORE STOCK)
        summary_col_start = 30
        ws.cell(row=header_row, column=summary_col_start,
               value="Deliv Avg(10d)")
        ws.cell(row=header_row, column=summary_col_start + 1,
               value="Deliv Avg(30d)")
        ws.cell(row=header_row, column=summary_col_start + 2,
               value="Deliv Trend")
        ws.cell(row=header_row, column=summary_col_start + 3,
               value="Accum Score")
        ws.cell(row=header_row, column=summary_col_start + 4,
               value=f"Count (≥50%)/{self.evaluation_days}")
        ws.cell(row=header_row, column=summary_col_start + 5,
               value=f"Count (≥40%)/{self.evaluation_days}")
        # High volume counts (45 days)
        ws.cell(row=header_row, column=summary_col_start + 6,
               value=f"Count (≥50% + HighVol)/{self.evaluation_days}")
        ws.cell(row=header_row, column=summary_col_start + 7,
               value=f"Count (≥40% + HighVol)/{self.evaluation_days}")
        # Recent high volume counts (15 and 20 days)
        ws.cell(row=header_row, column=summary_col_start + 8,
               value="Count (≥50% + HighVol)/15d")
        ws.cell(row=header_row, column=summary_col_start + 9,
               value="Count (≥50% + HighVol)/20d")

        # SELL SIGNAL COLUMNS
        ws.cell(row=header_row, column=summary_col_start + 10,
               value="Exit Score")
        ws.cell(row=header_row, column=summary_col_start + 11,
               value="Cross Below WMA")
        ws.cell(row=header_row, column=summary_col_start + 12,
               value="Distribution Alert")
        ws.cell(row=header_row, column=summary_col_start + 13,
               value="Stage 3 Alert")
        ws.cell(row=header_row, column=summary_col_start + 14,
               value="Trend Break")
        ws.cell(row=header_row, column=summary_col_start + 15,
               value="Price vs 10MA")
        ws.cell(row=header_row, column=summary_col_start + 16,
               value="Deliv Momentum")
        ws.cell(row=header_row, column=summary_col_start + 17,
               value="Vol Spike Down")

        # STAGE 1 ALERT COLUMNS
        ws.cell(row=header_row, column=summary_col_start + 18,
               value="Stage 1 Alert")
        ws.cell(row=header_row, column=summary_col_start + 19,
               value="Stage 1 Strength")

        # STOCK column (after all columns)
        stock_col = summary_col_start + 20  # Column 50
        ws.cell(row=header_row, column=stock_col, value="STOCK")

        # Date columns (after STOCK)
        date_col_start = stock_col + 1  # Column 32
        for idx, date in enumerate(trading_dates):
            col = date_col_start + idx
            date_str = date.strftime(self._get_date_format())
            ws.cell(row=header_row, column=col, value=date_str)

        # Style header row - now extends to last date column
        last_col = date_col_start + len(trading_dates) - 1
        self._style_header_row(ws, header_row, last_col)

        # Add ticker rows (preserve order from ticker_order if provided)
        current_row = header_row + 1

        # Use ticker_order if provided, otherwise sort alphabetically
        if ticker_order:
            # Filter to only include tickers that have data
            tickers_to_process = [t for t in ticker_order if t in ticker_data_dict]
        else:
            tickers_to_process = sorted(ticker_data_dict.keys())

        for ticker in tickers_to_process:
            df = ticker_data_dict[ticker]
            is_fno = ticker in fno_tickers

            self._add_ticker_row(ws, current_row, ticker, df, trading_dates,
                               stock_col, date_col_start, summary_col_start, is_fno)
            current_row += 1

        # Adjust column widths (6 metadata + 6 summary + 1 stock + 60 date columns = 73 total)
        total_cols = date_col_start + len(trading_dates) - 1
        self._adjust_column_widths(ws, total_cols)

    def _add_daily_band_totals(self, ws, start_row, trading_dates, ticker_data_dict):
        """Add daily band totals at the top"""

        # Calculate daily totals
        daily_counts = {date: {'purple': 0, 'dark_green': 0, 'light_green': 0,
                               'blue': 0, 'cream': 0, 'white': 0} for date in trading_dates}

        for ticker, df in ticker_data_dict.items():
            for _, row in df.iterrows():
                if row['date'] in daily_counts:
                    band = row.get('color_band', 'white')
                    if band in daily_counts[row['date']]:
                        daily_counts[row['date']][band] += 1

        # Date columns start after STOCK column (col 50 = stock, col 51 = first date)
        date_col_start = 51

        # Add OVERALL summary row first (Total with Volume > 36-Day MA)
        ws.cell(row=start_row, column=1, value="TOTAL (Vol>MA)")
        ws.merge_cells(start_row=start_row, start_column=1,
                      end_row=start_row, end_column=45)  # Merge through STOCK column

        # Make it bold
        overall_cell = ws.cell(row=start_row, column=1)
        overall_cell.font = Font(bold=True)

        for idx, date in enumerate(trading_dates):
            col = date_col_start + idx  # Start from column 14 (date columns)
            # Sum all bands except white (white = low volume)
            total = (daily_counts[date]['purple'] + daily_counts[date]['dark_green'] +
                    daily_counts[date]['light_green'] + daily_counts[date]['blue'] +
                    daily_counts[date]['cream'])
            cell = ws.cell(row=start_row, column=col, value=total)
            cell.font = Font(bold=True)

        start_row += 1

        # Add individual band totals rows
        bands = ['purple', 'dark_green', 'light_green', 'blue', 'cream', 'white']
        band_labels = ['Purple (≥80%)', 'Dark Green (60-80%)', 'Light Green (50-60%)',
                      'Blue (40-50%)', 'Cream (Accum: <40% + HighVol)', 'White (LowVol)']

        for band, label in zip(bands, band_labels):
            ws.cell(row=start_row, column=1, value=label)
            ws.merge_cells(start_row=start_row, start_column=1,
                          end_row=start_row, end_column=45)  # Merge through STOCK column

            for idx, date in enumerate(trading_dates):
                col = date_col_start + idx  # Start from column 14
                count = daily_counts[date][band]
                ws.cell(row=start_row, column=col, value=count)

            start_row += 1

        # Add blank row
        start_row += 1
        return start_row

    def _add_ticker_row(self, ws, row, ticker, df, trading_dates,
                       stock_col, date_col_start, summary_col_start, is_fno):
        """Add a ticker data row"""

        # Get latest data for summary columns
        latest_data = df.iloc[-1] if not df.empty else None

        # Get metadata for this ticker
        metadata = self.ticker_metadata.get(ticker, {})

        # Color definitions for signals
        sell_signal_color = PatternFill(start_color='FF6B6B', end_color='FF6B6B', fill_type='solid')
        warning_color = PatternFill(start_color='FFD93D', end_color='FFD93D', fill_type='solid')
        stage1_signal_color = PatternFill(start_color='90EE90', end_color='90EE90', fill_type='solid')
        stage1_strong_color = PatternFill(start_color='32CD32', end_color='32CD32', fill_type='solid')
        buy_signal_color = PatternFill(start_color='00B050', end_color='00B050', fill_type='solid')

        # Helper to safely get latest value
        def _get(col, default='N/A'):
            if latest_data is not None and col in df.columns:
                val = latest_data[col]
                return val if pd.notna(val) else default
            return default

        # ── COLUMNS 1-3: Identity & Stage ──
        mcap_cell = ws.cell(row=row, column=1, value=metadata.get('mcap', ''))
        segment_cell = ws.cell(row=row, column=2, value=metadata.get('department', ''))
        stage_value = _get('stage')
        stage_cell = ws.cell(row=row, column=3, value=stage_value)

        # ── COLUMNS 4-5: Weeks Above/Below WMA (Stage maturity) ──
        weeks_above = _get('weeks_above_wma', 0)
        weeks_below = _get('weeks_below_wma', 0)
        wks_above_cell = ws.cell(row=row, column=4, value=int(weeks_above) if weeks_above else 0)
        wks_below_cell = ws.cell(row=row, column=5, value=int(weeks_below) if weeks_below else 0)

        # ── COLUMNS 6-7: Price vs WMA & Slope ──
        price_vs_wma = _get('price_vs_wma')
        price_wma_cell = ws.cell(row=row, column=6, value=price_vs_wma)
        wma_slope = _get('wma_slope')
        slope_cell = ws.cell(row=row, column=7, value=wma_slope)

        # ── COLUMNS 8-10: Cross Signal + Volume Confirmation ──
        # Cross above: show for the entire week it occurred (not just last 5 days)
        has_cross_above = False
        cross_confirmed = False
        if 'cross_above' in df.columns and len(df) >= 1:
            # Get the current week of the latest data point
            latest_week = df.iloc[-1].get('week')
            if latest_week is not None:
                current_week_data = df[df['week'] == latest_week]
                has_cross_above = current_week_data['cross_above'].any()
                if has_cross_above and 'cross_above_confirmed' in df.columns:
                    cross_confirmed = current_week_data['cross_above_confirmed'].any()
            # Also check previous week if current week just started
            if not has_cross_above and len(df['week'].unique()) >= 2:
                prev_week = df['week'].unique()[-2]
                prev_week_data = df[df['week'] == prev_week]
                has_cross_above = prev_week_data['cross_above'].any()
                if has_cross_above and 'cross_above_confirmed' in df.columns:
                    cross_confirmed = prev_week_data['cross_above_confirmed'].any()

        cross_cell = ws.cell(row=row, column=8, value="✓" if has_cross_above else "")
        vol_conf_cell = ws.cell(row=row, column=9, value="✓ Vol" if cross_confirmed else ("No Vol" if has_cross_above else ""))

        # Color code: green for volume-confirmed cross, yellow for unconfirmed
        if cross_confirmed:
            cross_cell.fill = buy_signal_color
            cross_cell.font = Font(bold=True, color='FFFFFF')
            vol_conf_cell.fill = buy_signal_color
            vol_conf_cell.font = Font(bold=True, color='FFFFFF')
        elif has_cross_above:
            cross_cell.fill = warning_color
            cross_cell.font = Font(bold=True)
            vol_conf_cell.fill = warning_color

        # Volume Ratio (column 10)
        vol_ratio = _get('vol_ratio', None)
        vol_ratio_cell = ws.cell(row=row, column=10,
                                 value=f"{vol_ratio:.1f}x" if pd.notna(vol_ratio) else "N/A")
        # Highlight strong volume
        if pd.notna(vol_ratio) and vol_ratio >= 2.0:
            vol_ratio_cell.font = Font(bold=True)
            vol_ratio_cell.fill = PatternFill(start_color='E2EFDA', end_color='E2EFDA', fill_type='solid')

        # ── COLUMNS 11-13: 52W Metrics ──
        high_52w_pct = _get('52w_high_pct', None)
        high_52w_date = _get('52w_high_date', '')
        if pd.notna(high_52w_pct):
            high_display = f"{high_52w_pct:+.1f}%"
            if high_52w_date and high_52w_date != 'N/A':
                date_parts = str(high_52w_date).split('-')
                if len(date_parts) >= 2:
                    high_display += f" ({date_parts[0]}-{date_parts[1]})"
            high_52w_cell = ws.cell(row=row, column=11, value=high_display)
        else:
            high_52w_cell = ws.cell(row=row, column=11, value="N/A")

        low_52w_pct = _get('52w_low_pct', None)
        low_52w_date = _get('52w_low_date', '')
        if pd.notna(low_52w_pct):
            low_display = f"{low_52w_pct:+.1f}%"
            if low_52w_date and low_52w_date != 'N/A':
                date_parts = str(low_52w_date).split('-')
                if len(date_parts) >= 2:
                    low_display += f" ({date_parts[0]}-{date_parts[1]})"
            low_52w_cell = ws.cell(row=row, column=12, value=low_display)
        else:
            low_52w_cell = ws.cell(row=row, column=12, value="N/A")

        near_52w = _get('near_52w_high')
        near_52w_cell = ws.cell(row=row, column=13, value=near_52w)
        if near_52w == 'Yes':
            high_52w_cell.fill = self.colors['gold']
            near_52w_cell.fill = self.colors['gold']
            high_52w_cell.font = Font(bold=True)
            near_52w_cell.font = Font(bold=True)

        # ── COLUMNS 14-15: Relative Strength vs NIFTY ──
        rs_ratio = _get('rs_ratio', None)
        rs_trend = _get('rs_trend')
        rs_signal = _get('rs_signal')
        rs_cell = ws.cell(row=row, column=14,
                          value=f"{rs_ratio:+.1f}%" if pd.notna(rs_ratio) else "N/A")
        rs_trend_cell = ws.cell(row=row, column=15, value=rs_trend)

        # Color code RS
        if rs_signal == 'Outperform':
            rs_cell.fill = PatternFill(start_color='E2EFDA', end_color='E2EFDA', fill_type='solid')
        elif rs_signal == 'Underperform':
            rs_cell.fill = PatternFill(start_color='FCE4EC', end_color='FCE4EC', fill_type='solid')
        if rs_trend == 'Improving':
            rs_trend_cell.fill = PatternFill(start_color='E2EFDA', end_color='E2EFDA', fill_type='solid')
        elif rs_trend == 'Weakening':
            rs_trend_cell.fill = PatternFill(start_color='FCE4EC', end_color='FCE4EC', fill_type='solid')

        # ── COLUMNS 16-17: RSI ──
        rsi_value = _get('rsi', None)
        rsi_signal = _get('rsi_signal')
        rsi_cell = ws.cell(row=row, column=16,
                          value=f"{rsi_value:.1f}" if pd.notna(rsi_value) else "N/A")
        rsi_signal_cell = ws.cell(row=row, column=17, value=rsi_signal)

        if rsi_signal == 'Overbought' and pd.notna(rsi_value):
            rsi_cell.fill = PatternFill(start_color='FFB6C1', end_color='FFB6C1', fill_type='solid')
            rsi_signal_cell.fill = PatternFill(start_color='FFB6C1', end_color='FFB6C1', fill_type='solid')
        elif rsi_signal == 'Oversold' and pd.notna(rsi_value):
            rsi_cell.fill = PatternFill(start_color='90EE90', end_color='90EE90', fill_type='solid')
            rsi_signal_cell.fill = PatternFill(start_color='90EE90', end_color='90EE90', fill_type='solid')

        # ── COLUMNS 18-22: Fundamentals (NEW) ──
        pe_ratio = _get('pe_ratio', None)
        sector_pe = _get('sector_pe', None)
        price_vs_200dma = _get('price_vs_200dma', None)
        promoter_pct = _get('promoter_pct', None)
        promoter_change = _get('promoter_change', None)
        profit_growth = _get('profit_growth_yoy', None)

        pe_cell = ws.cell(row=row, column=18,
                          value=f"{pe_ratio:.1f}" if pd.notna(pe_ratio) else "N/A")
        sector_pe_cell = ws.cell(row=row, column=19,
                                 value=f"{sector_pe:.1f}" if pd.notna(sector_pe) else "N/A")
        dma200_cell = ws.cell(row=row, column=20,
                               value=f"{price_vs_200dma:+.1f}%" if pd.notna(price_vs_200dma) else "N/A")

        # Show promoter % with QoQ change if available
        if pd.notna(promoter_pct) and pd.notna(promoter_change):
            promoter_display = f"{promoter_pct:.1f}% ({promoter_change:+.2f})"
        elif pd.notna(promoter_pct):
            promoter_display = f"{promoter_pct:.1f}%"
        else:
            promoter_display = "N/A"
        promoter_cell = ws.cell(row=row, column=21, value=promoter_display)

        profit_cell = ws.cell(row=row, column=22,
                              value=f"{profit_growth:+.1f}%" if pd.notna(profit_growth) else "N/A")

        # Color code PE (green if below sector PE, pink if above)
        if pd.notna(pe_ratio) and pd.notna(sector_pe) and sector_pe > 0:
            if pe_ratio < sector_pe * 0.8:  # Significantly below sector
                pe_cell.fill = PatternFill(start_color='E2EFDA', end_color='E2EFDA', fill_type='solid')
            elif pe_ratio > sector_pe * 1.5:  # Significantly above sector
                pe_cell.fill = PatternFill(start_color='FCE4EC', end_color='FCE4EC', fill_type='solid')

        # Color code 200 DMA (green above, pink below)
        if pd.notna(price_vs_200dma):
            if price_vs_200dma >= 0:
                dma200_cell.fill = PatternFill(start_color='E2EFDA', end_color='E2EFDA', fill_type='solid')
            else:
                dma200_cell.fill = PatternFill(start_color='FCE4EC', end_color='FCE4EC', fill_type='solid')

        # Color code promoter holding (change-aware)
        if pd.notna(promoter_change) and promoter_change > 0:
            # Promoter INCREASING stake = strongest bullish signal
            promoter_cell.fill = PatternFill(start_color='00B050', end_color='00B050', fill_type='solid')
            promoter_cell.font = Font(bold=True, color='FFFFFF')
        elif pd.notna(promoter_change) and promoter_change < -1:
            # Promoter DECREASING stake = red flag
            promoter_cell.fill = PatternFill(start_color='FF6B6B', end_color='FF6B6B', fill_type='solid')
            promoter_cell.font = Font(bold=True, color='FFFFFF')
        elif pd.notna(promoter_pct):
            if promoter_pct >= 60:  # High promoter = strong conviction
                promoter_cell.fill = PatternFill(start_color='E2EFDA', end_color='E2EFDA', fill_type='solid')
            elif promoter_pct < 30:  # Low promoter
                promoter_cell.fill = PatternFill(start_color='FCE4EC', end_color='FCE4EC', fill_type='solid')

        # Color code profit growth
        if pd.notna(profit_growth):
            if profit_growth > 20:  # Strong earnings growth
                profit_cell.fill = PatternFill(start_color='E2EFDA', end_color='E2EFDA', fill_type='solid')
                profit_cell.font = Font(bold=True)
            elif profit_growth < -20:  # Significant decline
                profit_cell.fill = PatternFill(start_color='FCE4EC', end_color='FCE4EC', fill_type='solid')

        # ── COLUMNS 23-29: Momentum, Divergence, Squeeze ──
        roc_1w = _get('roc_1w', None)
        roc_1m = _get('roc_1m', None)
        roc_3m = _get('roc_3m', None)
        momentum_align = _get('momentum_align')
        divergence = _get('divergence')
        squeeze = _get('squeeze')
        squeeze_ratio = _get('squeeze_ratio', None)

        roc_1w_cell = ws.cell(row=row, column=23,
                              value=f"{roc_1w:+.1f}%" if pd.notna(roc_1w) else "N/A")
        roc_1m_cell = ws.cell(row=row, column=24,
                              value=f"{roc_1m:+.1f}%" if pd.notna(roc_1m) else "N/A")
        roc_3m_cell = ws.cell(row=row, column=25,
                              value=f"{roc_3m:+.1f}%" if pd.notna(roc_3m) else "N/A")
        momentum_cell = ws.cell(row=row, column=26, value=momentum_align)
        divergence_cell = ws.cell(row=row, column=27, value=divergence)
        squeeze_cell = ws.cell(row=row, column=28, value=squeeze)
        squeeze_ratio_cell = ws.cell(row=row, column=29,
                                      value=f"{squeeze_ratio:.2f}" if pd.notna(squeeze_ratio) else "N/A")

        # Color code ROC (green = positive, pink = negative)
        roc_pos_fill = PatternFill(start_color='E2EFDA', end_color='E2EFDA', fill_type='solid')
        roc_neg_fill = PatternFill(start_color='FCE4EC', end_color='FCE4EC', fill_type='solid')
        for roc_cell, roc_val in [(roc_1w_cell, roc_1w), (roc_1m_cell, roc_1m), (roc_3m_cell, roc_3m)]:
            if pd.notna(roc_val):
                roc_cell.fill = roc_pos_fill if roc_val > 0 else roc_neg_fill

        # Color code momentum alignment
        if momentum_align == 'All Up':
            momentum_cell.fill = buy_signal_color
            momentum_cell.font = Font(bold=True, color='FFFFFF')
        elif momentum_align == 'Reversing Up':
            momentum_cell.fill = roc_pos_fill
            momentum_cell.font = Font(bold=True)
        elif momentum_align == 'All Down':
            momentum_cell.fill = sell_signal_color
            momentum_cell.font = Font(bold=True, color='FFFFFF')
        elif momentum_align == 'Breaking Down':
            momentum_cell.fill = roc_neg_fill

        # Color code divergence
        if divergence == 'Bullish':
            divergence_cell.fill = buy_signal_color
            divergence_cell.font = Font(bold=True, color='FFFFFF')
        elif divergence == 'Bearish':
            divergence_cell.fill = sell_signal_color
            divergence_cell.font = Font(bold=True, color='FFFFFF')

        # Color code squeeze
        squeeze_coil_fill = PatternFill(start_color='FFF2CC', end_color='FFF2CC', fill_type='solid')  # Light yellow
        if squeeze == 'Coiling':
            squeeze_cell.fill = PatternFill(start_color='FF9800', end_color='FF9800', fill_type='solid')  # Orange
            squeeze_cell.font = Font(bold=True, color='FFFFFF')
            squeeze_ratio_cell.fill = PatternFill(start_color='FF9800', end_color='FF9800', fill_type='solid')
            squeeze_ratio_cell.font = Font(bold=True, color='FFFFFF')
        elif squeeze == 'Tight':
            squeeze_cell.fill = squeeze_coil_fill
            squeeze_ratio_cell.fill = squeeze_coil_fill

        # ── SUMMARY COLUMNS (25+) ──
        deliv_avg_10d = _get('deliv_avg_10d', None)
        deliv_avg_30d = _get('deliv_avg_30d', None)
        deliv_trend = _get('deliv_trend')
        accum_score = _get('accum_score', 0)

        avg10_cell = ws.cell(row=row, column=summary_col_start,
                            value=f"{deliv_avg_10d:.1f}%" if pd.notna(deliv_avg_10d) else "N/A")
        avg30_cell = ws.cell(row=row, column=summary_col_start + 1,
                            value=f"{deliv_avg_30d:.1f}%" if pd.notna(deliv_avg_30d) else "N/A")
        trend_cell = ws.cell(row=row, column=summary_col_start + 2, value=deliv_trend)
        score_cell = ws.cell(row=row, column=summary_col_start + 3,
                            value=f"{int(accum_score)}/6" if pd.notna(accum_score) else "N/A")

        if not hasattr(self, '_calculator'):
            from calculations import StockCalculator
            self._calculator = StockCalculator(self.config)
        summary = self._calculator.calculate_summary_counts(df, self.evaluation_days)

        count1_cell = ws.cell(row=row, column=summary_col_start + 4,
                             value=summary['count_purple_darkgreen_lightgreen'])
        count2_cell = ws.cell(row=row, column=summary_col_start + 5,
                             value=summary['count_including_blue'])
        count3_cell = ws.cell(row=row, column=summary_col_start + 6,
                             value=summary['count_excl_blue_highvol'])
        count4_cell = ws.cell(row=row, column=summary_col_start + 7,
                             value=summary['count_incl_blue_highvol'])
        count5_cell = ws.cell(row=row, column=summary_col_start + 8,
                             value=summary['count_excl_blue_highvol_15d'])
        count6_cell = ws.cell(row=row, column=summary_col_start + 9,
                             value=summary['count_excl_blue_highvol_20d'])

        # ── SELL SIGNAL COLUMNS ──
        exit_score = _get('exit_score', 0)
        exit_score_cell = ws.cell(row=row, column=summary_col_start + 10,
                                 value=f"{int(exit_score)}/7" if pd.notna(exit_score) else "N/A")

        # Cross Below WMA (primary Weinstein sell)
        cross_below_alert = _get('cross_below_alert', '-')
        cross_below_cell = ws.cell(row=row, column=summary_col_start + 11, value=cross_below_alert)
        if cross_below_alert == 'SELL (Vol)':
            cross_below_cell.fill = sell_signal_color
            cross_below_cell.font = Font(bold=True, color='FFFFFF')
        elif cross_below_alert == 'SELL':
            cross_below_cell.fill = warning_color
            cross_below_cell.font = Font(bold=True)

        distribution_alert = _get('distribution_alert', 'No')
        distrib_cell = ws.cell(row=row, column=summary_col_start + 12, value=distribution_alert)

        stage_3_alert = _get('stage_3_alert', '-')
        stage3_cell = ws.cell(row=row, column=summary_col_start + 13, value=stage_3_alert)

        trend_break = _get('trend_break', 'Neutral')
        trend_break_cell = ws.cell(row=row, column=summary_col_start + 14, value=trend_break)

        price_vs_10ma = _get('price_vs_10ma')
        price10ma_cell = ws.cell(row=row, column=summary_col_start + 15, value=price_vs_10ma)

        deliv_momentum = _get('deliv_momentum')
        deliv_mom_cell = ws.cell(row=row, column=summary_col_start + 16, value=deliv_momentum)

        vol_spike_down = _get('vol_spike_down', 'No')
        vol_spike_cell = ws.cell(row=row, column=summary_col_start + 17, value=vol_spike_down)

        # Color code sell signals
        if exit_score >= 4:
            exit_score_cell.fill = sell_signal_color
            exit_score_cell.font = Font(bold=True, color='FFFFFF')
        elif exit_score >= 2:
            exit_score_cell.fill = warning_color

        if distribution_alert == 'Yes':
            distrib_cell.fill = sell_signal_color
            distrib_cell.font = Font(bold=True)
        if stage_3_alert == 'Exit Signal':
            stage3_cell.fill = sell_signal_color
            stage3_cell.font = Font(bold=True)
        if trend_break == 'Lower High':
            trend_break_cell.fill = warning_color
        if price_vs_10ma == 'Below':
            price10ma_cell.fill = warning_color
        if deliv_momentum == 'Declining':
            deliv_mom_cell.fill = warning_color
        if vol_spike_down == 'Yes':
            vol_spike_cell.fill = warning_color

        # ── STAGE 1 ALERT COLUMNS ──
        stage1_alert = _get('stage1_alert', 'No')
        stage1_alert_cell = ws.cell(row=row, column=summary_col_start + 18, value=stage1_alert)

        stage1_strength = _get('stage1_strength', 0)
        stage1_strength_cell = ws.cell(row=row, column=summary_col_start + 19,
                                       value=f"{int(stage1_strength)}/5" if pd.notna(stage1_strength) else "N/A")

        if stage1_alert == 'Yes':
            if stage1_strength >= 4:
                stage1_alert_cell.fill = stage1_strong_color
                stage1_strength_cell.fill = stage1_strong_color
                stage1_alert_cell.font = Font(bold=True)
                stage1_strength_cell.font = Font(bold=True)
            else:
                stage1_alert_cell.fill = stage1_signal_color
                stage1_strength_cell.fill = stage1_signal_color
                stage1_alert_cell.font = Font(bold=True)

        # ── STOCK COLUMN ──
        stock_cell = ws.cell(row=row, column=stock_col, value=ticker)

        # ── FNO GREY STYLING ──
        if is_fno:
            grey = self.colors['grey']
            # Grey all base columns
            for c in [mcap_cell, segment_cell, stage_cell, wks_above_cell, wks_below_cell,
                      price_wma_cell, slope_cell, high_52w_cell, low_52w_cell, near_52w_cell,
                      pe_cell, sector_pe_cell, promoter_cell,
                      avg10_cell, avg30_cell, trend_cell, score_cell,
                      count1_cell, count2_cell, count3_cell, count4_cell, count5_cell, count6_cell,
                      squeeze_ratio_cell, stock_cell]:
                c.fill = grey
            # Cross columns: preserve green/yellow highlights
            if not has_cross_above:
                cross_cell.fill = grey
                vol_conf_cell.fill = grey
            # Vol ratio: preserve highlight for strong volume
            if not (pd.notna(vol_ratio) and vol_ratio >= 2.0):
                vol_ratio_cell.fill = grey
            # RS: preserve signal colors
            if rs_signal not in ['Outperform', 'Underperform']:
                rs_cell.fill = grey
            if rs_trend not in ['Improving', 'Weakening']:
                rs_trend_cell.fill = grey
            # RSI: preserve overbought/oversold
            if rsi_signal not in ['Overbought', 'Oversold']:
                rsi_cell.fill = grey
                rsi_signal_cell.fill = grey
            # 200 DMA: preserve above/below coloring
            if not pd.notna(price_vs_200dma):
                dma200_cell.fill = grey
            # Profit growth: preserve strong growth/decline
            if not pd.notna(profit_growth):
                profit_cell.fill = grey
            # ROC: preserve color coding
            for roc_cell_fno, roc_val_fno in [(roc_1w_cell, roc_1w), (roc_1m_cell, roc_1m), (roc_3m_cell, roc_3m)]:
                if not pd.notna(roc_val_fno):
                    roc_cell_fno.fill = grey
            # Momentum: preserve strong signals
            if momentum_align not in ['All Up', 'Reversing Up', 'All Down', 'Breaking Down']:
                momentum_cell.fill = grey
            # Divergence: preserve bullish/bearish
            if divergence not in ['Bullish', 'Bearish']:
                divergence_cell.fill = grey
            # Squeeze: preserve coiling/tight
            if squeeze not in ['Coiling', 'Tight']:
                squeeze_cell.fill = grey
            # Exit signals: preserve active alerts
            if exit_score < 2:
                exit_score_cell.fill = grey
            if cross_below_alert not in ['SELL', 'SELL (Vol)']:
                cross_below_cell.fill = grey
            if distribution_alert != 'Yes':
                distrib_cell.fill = grey
            if stage_3_alert != 'Exit Signal':
                stage3_cell.fill = grey
            if trend_break != 'Lower High':
                trend_break_cell.fill = grey
            if price_vs_10ma != 'Below':
                price10ma_cell.fill = grey
            if deliv_momentum != 'Declining':
                deliv_mom_cell.fill = grey
            if vol_spike_down != 'Yes':
                vol_spike_cell.fill = grey
            if stage1_alert != 'Yes':
                stage1_alert_cell.fill = grey
                stage1_strength_cell.fill = grey

        # Center align all non-date columns
        all_cells = [mcap_cell, segment_cell, stage_cell, wks_above_cell, wks_below_cell,
                     price_wma_cell, slope_cell, cross_cell, vol_conf_cell, vol_ratio_cell,
                     high_52w_cell, low_52w_cell, near_52w_cell, rs_cell, rs_trend_cell,
                     rsi_cell, rsi_signal_cell,
                     pe_cell, sector_pe_cell, dma200_cell, promoter_cell, profit_cell,
                     roc_1w_cell, roc_1m_cell, roc_3m_cell, momentum_cell,
                     divergence_cell, squeeze_cell, squeeze_ratio_cell,
                     avg10_cell, avg30_cell, trend_cell, score_cell,
                     count1_cell, count2_cell, count3_cell, count4_cell, count5_cell, count6_cell,
                     exit_score_cell, cross_below_cell, distrib_cell, stage3_cell,
                     trend_break_cell, price10ma_cell, deliv_mom_cell, vol_spike_cell,
                     stage1_alert_cell, stage1_strength_cell]
        for cell in all_cells:
            cell.alignment = Alignment(horizontal='center', vertical='center')

        # ── DATE COLUMNS ──
        for idx, date in enumerate(trading_dates):
            col = date_col_start + idx
            cell = ws.cell(row=row, column=col)

            date_data = df[df['date'] == date]
            if not date_data.empty:
                row_data = date_data.iloc[0]
                delivery_pct = row_data.get('delivery_pct')
                is_high_vol = row_data.get('is_high_vol', 'N/A')

                if pd.notna(delivery_pct):
                    cell.value = f"{delivery_pct:.1f}% | {is_high_vol}"
                    color_band = row_data.get('color_band', 'white')
                    cell.fill = self.colors.get(color_band, self.colors['white'])
                else:
                    cell.value = ""
                    cell.fill = self.colors['white']
            else:
                cell.value = ""
                cell.fill = self.colors['white']

            cell.alignment = Alignment(horizontal='center', vertical='center')

    def _style_header_row(self, ws, row, max_col):
        """Apply styling to header row"""
        for col in range(1, max_col + 1):
            cell = ws.cell(row=row, column=col)
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            cell.fill = PatternFill(start_color='CCCCCC', end_color='CCCCCC', fill_type='solid')

    def _adjust_column_widths(self, ws, total_cols):
        """Adjust column widths for better readability"""
        ws.column_dimensions['A'].width = 12  # MCAP
        ws.column_dimensions['B'].width = 20  # SEGMENT
        ws.column_dimensions['C'].width = 10  # STAGE
        ws.column_dimensions['D'].width = 12  # Wks Above WMA
        ws.column_dimensions['E'].width = 12  # Wks Below WMA
        ws.column_dimensions['F'].width = 14  # Price vs WMA
        ws.column_dimensions['G'].width = 12  # 30WMA Slope
        ws.column_dimensions['H'].width = 12  # Cross Above
        ws.column_dimensions['I'].width = 12  # Vol Confirmed
        ws.column_dimensions['J'].width = 10  # Vol Ratio
        ws.column_dimensions['K'].width = 20  # 52W High %
        ws.column_dimensions['L'].width = 20  # 52W Low %
        ws.column_dimensions['R'].width = 10  # PE Ratio
        ws.column_dimensions['S'].width = 10  # Sector PE
        ws.column_dimensions['T'].width = 14  # Price vs 200DMA
        ws.column_dimensions['U'].width = 12  # Promoter %
        ws.column_dimensions['V'].width = 16  # Profit Growth YoY
        ws.column_dimensions['W'].width = 10  # ROC 1W
        ws.column_dimensions['X'].width = 10  # ROC 1M
        ws.column_dimensions['Y'].width = 10  # ROC 3M
        ws.column_dimensions['Z'].width = 14  # Momentum
        ws.column_dimensions['AA'].width = 12  # Divergence
        ws.column_dimensions['AB'].width = 10  # Squeeze
        ws.column_dimensions['AC'].width = 12  # Squeeze Ratio

        # Remaining columns
        explicit_cols = {'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z', 'AA', 'AB', 'AC'}
        for col in range(13, total_cols + 1):
            col_letter = get_column_letter(col)
            if col_letter not in explicit_cols:
                ws.column_dimensions[col_letter].width = 15

    def _get_date_format(self):
        """Get Python date format string from config"""
        format_map = {
            'DD-MM-YYYY': '%d-%m-%Y',
            'DD/MM/YYYY': '%d/%m/%Y',
            'MM-DD-YYYY': '%m-%d-%Y',
            'MM/DD/YYYY': '%m/%d/%Y',
            'YYYY-MM-DD': '%Y-%m-%d'
        }
        return format_map.get(self.date_format, '%d-%m-%Y')

    def _load_ticker_metadata(self):
        """Load ticker metadata from JSON file"""
        import json
        import os

        metadata_path = 'Stock_Information/ticker_metadata.json'
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Could not load ticker metadata: {e}")
                return {}
        return {}

    def _build_sector_analysis_sheet(self, ws, ticker_data_dict):
        """
        Build the Sector Analysis sheet showing sector-wise accumulation
        with last 5 days trends to identify sector rotation
        """
        logger.info("Building Sector Analysis sheet...")

        # Get last 5 trading days from data
        all_dates = set()
        for df in ticker_data_dict.values():
            if not df.empty:
                all_dates.update(df['date'].tolist())

        if not all_dates:
            ws.cell(row=1, column=1, value="No data available")
            return

        trading_dates = sorted(list(all_dates))[-5:]  # Last 5 days

        # Get all unique sectors
        sectors = set()
        for ticker, metadata in self.ticker_metadata.items():
            sector = metadata.get('department', 'Unknown')
            if sector:
                sectors.add(sector)

        sectors = sorted(list(sectors))

        # Color bands in order
        color_bands = ['Purple (≥80%)', 'Dark Green (60-80%)',
                      'Light Green (50-60%)', 'Blue (40-50%)',
                      'Cream (Accum)', 'White (LowVol)']
        band_keys = ['purple', 'dark_green', 'light_green', 'blue', 'cream', 'white']

        # Title
        ws.cell(row=1, column=1, value="SECTOR-WISE ACCUMULATION ANALYSIS")
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(sectors) + 2)
        title_cell = ws.cell(row=1, column=1)
        title_cell.font = Font(bold=True, size=14)
        title_cell.alignment = Alignment(horizontal='center')

        # Subtitle
        ws.cell(row=2, column=1, value=f"Last 5 Trading Days: {trading_dates[0].strftime('%d-%b')} to {trading_dates[-1].strftime('%d-%b-%Y')}")
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(sectors) + 2)
        subtitle_cell = ws.cell(row=2, column=1)
        subtitle_cell.font = Font(italic=True, size=11)
        subtitle_cell.alignment = Alignment(horizontal='center')

        current_row = 4

        # Build a table for each day
        for day_idx, date in enumerate(trading_dates):
            date_str = date.strftime('%d-%b-%Y (%a)')

            # Day header
            ws.cell(row=current_row, column=1, value=f"Day {day_idx + 1}: {date_str}")
            ws.merge_cells(start_row=current_row, start_column=1,
                          end_row=current_row, end_column=len(sectors) + 2)
            day_header = ws.cell(row=current_row, column=1)
            day_header.font = Font(bold=True, size=12)
            day_header.fill = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')
            day_header.font = Font(bold=True, size=12, color='FFFFFF')
            current_row += 1

            # Column headers: Color Band | Sector1 | Sector2 | ... | TOTAL
            ws.cell(row=current_row, column=1, value="Delivery Band")
            for idx, sector in enumerate(sectors):
                ws.cell(row=current_row, column=idx + 2, value=sector)
            ws.cell(row=current_row, column=len(sectors) + 2, value="TOTAL")

            # Style column headers
            for col in range(1, len(sectors) + 3):
                cell = ws.cell(row=current_row, column=col)
                cell.font = Font(bold=True)
                cell.fill = PatternFill(start_color='D9E1F2', end_color='D9E1F2', fill_type='solid')
                cell.alignment = Alignment(horizontal='center', vertical='center')
                cell.border = Border(
                    left=Side(style='thin'),
                    right=Side(style='thin'),
                    top=Side(style='thin'),
                    bottom=Side(style='thin')
                )

            current_row += 1

            # Calculate counts for this date
            sector_band_counts = {}
            for sector in sectors:
                sector_band_counts[sector] = {band: 0 for band in band_keys}

            # Count stocks by sector and color band
            for ticker, df in ticker_data_dict.items():
                metadata = self.ticker_metadata.get(ticker, {})
                sector = metadata.get('department', 'Unknown')

                if sector not in sectors:
                    continue

                # Get data for this date
                date_data = df[df['date'] == date]
                if not date_data.empty:
                    color_band = date_data.iloc[0].get('color_band', 'white')
                    if color_band in sector_band_counts[sector]:
                        sector_band_counts[sector][color_band] += 1

            # Add rows for each color band
            for band_label, band_key in zip(color_bands, band_keys):
                ws.cell(row=current_row, column=1, value=band_label)

                # Apply color to the band label cell
                label_cell = ws.cell(row=current_row, column=1)
                label_cell.fill = self.colors.get(band_key, self.colors['white'])
                label_cell.font = Font(bold=True)
                label_cell.alignment = Alignment(horizontal='left', vertical='center')
                label_cell.border = Border(
                    left=Side(style='thin'),
                    right=Side(style='thin'),
                    top=Side(style='thin'),
                    bottom=Side(style='thin')
                )

                # Sector counts
                row_total = 0
                for idx, sector in enumerate(sectors):
                    count = sector_band_counts[sector][band_key]
                    cell = ws.cell(row=current_row, column=idx + 2, value=count if count > 0 else "")
                    cell.alignment = Alignment(horizontal='center', vertical='center')
                    cell.border = Border(
                        left=Side(style='thin'),
                        right=Side(style='thin'),
                        top=Side(style='thin'),
                        bottom=Side(style='thin')
                    )
                    row_total += count

                    # Highlight high counts
                    if count >= 3:
                        cell.font = Font(bold=True)
                        cell.fill = PatternFill(start_color='FFF2CC', end_color='FFF2CC', fill_type='solid')

                # Row total
                total_cell = ws.cell(row=current_row, column=len(sectors) + 2, value=row_total if row_total > 0 else "")
                total_cell.font = Font(bold=True)
                total_cell.alignment = Alignment(horizontal='center', vertical='center')
                total_cell.border = Border(
                    left=Side(style='thin'),
                    right=Side(style='thin'),
                    top=Side(style='thin'),
                    bottom=Side(style='thin')
                )

                current_row += 1

            # TOTAL row for this day
            ws.cell(row=current_row, column=1, value="TOTAL STOCKS")
            total_row_cell = ws.cell(row=current_row, column=1)
            total_row_cell.font = Font(bold=True)
            total_row_cell.fill = PatternFill(start_color='E2EFDA', end_color='E2EFDA', fill_type='solid')

            grand_total = 0
            for idx, sector in enumerate(sectors):
                sector_total = sum(sector_band_counts[sector].values())
                cell = ws.cell(row=current_row, column=idx + 2, value=sector_total if sector_total > 0 else "")
                cell.font = Font(bold=True)
                cell.alignment = Alignment(horizontal='center', vertical='center')
                cell.fill = PatternFill(start_color='E2EFDA', end_color='E2EFDA', fill_type='solid')
                cell.border = Border(
                    left=Side(style='thin'),
                    right=Side(style='thin'),
                    top=Side(style='thin'),
                    bottom=Side(style='thin')
                )
                grand_total += sector_total

            # Grand total
            grand_total_cell = ws.cell(row=current_row, column=len(sectors) + 2, value=grand_total)
            grand_total_cell.font = Font(bold=True)
            grand_total_cell.alignment = Alignment(horizontal='center', vertical='center')
            grand_total_cell.fill = PatternFill(start_color='C6E0B4', end_color='C6E0B4', fill_type='solid')
            grand_total_cell.border = Border(
                left=Side(style='thin'),
                right=Side(style='thin'),
                top=Side(style='thin'),
                bottom=Side(style='thin')
            )

            current_row += 2  # Blank row between days

        # Add SUMMARY TREND section at the bottom
        current_row += 1
        ws.cell(row=current_row, column=1, value="5-DAY ACCUMULATION SUMMARY (High Quality Stocks)")
        ws.merge_cells(start_row=current_row, start_column=1,
                      end_row=current_row, end_column=len(sectors) + 2)
        summary_header = ws.cell(row=current_row, column=1)
        summary_header.font = Font(bold=True, size=12)
        summary_header.fill = PatternFill(start_color='F4B084', end_color='F4B084', fill_type='solid')
        current_row += 1

        # Summary table headers
        ws.cell(row=current_row, column=1, value="Sector")
        ws.cell(row=current_row, column=2, value="Avg Purple+DGreen")
        ws.cell(row=current_row, column=3, value="Avg Total Accum")
        ws.cell(row=current_row, column=4, value="Trend")
        ws.cell(row=current_row, column=5, value="Rank")

        for col in range(1, 6):
            cell = ws.cell(row=current_row, column=col)
            cell.font = Font(bold=True)
            cell.fill = PatternFill(start_color='D9E1F2', end_color='D9E1F2', fill_type='solid')
            cell.alignment = Alignment(horizontal='center', vertical='center')

        current_row += 1

        # Calculate 5-day averages per sector
        sector_summary = {}
        for sector in sectors:
            high_quality_counts = []  # Purple + Dark Green
            total_accum_counts = []   # Purple + Dark Green + Light Green + Blue

            for date in trading_dates:
                sector_band_counts_date = {band: 0 for band in band_keys}

                for ticker, df in ticker_data_dict.items():
                    metadata = self.ticker_metadata.get(ticker, {})
                    if metadata.get('department', 'Unknown') != sector:
                        continue

                    date_data = df[df['date'] == date]
                    if not date_data.empty:
                        color_band = date_data.iloc[0].get('color_band', 'white')
                        if color_band in sector_band_counts_date:
                            sector_band_counts_date[color_band] += 1

                high_quality = sector_band_counts_date['purple'] + sector_band_counts_date['dark_green']
                total_accum = (sector_band_counts_date['purple'] + sector_band_counts_date['dark_green'] +
                              sector_band_counts_date['light_green'] + sector_band_counts_date['blue'])

                high_quality_counts.append(high_quality)
                total_accum_counts.append(total_accum)

            avg_high_quality = sum(high_quality_counts) / len(high_quality_counts)
            avg_total_accum = sum(total_accum_counts) / len(total_accum_counts)

            # Determine trend (comparing first 2 days vs last 2 days)
            early_avg = (high_quality_counts[0] + high_quality_counts[1]) / 2
            recent_avg = (high_quality_counts[-2] + high_quality_counts[-1]) / 2

            if recent_avg > early_avg + 1:
                trend = "▲ Increasing"
            elif recent_avg < early_avg - 1:
                trend = "▼ Decreasing"
            else:
                trend = "→ Stable"

            sector_summary[sector] = {
                'avg_high_quality': avg_high_quality,
                'avg_total_accum': avg_total_accum,
                'trend': trend
            }

        # Sort sectors by avg_high_quality (descending)
        sorted_sectors = sorted(sectors, key=lambda s: sector_summary[s]['avg_high_quality'], reverse=True)

        # Add summary rows
        for rank, sector in enumerate(sorted_sectors, start=1):
            summary = sector_summary[sector]

            ws.cell(row=current_row, column=1, value=sector)
            ws.cell(row=current_row, column=2, value=f"{summary['avg_high_quality']:.1f}")
            ws.cell(row=current_row, column=3, value=f"{summary['avg_total_accum']:.1f}")
            ws.cell(row=current_row, column=4, value=summary['trend'])
            ws.cell(row=current_row, column=5, value=rank)

            # Highlight top 5 sectors
            if rank <= 5:
                for col in range(1, 6):
                    cell = ws.cell(row=current_row, column=col)
                    cell.fill = PatternFill(start_color='C6E0B4', end_color='C6E0B4', fill_type='solid')
                    cell.font = Font(bold=True)

            # Center align numeric columns
            for col in range(2, 6):
                ws.cell(row=current_row, column=col).alignment = Alignment(horizontal='center', vertical='center')

            current_row += 1

        # Adjust column widths
        ws.column_dimensions['A'].width = 25
        for col in range(2, len(sectors) + 3):
            ws.column_dimensions[get_column_letter(col)].width = 18

        logger.info("Sector Analysis sheet completed")
