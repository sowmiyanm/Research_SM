"""
Excel Generator Module
Generates formatted Excel reports with delivery analysis
"""

import pandas as pd
import numpy as np
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.formatting.rule import CellIsRule
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Module-level style constants
_FONT_BOLD = Font(bold=True)
_FONT_BOLD_WHITE = Font(bold=True, color='FFFFFF')
_FONT_BOLD_SIZE12 = Font(bold=True, size=12)
_FONT_BOLD_SIZE14 = Font(bold=True, size=14)
_FONT_RED_BOLD_SIZE14 = Font(bold=True, size=14, color="C00000")
_FONT_BOLD_SIZE12_WHITE = Font(bold=True, size=12, color='FFFFFF')
_FONT_ITALIC_SIZE11 = Font(italic=True, size=11)
_FONT_BOLD_SIZE10 = Font(bold=True, size=10)

_FILL_GREEN_LIGHT = PatternFill(start_color='E2EFDA', end_color='E2EFDA', fill_type='solid')
_FILL_PINK_LIGHT = PatternFill(start_color='FCE4EC', end_color='FCE4EC', fill_type='solid')
_FILL_GREEN_STAGE1 = PatternFill(start_color='90EE90', end_color='90EE90', fill_type='solid')
_FILL_YELLOW_SQUEEZE = PatternFill(start_color='FFF2CC', end_color='FFF2CC', fill_type='solid')
_FILL_PINK_RSI = PatternFill(start_color='FFB6C1', end_color='FFB6C1', fill_type='solid')
_FILL_ORANGE = PatternFill(start_color='FF9800', end_color='FF9800', fill_type='solid')
_FILL_RED_SELL = PatternFill(start_color='FF6B6B', end_color='FF6B6B', fill_type='solid')
_FILL_BLUE_HEADER = PatternFill(start_color='D9E1F2', end_color='D9E1F2', fill_type='solid')
_FILL_GREEN_MED = PatternFill(start_color='C6E0B4', end_color='C6E0B4', fill_type='solid')
_FILL_GREEN_BUY = PatternFill(start_color='00B050', end_color='00B050', fill_type='solid')
_FILL_YELLOW_WARN = PatternFill(start_color='FFD93D', end_color='FFD93D', fill_type='solid')
_FILL_ORANGE_LIGHT = PatternFill(start_color='F4B084', end_color='F4B084', fill_type='solid')
_FILL_GREY = PatternFill(start_color='CCCCCC', end_color='CCCCCC', fill_type='solid')
_FILL_BLUE_DARK = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')
_FILL_GREEN_STAGE1_STRONG = PatternFill(start_color='32CD32', end_color='32CD32', fill_type='solid')

_NUMBER_FMT_PCT = '+0.0%;-0.0%'
_NUMBER_FMT_PCT2 = '+0.00%;-0.00%'
_NUMBER_FMT_1DP = '0.0'
_NUMBER_FMT_2DP = '0.00'
_NUMBER_FMT_INT = '0'


class ExcelReportGenerator:
    """Generates Excel reports with delivery analysis"""

    def __init__(self, config):
        self.config = config
        self.lookback_days = config.get('lookback_days_display', 60)
        self.evaluation_days = config.get('evaluation_days', 45)
        self.date_format = config.get('date_format', 'DD-MM-YYYY')
        self.display_order = config.get('display_order', 'descending')
        self.stale_days_threshold = config.get('stale_days_threshold', 4)
        self.shortlist_config = config.get('shortlist', {})

        self.ticker_metadata = self._load_ticker_metadata()

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
            'cream': PatternFill(start_color=config['delivery_bins']['cream']['color'],
                                end_color=config['delivery_bins']['cream']['color'],
                                fill_type='solid'),
            'grey': PatternFill(start_color=config.get('fno_grey_color', 'D3D3D3'),
                               end_color=config.get('fno_grey_color', 'D3D3D3'),
                               fill_type='solid'),
            'gold': PatternFill(start_color='FFD700', end_color='FFD700', fill_type='solid'),
        }

    # ── layout constants: STOCK is column 1 ──
    # column 1  = STOCK (ticker)
    # column 2  = MCAP
    # column 3  = SEGMENT
    # column 4  = STAGE
    # ... (metrics shift right by 1 from old layout)
    # summary_col_start = 31 (was 30)
    # as_of_col = 51 (was 50)
    # cols 52-56 = Pivot / →Pivot% / Stop / →Stop% / Base Wks  (added 2026-08-18)
    # date_col_start = 59

    _SUMMARY_COL = 31
    _AS_OF_COL = 51
    _PIVOT_COL = 52          # Pivot Price
    _DIST_PIVOT_COL = 53     # Distance to Pivot %
    _STOP_COL = 54           # Stop Level
    _DIST_STOP_COL = 55      # Distance to Stop %
    _BASE_WK_COL = 56        # Base length in weeks
    _WHY_COL = 57
    _TRIPLE_CONFIRM_COL = 58
    _DATE_COL_START = 59

    def generate_report(self, ticker_data_dict, fno_tickers, output_filename=None, ticker_order=None):
        if output_filename is None:
            output_filename = f"Delivery_Report_{datetime.now().strftime('%Y-%m-%d')}.xlsx"

        logger.info(f"Generating Excel report: {output_filename}")

        wb = Workbook()

        # Sheet order: Shortlist first, then Report, Daily Bands, Sector Analysis
        ws_shortlist = wb.active
        ws_shortlist.title = "Shortlist"

        ws_report = wb.create_sheet("Report")
        ws_bands = wb.create_sheet("Daily Bands")
        ws_sector = wb.create_sheet("Sector Analysis")

        # Build sheets
        self._build_report_sheet(ws_report, ticker_data_dict, fno_tickers, ticker_order)
        self._build_daily_bands_sheet(ws_bands, ticker_data_dict)
        self._build_sector_analysis_sheet(ws_sector, ticker_data_dict)
        self._build_shortlist_sheet(ws_shortlist, ticker_data_dict, fno_tickers)

        wb.save(output_filename)
        logger.info(f"Report saved: {output_filename}")
        return output_filename

    def _get_trading_dates(self, ticker_data_dict):
        all_dates = set()
        for df in ticker_data_dict.values():
            if not df.empty:
                all_dates.update(df['date'].tolist())
        trading_dates = sorted(list(all_dates))[-self.lookback_days:]
        if self.display_order == 'descending':
            trading_dates = sorted(trading_dates, reverse=True)
        return trading_dates

    # ═══════════════════════════════════════════════════════════════
    #  REPORT sheet
    # ═══════════════════════════════════════════════════════════════

    def _build_report_sheet(self, ws, ticker_data_dict, fno_tickers, ticker_order=None):
        if not ticker_data_dict:
            logger.warning("No ticker data to process")
            return

        trading_dates = self._get_trading_dates(ticker_data_dict)
        summary_col = self._SUMMARY_COL
        as_of_col = self._AS_OF_COL
        why_col = self._WHY_COL
        triple_confirm_col = self._TRIPLE_CONFIRM_COL
        date_col_start = self._DATE_COL_START

        # ── Header row 1 ──
        header_row = 1

        ws.cell(row=header_row, column=1, value="STOCK")
        ws.cell(row=header_row, column=2, value="MCAP")
        ws.cell(row=header_row, column=3, value="SEGMENT")
        ws.cell(row=header_row, column=4, value="STAGE")
        ws.cell(row=header_row, column=5, value="Wks Above")
        ws.cell(row=header_row, column=6, value="Wks Below")
        ws.cell(row=header_row, column=7, value="Price vs WMA")
        ws.cell(row=header_row, column=8, value="30WMA Slope")
        ws.cell(row=header_row, column=9, value="Cross↑")
        ws.cell(row=header_row, column=10, value="Vol Conf")
        ws.cell(row=header_row, column=11, value="Vol Ratio")
        ws.cell(row=header_row, column=12, value="52W High %")
        ws.cell(row=header_row, column=13, value="52W Low %")
        ws.cell(row=header_row, column=14, value="Near 52WH")
        ws.cell(row=header_row, column=15, value="RS vs NIFTY")
        ws.cell(row=header_row, column=16, value="RS Trend")
        ws.cell(row=header_row, column=17, value="RSI (14)")
        ws.cell(row=header_row, column=18, value="RSI Signal")

        ws.cell(row=header_row, column=19, value="PE")
        ws.cell(row=header_row, column=20, value="Sector PE")
        ws.cell(row=header_row, column=21, value="vs 200DMA")
        ws.cell(row=header_row, column=22, value="Promoter %")
        ws.cell(row=header_row, column=23, value="Profit Gr. YoY")

        ws.cell(row=header_row, column=24, value="ROC 1W")
        ws.cell(row=header_row, column=25, value="ROC 1M")
        ws.cell(row=header_row, column=26, value="ROC 3M")
        ws.cell(row=header_row, column=27, value="Momentum")
        ws.cell(row=header_row, column=28, value="Divergence")
        ws.cell(row=header_row, column=29, value="Squeeze")
        ws.cell(row=header_row, column=30, value="Sqz Ratio")

        ws.cell(row=header_row, column=summary_col, value="Dlv 10d")
        ws.cell(row=header_row, column=summary_col + 1, value="Dlv 30d")
        ws.cell(row=header_row, column=summary_col + 2, value="Dlv Trend")
        ws.cell(row=header_row, column=summary_col + 3, value="Divergence")
        ws.cell(row=header_row, column=summary_col + 4, value=f"N≥50%/{self.evaluation_days}")
        ws.cell(row=header_row, column=summary_col + 5, value=f"N≥40%/{self.evaluation_days}")
        ws.cell(row=header_row, column=summary_col + 6, value=f"N≥50%+HV/{self.evaluation_days}")
        ws.cell(row=header_row, column=summary_col + 7, value=f"N≥40%+HV/{self.evaluation_days}")
        ws.cell(row=header_row, column=summary_col + 8, value="N≥50%+HV/15d")
        ws.cell(row=header_row, column=summary_col + 9, value="N≥50%+HV/20d")

        ws.cell(row=header_row, column=summary_col + 10, value="Stage")
        ws.cell(row=header_row, column=summary_col + 11, value="Cross↓ WMA")
        ws.cell(row=header_row, column=summary_col + 12, value="Distrib Alert")
        ws.cell(row=header_row, column=summary_col + 13, value="Stage 3 Alert")
        ws.cell(row=header_row, column=summary_col + 14, value="Trend Break")
        ws.cell(row=header_row, column=summary_col + 15, value="vs 10MA")
        ws.cell(row=header_row, column=summary_col + 16, value="Dlv Momentum")
        ws.cell(row=header_row, column=summary_col + 17, value="Vol Spike↓")

        ws.cell(row=header_row, column=summary_col + 18, value="Stage 1 Alert")
        ws.cell(row=header_row, column=summary_col + 19, value="Stg1 Str (of 5)")

        ws.cell(row=header_row, column=as_of_col, value="As Of")
        ws.cell(row=header_row, column=self._PIVOT_COL, value="Pivot")
        ws.cell(row=header_row, column=self._DIST_PIVOT_COL, value="→Pivot %")
        ws.cell(row=header_row, column=self._STOP_COL, value="Stop")
        ws.cell(row=header_row, column=self._DIST_STOP_COL, value="→Stop %")
        ws.cell(row=header_row, column=self._BASE_WK_COL, value="Base Wks")
        ws.cell(row=header_row, column=why_col, value="Why")
        ws.cell(row=header_row, column=triple_confirm_col, value="Triple Confirm")

        # Date columns
        for idx, date in enumerate(trading_dates):
            col = date_col_start + idx
            date_str = date.strftime(self._get_date_format())
            ws.cell(row=header_row, column=col, value=date_str)

        last_col = date_col_start + len(trading_dates) - 1
        self._style_header_row(ws, header_row, last_col)

        # ── Ticker rows ──
        if ticker_order:
            tickers_to_process = [t for t in ticker_order if t in ticker_data_dict]
        else:
            tickers_to_process = sorted(ticker_data_dict.keys())

        current_row = header_row + 1
        for ticker in tickers_to_process:
            df = ticker_data_dict[ticker]
            is_fno = ticker in fno_tickers
            self._add_ticker_row(ws, current_row, ticker, df, trading_dates,
                                 date_col_start, summary_col, as_of_col, why_col,
                                 triple_confirm_col, is_fno)
            current_row += 1

        last_data_row = current_row - 1

        # ── Autofilter & freeze panes ──
        ws.auto_filter.ref = f"A{header_row}:{get_column_letter(last_col)}{last_data_row}"
        ws.freeze_panes = ws.cell(row=header_row + 1, column=2)

        self._adjust_column_widths(ws, last_col)

    def _add_ticker_row(self, ws, row, ticker, df, trading_dates,
                        date_col_start, summary_col, as_of_col, why_col,
                        triple_confirm_col, is_fno):
        latest_data = df.iloc[-1] if not df.empty else None
        metadata = self.ticker_metadata.get(ticker, {})

        sell_fill = _FILL_RED_SELL
        warn_fill = _FILL_YELLOW_WARN
        s1_fill = _FILL_GREEN_STAGE1
        s1_strong_fill = _FILL_GREEN_STAGE1_STRONG
        buy_fill = _FILL_GREEN_BUY

        def _get(col, default='N/A'):
            if latest_data is not None and col in df.columns:
                val = latest_data[col]
                return val if pd.notna(val) else default
            return default

        def _num(val, default=None):
            """Return a numeric value or default for blank cells."""
            if pd.notna(val):
                return float(val)
            return default

        # ── Helper: write a numeric cell with format ──
        def _pct(col_letter, val, fmt=_NUMBER_FMT_PCT):
            """Write a percentage value as a decimal number (e.g. 5.2% → 0.052)."""
            c = ws.cell(row=row, column=col_letter)
            if pd.notna(val):
                c.value = round(float(val) / 100.0, 6)
                c.number_format = fmt
            else:
                c.value = None

        def _num_cell(col_letter, val, fmt=_NUMBER_FMT_1DP):
            c = ws.cell(row=row, column=col_letter)
            if pd.notna(val):
                c.value = float(val)
                c.number_format = fmt
            else:
                c.value = None

        def _int_cell(col_letter, val):
            c = ws.cell(row=row, column=col_letter)
            if pd.notna(val):
                c.value = int(val)
                c.number_format = _NUMBER_FMT_INT
            else:
                c.value = None

        # ── Col 1: STOCK ──
        stock_cell = ws.cell(row=row, column=1, value=ticker)

        # ── Col 2-4: MCAP, SEGMENT, STAGE ──
        ws.cell(row=row, column=2, value=metadata.get('mcap', ''))
        ws.cell(row=row, column=3, value=metadata.get('department', ''))
        stage_cell = ws.cell(row=row, column=4, value=_get('stage'))

        # ── Col 5-6: Weeks Above/Below ──
        _int_cell(5, _get('weeks_above_wma', 0))
        _int_cell(6, _get('weeks_below_wma', 0))

        # ── Col 7-8: Price vs WMA, Slope ──
        ws.cell(row=row, column=7, value=_get('price_vs_wma'))
        ws.cell(row=row, column=8, value=_get('wma_slope'))

        # ── Col 9-11: Cross + Vol ──
        has_cross_above = False
        cross_confirmed = False
        if 'cross_above' in df.columns and len(df) >= 1:
            latest_week = df.iloc[-1].get('week')
            if latest_week is not None:
                cw = df[df['week'] == latest_week]
                has_cross_above = cw['cross_above'].any()
                if has_cross_above and 'cross_above_confirmed' in df.columns:
                    cross_confirmed = cw['cross_above_confirmed'].any()
            if not has_cross_above and len(df['week'].unique()) >= 2:
                pw = df[df['week'] == df['week'].unique()[-2]]
                has_cross_above = pw['cross_above'].any()
                if has_cross_above and 'cross_above_confirmed' in df.columns:
                    cross_confirmed = pw['cross_above_confirmed'].any()

        cross_cell = ws.cell(row=row, column=9, value="✓" if has_cross_above else "")
        vol_conf_cell = ws.cell(row=row, column=10,
                                value="✓ Vol" if cross_confirmed else ("No Vol" if has_cross_above else ""))
        if cross_confirmed:
            cross_cell.fill = buy_fill
            cross_cell.font = _FONT_BOLD_WHITE
            vol_conf_cell.fill = buy_fill
            vol_conf_cell.font = _FONT_BOLD_WHITE
        elif has_cross_above:
            cross_cell.fill = warn_fill
            cross_cell.font = _FONT_BOLD
            vol_conf_cell.fill = warn_fill

        vol_ratio = _get('vol_ratio', None)
        vol_ratio_cell = ws.cell(row=row, column=11)
        if pd.notna(vol_ratio):
            vol_ratio_cell.value = round(float(vol_ratio), 1)
            vol_ratio_cell.number_format = _NUMBER_FMT_1DP
        if pd.notna(vol_ratio) and vol_ratio >= 2.0:
            vol_ratio_cell.font = _FONT_BOLD
            vol_ratio_cell.fill = _FILL_GREEN_LIGHT

        # ── Col 12-14: 52W metrics ──
        high_52w_pct = _get('52w_high_pct', None)
        _pct(12, high_52w_pct)
        high_52w_cell = ws.cell(row=row, column=12)

        low_52w_pct = _get('52w_low_pct', None)
        _pct(13, low_52w_pct)
        low_52w_cell = ws.cell(row=row, column=13)

        near_52w = _get('near_52w_high')
        near_52w_cell = ws.cell(row=row, column=14, value=near_52w)
        if near_52w == 'Yes':
            high_52w_cell.fill = self.colors['gold']
            near_52w_cell.fill = self.colors['gold']
            high_52w_cell.font = _FONT_BOLD
            near_52w_cell.font = _FONT_BOLD

        # ── Col 15-16: RS vs NIFTY ──
        rs_ratio = _get('rs_ratio', None)
        _pct(15, rs_ratio)
        rs_cell = ws.cell(row=row, column=15)
        rs_trend = _get('rs_trend')
        rs_signal = _get('rs_signal')
        rs_trend_cell = ws.cell(row=row, column=16, value=rs_trend)

        if rs_signal == 'Outperform':
            rs_cell.fill = _FILL_GREEN_LIGHT
        elif rs_signal == 'Underperform':
            rs_cell.fill = _FILL_PINK_LIGHT
        if rs_trend == 'Improving':
            rs_trend_cell.fill = _FILL_GREEN_LIGHT
        elif rs_trend == 'Weakening':
            rs_trend_cell.fill = _FILL_PINK_LIGHT

        # ── Col 17-18: RSI ──
        rsi_value = _get('rsi', None)
        _num_cell(17, rsi_value, _NUMBER_FMT_1DP)
        rsi_cell = ws.cell(row=row, column=17)
        rsi_signal = _get('rsi_signal')
        rsi_signal_cell = ws.cell(row=row, column=18, value=rsi_signal)
        if rsi_signal == 'Overbought' and pd.notna(rsi_value):
            rsi_cell.fill = _FILL_PINK_RSI
            rsi_signal_cell.fill = _FILL_PINK_RSI
        elif rsi_signal == 'Oversold' and pd.notna(rsi_value):
            rsi_cell.fill = _FILL_GREEN_STAGE1
            rsi_signal_cell.fill = _FILL_GREEN_STAGE1

        # ── Col 19-23: Fundamentals ──
        pe_ratio = _get('pe_ratio', None)
        _num_cell(19, pe_ratio, _NUMBER_FMT_1DP)
        pe_cell = ws.cell(row=row, column=19)

        sector_pe = _get('sector_pe', None)
        _num_cell(20, sector_pe, _NUMBER_FMT_1DP)
        sector_pe_cell = ws.cell(row=row, column=20)

        price_vs_200dma = _get('price_vs_200dma', None)
        _pct(21, price_vs_200dma)
        dma200_cell = ws.cell(row=row, column=21)

        promoter_pct = _get('promoter_pct', None)
        promoter_change = _get('promoter_change', None)
        _pct(22, promoter_pct, _NUMBER_FMT_PCT2)
        promoter_cell = ws.cell(row=row, column=22)

        profit_growth = _get('profit_growth_yoy', None)
        _pct(23, profit_growth)
        profit_cell = ws.cell(row=row, column=23)

        # PE colour
        if pd.notna(pe_ratio) and pd.notna(sector_pe) and sector_pe > 0:
            if pe_ratio < sector_pe * 0.8:
                pe_cell.fill = _FILL_GREEN_LIGHT
            elif pe_ratio > sector_pe * 1.5:
                pe_cell.fill = _FILL_PINK_LIGHT
        # 200DMA colour
        if pd.notna(price_vs_200dma):
            if price_vs_200dma >= 0:
                dma200_cell.fill = _FILL_GREEN_LIGHT
            else:
                dma200_cell.fill = _FILL_PINK_LIGHT
        # Promoter colour
        if pd.notna(promoter_change) and promoter_change > 0:
            promoter_cell.fill = buy_fill
            promoter_cell.font = _FONT_BOLD_WHITE
        elif pd.notna(promoter_change) and promoter_change < -1:
            promoter_cell.fill = sell_fill
            promoter_cell.font = _FONT_BOLD_WHITE
        elif pd.notna(promoter_pct):
            if promoter_pct >= 60:
                promoter_cell.fill = _FILL_GREEN_LIGHT
            elif promoter_pct < 30:
                promoter_cell.fill = _FILL_PINK_LIGHT
        # Profit colour
        if pd.notna(profit_growth):
            if profit_growth > 20:
                profit_cell.fill = _FILL_GREEN_LIGHT
                profit_cell.font = _FONT_BOLD
            elif profit_growth < -20:
                profit_cell.fill = _FILL_PINK_LIGHT

        # ── Col 24-30: Momentum, Divergence, Squeeze ──
        roc_1w = _get('roc_1w', None)
        roc_1m = _get('roc_1m', None)
        roc_3m = _get('roc_3m', None)
        _pct(24, roc_1w)
        _pct(25, roc_1m)
        _pct(26, roc_3m)
        roc_1w_cell = ws.cell(row=row, column=24)
        roc_1m_cell = ws.cell(row=row, column=25)
        roc_3m_cell = ws.cell(row=row, column=26)

        momentum_align = _get('momentum_align')
        divergence = _get('divergence')
        squeeze = _get('squeeze')
        squeeze_ratio = _get('squeeze_ratio', None)

        momentum_cell = ws.cell(row=row, column=27, value=momentum_align)
        divergence_cell = ws.cell(row=row, column=28, value=divergence)
        squeeze_cell = ws.cell(row=row, column=29, value=squeeze)
        _num_cell(30, squeeze_ratio, _NUMBER_FMT_2DP)
        squeeze_ratio_cell = ws.cell(row=row, column=30)

        # ROC colours
        for rc, rv in [(roc_1w_cell, roc_1w), (roc_1m_cell, roc_1m), (roc_3m_cell, roc_3m)]:
            if pd.notna(rv):
                rc.fill = _FILL_GREEN_LIGHT if rv > 0 else _FILL_PINK_LIGHT

        if momentum_align == 'All Up':
            momentum_cell.fill = buy_fill; momentum_cell.font = _FONT_BOLD_WHITE
        elif momentum_align == 'Reversing Up':
            momentum_cell.fill = _FILL_GREEN_LIGHT; momentum_cell.font = _FONT_BOLD
        elif momentum_align == 'All Down':
            momentum_cell.fill = sell_fill; momentum_cell.font = _FONT_BOLD_WHITE
        elif momentum_align == 'Breaking Down':
            momentum_cell.fill = _FILL_PINK_LIGHT

        if divergence == 'Bullish':
            divergence_cell.fill = buy_fill; divergence_cell.font = _FONT_BOLD_WHITE
        elif divergence == 'Bearish':
            divergence_cell.fill = sell_fill; divergence_cell.font = _FONT_BOLD_WHITE

        if squeeze == 'Coiling':
            squeeze_cell.fill = _FILL_ORANGE; squeeze_cell.font = _FONT_BOLD_WHITE
            squeeze_ratio_cell.fill = _FILL_ORANGE; squeeze_ratio_cell.font = _FONT_BOLD_WHITE
        elif squeeze == 'Tight':
            squeeze_cell.fill = _FILL_YELLOW_SQUEEZE
            squeeze_ratio_cell.fill = _FILL_YELLOW_SQUEEZE

        # ── Summary columns (31+) ──
        deliv_avg_10d = _get('deliv_avg_10d', None)
        deliv_avg_30d = _get('deliv_avg_30d', None)
        deliv_trend = _get('deliv_trend')

        _pct(summary_col, deliv_avg_10d)
        _pct(summary_col + 1, deliv_avg_30d)
        ws.cell(row=row, column=summary_col + 2, value=deliv_trend)
        # col 34 (was Accum Score): show divergence — the price/delivery
        # divergence signal already computed at column 28; repeating it here
        # next to the delivery columns it relates to makes for easier scanning
        divergence_val = _get('divergence')
        div_cell = ws.cell(row=row, column=summary_col + 3, value=divergence_val)
        if divergence_val == 'Bullish':
            div_cell.fill = buy_fill; div_cell.font = _FONT_BOLD_WHITE
        elif divergence_val == 'Bearish':
            div_cell.fill = sell_fill; div_cell.font = _FONT_BOLD_WHITE

        if not hasattr(self, '_calculator'):
            from calculations import StockCalculator
            self._calculator = StockCalculator(self.config)
        summary = self._calculator.calculate_summary_counts(df, self.evaluation_days)

        _int_cell(summary_col + 4, summary['count_purple_darkgreen_lightgreen'])
        _int_cell(summary_col + 5, summary['count_including_blue'])
        _int_cell(summary_col + 6, summary['count_excl_blue_highvol'])
        _int_cell(summary_col + 7, summary['count_incl_blue_highvol'])
        _int_cell(summary_col + 8, summary['count_excl_blue_highvol_15d'])
        _int_cell(summary_col + 9, summary['count_excl_blue_highvol_20d'])

        # ── Sell signals ──
        # col 41 (was Exit Score): repeat the Stage, so the sell-signal block
        # starts with the context (Stage 3/4 = distribution zone, Stage 1/2 =
        # less concerning for any alerts in this block)
        stage_val = _get('stage')
        stage_cell = ws.cell(row=row, column=summary_col + 10, value=stage_val)
        if stage_val in ['Stage 3', 'Stage 4']:
            stage_cell.fill = sell_fill; stage_cell.font = _FONT_BOLD_WHITE
        elif stage_val == 'Stage 1':
            stage_cell.fill = _FILL_GREEN_STAGE1

        for ci, key in [(summary_col + 11, 'cross_below_alert'),
                         (summary_col + 12, 'distribution_alert'),
                         (summary_col + 13, 'stage_3_alert'),
                         (summary_col + 14, 'trend_break'),
                         (summary_col + 15, 'price_vs_10ma'),
                         (summary_col + 16, 'deliv_momentum'),
                         (summary_col + 17, 'vol_spike_down')]:
            ws.cell(row=row, column=ci, value=_get(key, '-'))

        cross_below_alert = _get('cross_below_alert', '-')
        distribution_alert = _get('distribution_alert', 'No')
        stage_3_alert = _get('stage_3_alert', '-')
        trend_break = _get('trend_break', 'Neutral')
        price_vs_10ma = _get('price_vs_10ma')
        deliv_momentum = _get('deliv_momentum')
        vol_spike_down = _get('vol_spike_down', 'No')

        if cross_below_alert == 'SELL (Vol)':
            ws.cell(row=row, column=summary_col + 11).fill = sell_fill
            ws.cell(row=row, column=summary_col + 11).font = _FONT_BOLD_WHITE
        elif cross_below_alert == 'SELL':
            ws.cell(row=row, column=summary_col + 11).fill = warn_fill
            ws.cell(row=row, column=summary_col + 11).font = _FONT_BOLD

        if distribution_alert == 'Yes':
            ws.cell(row=row, column=summary_col + 12).fill = sell_fill
            ws.cell(row=row, column=summary_col + 12).font = _FONT_BOLD
        if stage_3_alert == 'Exit Signal':
            ws.cell(row=row, column=summary_col + 13).fill = sell_fill
            ws.cell(row=row, column=summary_col + 13).font = _FONT_BOLD
        if trend_break == 'Lower High':
            ws.cell(row=row, column=summary_col + 14).fill = warn_fill
        if price_vs_10ma == 'Below':
            ws.cell(row=row, column=summary_col + 15).fill = warn_fill
        if deliv_momentum == 'Declining':
            ws.cell(row=row, column=summary_col + 16).fill = warn_fill
        if vol_spike_down == 'Yes':
            ws.cell(row=row, column=summary_col + 17).fill = warn_fill

        # ── Stage 1 Alert ──
        stage1_alert = _get('stage1_alert', 'No')
        stage1_strength = _get('stage1_strength', 0)
        ws.cell(row=row, column=summary_col + 18, value=stage1_alert)
        _int_cell(summary_col + 19, stage1_strength)

        if stage1_alert == 'Yes':
            if stage1_strength >= 4:
                ws.cell(row=row, column=summary_col + 18).fill = s1_strong_fill
                ws.cell(row=row, column=summary_col + 19).fill = s1_strong_fill
                ws.cell(row=row, column=summary_col + 18).font = _FONT_BOLD
                ws.cell(row=row, column=summary_col + 19).font = _FONT_BOLD
            else:
                ws.cell(row=row, column=summary_col + 18).fill = s1_fill
                ws.cell(row=row, column=summary_col + 19).fill = s1_fill
                ws.cell(row=row, column=summary_col + 18).font = _FONT_BOLD

        # ── As Of ──
        data_date = df['date'].max()
        as_of_display = pd.Timestamp(data_date).strftime('%d-%b-%Y') if pd.notna(data_date) else 'N/A'
        as_of_cell = ws.cell(row=row, column=as_of_col, value=as_of_display)
        if pd.notna(data_date):
            days_behind = (datetime.now() - pd.Timestamp(data_date)).days
            if days_behind > self.stale_days_threshold:
                as_of_cell.fill = self.colors['grey']
                as_of_cell.font = _FONT_BOLD

        # ── Pivot / Stop levels ──
        pivot_price = _get('pivot_price', None)
        dist_pivot = _get('dist_to_pivot_pct', None)
        stop_level = _get('stop_level', None)
        dist_stop = _get('dist_to_stop_pct', None)
        base_wks = _get('base_length_weeks', None)

        _num_cell(self._PIVOT_COL, pivot_price, _NUMBER_FMT_2DP)
        _pct(self._DIST_PIVOT_COL, dist_pivot)
        _num_cell(self._STOP_COL, stop_level, _NUMBER_FMT_2DP)
        _pct(self._DIST_STOP_COL, dist_stop)
        _int_cell(self._BASE_WK_COL, base_wks)

        # Highlight the actionable entry zone: at or just through the pivot
        # (Weinstein buys the breakout and warns against chasing far past it).
        if pd.notna(dist_pivot):
            dp_cell = ws.cell(row=row, column=self._DIST_PIVOT_COL)
            if -2 <= dist_pivot <= 5:
                dp_cell.fill = buy_fill
                dp_cell.font = _FONT_BOLD_WHITE
            elif dist_pivot > 15:
                dp_cell.fill = warn_fill      # extended — poor risk/reward entry
        # Flag a stop that is uncomfortably far away
        if pd.notna(dist_stop):
            ds_cell = ws.cell(row=row, column=self._DIST_STOP_COL)
            if dist_stop > 15:
                ds_cell.fill = _FILL_PINK_LIGHT

        # ── Why ──
        why_parts = []
        if has_cross_above and cross_confirmed:
            why_parts.append("Cross↑Vol")
        elif has_cross_above:
            why_parts.append("Cross↑")
        stage_val = _get('stage')
        if stage_val in ['Stage 2', 'Stage 2 (Pullback)']:
            why_parts.append(stage_val)
        if pd.notna(rs_ratio) and rs_ratio > 5:
            why_parts.append(f"RS{rs_ratio:+.0f}%")
        if pd.notna(deliv_avg_30d) and deliv_avg_30d >= 50:
            why_parts.append(f"Dlv{deliv_avg_30d:.0f}%")
        if pd.notna(dist_pivot) and -2 <= dist_pivot <= 5:
            why_parts.append("AtPivot")
        elif pd.notna(dist_pivot) and dist_pivot > 15:
            why_parts.append(f"Ext{dist_pivot:.0f}%")
        if stage_3_alert == 'Exit Signal':
            why_parts.append("EXIT")
        if stage1_alert == 'Yes':
            why_parts.append(f"S1-{int(stage1_strength)}")
        why_str = '; '.join(why_parts) if why_parts else ''
        ws.cell(row=row, column=why_col, value=why_str)

        # ── Corp Action ──
        # We don't have a dedicated column in the new layout (kept it minimal),
        # so if corp_action_suspected is 'Yes' anywhere in the data, append
        # '⚠CA' to the Why column.
        if 'corp_action_suspected' in df.columns and (df['corp_action_suspected'] == 'Yes').any():
            existing = ws.cell(row=row, column=why_col).value
            ws.cell(row=row, column=why_col, value=(str(existing) + ' ⚠CA').strip())

        # ── Triple Confirm (price > 30WMA + high volume + high delivery, today) ──
        triple_confirm = _get('triple_confirm', 'No')
        tc_cell = ws.cell(row=row, column=triple_confirm_col, value=triple_confirm)
        if triple_confirm == 'Yes':
            tc_cell.fill = buy_fill
            tc_cell.font = _FONT_BOLD_WHITE

        # ── FNO grey styling ──
        if is_fno:
            grey = self.colors['grey']
            grey_cols = [2, 3, 4, 5, 6, 7, 8, 12, 13, 14, 19, 20, 22,
                         summary_col, summary_col + 1, summary_col + 2, summary_col + 3,
                         summary_col + 4, summary_col + 5, summary_col + 6,
                         summary_col + 7, summary_col + 8, summary_col + 9,
                         30, 1]
            for gc in grey_cols:
                ws.cell(row=row, column=gc).fill = grey
            # Preserve highlights on signal columns
            if not has_cross_above:
                cross_cell.fill = grey; vol_conf_cell.fill = grey
            if not (pd.notna(vol_ratio) and vol_ratio >= 2.0):
                vol_ratio_cell.fill = grey
            if rs_signal not in ['Outperform', 'Underperform']:
                rs_cell.fill = grey
            if rs_trend not in ['Improving', 'Weakening']:
                rs_trend_cell.fill = grey
            if rsi_signal not in ['Overbought', 'Oversold']:
                rsi_cell.fill = grey; rsi_signal_cell.fill = grey
            if not pd.notna(price_vs_200dma):
                dma200_cell.fill = grey
            if not pd.notna(profit_growth):
                profit_cell.fill = grey
            for rc, rv in [(roc_1w_cell, roc_1w), (roc_1m_cell, roc_1m), (roc_3m_cell, roc_3m)]:
                if not pd.notna(rv):
                    rc.fill = grey
            if momentum_align not in ['All Up', 'Reversing Up', 'All Down', 'Breaking Down']:
                momentum_cell.fill = grey
            if divergence not in ['Bullish', 'Bearish']:
                divergence_cell.fill = grey
            if squeeze not in ['Coiling', 'Tight']:
                squeeze_cell.fill = grey
            if stage_val not in ['Stage 3', 'Stage 4', 'Stage 1']:
                stage_cell.fill = grey
            if cross_below_alert not in ['SELL', 'SELL (Vol)']:
                ws.cell(row=row, column=summary_col + 11).fill = grey
            if distribution_alert != 'Yes':
                ws.cell(row=row, column=summary_col + 12).fill = grey
            if stage_3_alert != 'Exit Signal':
                ws.cell(row=row, column=summary_col + 13).fill = grey
            if trend_break != 'Lower High':
                ws.cell(row=row, column=summary_col + 14).fill = grey
            if price_vs_10ma != 'Below':
                ws.cell(row=row, column=summary_col + 15).fill = grey
            if deliv_momentum != 'Declining':
                ws.cell(row=row, column=summary_col + 16).fill = grey
            if vol_spike_down != 'Yes':
                ws.cell(row=row, column=summary_col + 17).fill = grey
            if stage1_alert != 'Yes':
                ws.cell(row=row, column=summary_col + 18).fill = grey
                ws.cell(row=row, column=summary_col + 19).fill = grey

        # ── Centre-align everything ──
        for c in range(1, triple_confirm_col + 1):
            ws.cell(row=row, column=c).alignment = Alignment(horizontal='center', vertical='center')

        # ── Date columns ──
        for idx, date in enumerate(trading_dates):
            col = date_col_start + idx
            cell = ws.cell(row=row, column=col)
            date_data = df[df['date'] == date]
            if not date_data.empty:
                row_data = date_data.iloc[0]
                delivery_pct = row_data.get('delivery_pct')
                is_high_vol = row_data.get('is_high_vol', 'N/A')
                color_band = row_data.get('color_band', 'white')

                if pd.notna(delivery_pct):
                    cell.value = round(float(delivery_pct), 1)
                    cell.number_format = '0.0'
                cell.fill = self.colors.get(color_band, self.colors['white'])

                # Bold if high-vol day
                if is_high_vol == 'Yes':
                    cell.font = _FONT_BOLD
            else:
                cell.fill = self.colors['white']
            cell.alignment = Alignment(horizontal='center', vertical='center')

    def _style_header_row(self, ws, row, max_col):
        for col in range(1, max_col + 1):
            cell = ws.cell(row=row, column=col)
            cell.font = _FONT_BOLD
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            cell.fill = _FILL_GREY

    def _adjust_column_widths(self, ws, total_cols):
        widths = {1: 16, 2: 10, 3: 18, 4: 10, 5: 8, 6: 8, 7: 10, 8: 10,
                  9: 7, 10: 8, 11: 8, 12: 10, 13: 10, 14: 8, 15: 10,
                  16: 10, 17: 8, 18: 10, 19: 8, 20: 8, 21: 10, 22: 10,
                  23: 12, 24: 8, 25: 8, 26: 8, 27: 12, 28: 10, 29: 8, 30: 8}
        for c, w in widths.items():
            ws.column_dimensions[get_column_letter(c)].width = w
        # Summary cols all get 12
        for c in range(self._SUMMARY_COL, self._WHY_COL):
            ws.column_dimensions[get_column_letter(c)].width = 12
        ws.column_dimensions[get_column_letter(self._WHY_COL)].width = 28
        # Date cols
        for c in range(self._DATE_COL_START, total_cols + 1):
            ws.column_dimensions[get_column_letter(c)].width = 7

    # ═══════════════════════════════════════════════════════════════
    #  DAILY BANDS sheet
    # ═══════════════════════════════════════════════════════════════

    def _build_daily_bands_sheet(self, ws, ticker_data_dict):
        trading_dates = self._get_trading_dates(ticker_data_dict)
        date_col_start = 2  # simpler layout: col A = label, cols B+ = dates

        daily_counts = {date: {'purple': 0, 'dark_green': 0, 'light_green': 0,
                               'blue': 0, 'cream': 0, 'white': 0} for date in trading_dates}
        for ticker, df in ticker_data_dict.items():
            if df.empty or 'color_band' not in df.columns:
                continue
            relevant = df[df['date'].isin(daily_counts.keys())]
            if relevant.empty:
                continue
            counts = relevant.groupby(['date', 'color_band']).size()
            for (date, band), count in counts.items():
                if band in daily_counts[date]:
                    daily_counts[date][band] += count

        # Title
        ws.cell(row=1, column=1, value="Delivery Band Daily Totals")
        ws.cell(row=1, column=1).font = _FONT_BOLD_SIZE14

        # Date headers
        for idx, date in enumerate(trading_dates):
            ws.cell(row=2, column=date_col_start + idx,
                    value=date.strftime('%d-%b')).font = _FONT_BOLD
            ws.cell(row=2, column=date_col_start + idx).alignment = Alignment(horizontal='center')

        current_row = 3

        # TOTAL row
        ws.cell(row=current_row, column=1, value="TOTAL (Vol>MA)").font = _FONT_BOLD
        for idx, date in enumerate(trading_dates):
            total = (daily_counts[date]['purple'] + daily_counts[date]['dark_green'] +
                    daily_counts[date]['light_green'] + daily_counts[date]['blue'] +
                    daily_counts[date]['cream'])
            cell = ws.cell(row=current_row, column=date_col_start + idx, value=total)
            cell.font = _FONT_BOLD
            cell.alignment = Alignment(horizontal='center')
        current_row += 1

        bands = ['purple', 'dark_green', 'light_green', 'blue', 'cream', 'white']
        band_labels = ['Purple (≥80%)', 'Dark Green (60-80%)', 'Light Green (50-60%)',
                      'Blue (40-50%)', 'Cream (Accum: <40%+HV)', 'White (LowVol)']

        for band, label in zip(bands, band_labels):
            ws.cell(row=current_row, column=1, value=label)
            label_cell = ws.cell(row=current_row, column=1)
            label_cell.fill = self.colors.get(band, self.colors['white'])
            label_cell.font = _FONT_BOLD
            for idx, date in enumerate(trading_dates):
                cell = ws.cell(row=current_row, column=date_col_start + idx,
                              value=daily_counts[date][band])
                cell.alignment = Alignment(horizontal='center')
            current_row += 1

        # Column widths
        ws.column_dimensions['A'].width = 28
        for c in range(date_col_start, date_col_start + len(trading_dates)):
            ws.column_dimensions[get_column_letter(c)].width = 6

    # ═══════════════════════════════════════════════════════════════
    #  SHORTLIST sheet
    # ═══════════════════════════════════════════════════════════════

    def _build_shortlist_sheet(self, ws, ticker_data_dict, fno_tickers):
        if not self.shortlist_config:
            ws.cell(row=1, column=1, value="Shortlist not configured — add 'shortlist' to config.json")
            return

        sl = self.shortlist_config
        min_adv = sl.get('min_adv_crore', 5)
        stages_ok = sl.get('stages', ['Stage 2', 'Stage 2 (Pullback)'])
        min_rs = sl.get('min_rs', 0)
        min_deliv = sl.get('min_deliv_30d', 45)
        exclude_ca = sl.get('exclude_corp_action', True)
        top_n = sl.get('top_n', 50)

        # Detect a universe-wide RS outage (NIFTY fetch AND cache fallback both
        # failed that run, or ran before any NIFTY cache existed) up front, so
        # the analyst sees it on the sheet instead of it silently degrading
        # the ranking to delivery-only with no visible sign anything is wrong.
        non_empty = [df for df in ticker_data_dict.values() if not df.empty]
        rs_covered = sum(1 for df in non_empty if pd.notna(df.iloc[-1].get('rs_ratio')))
        rs_outage = bool(non_empty) and rs_covered == 0

        candidates = []
        for ticker, df in ticker_data_dict.items():
            if df.empty:
                continue
            latest = df.iloc[-1]

            stage = latest.get('stage', 'N/A')
            rs_ratio = latest.get('rs_ratio')
            deliv_30d = latest.get('deliv_avg_30d')
            has_ca = ('corp_action_suspected' in df.columns and
                      (df['corp_action_suspected'] == 'Yes').any())

            # Filters
            if stage not in stages_ok:
                continue
            if exclude_ca and has_ca:
                continue

            # ADV filter — median, not mean. A single block-deal day can lift
            # a 20-day mean far above a stock's typical traded value and let an
            # illiquid name through a liquidity screen.
            if len(df) >= 20:
                recent = df.iloc[-20:]
                adv_cr = (recent['traded_quantity'] * recent['close']).median() / 1e7
                if pd.isna(adv_cr) or adv_cr < min_adv:
                    continue
            else:
                continue

            # These two filters FAIL CLOSED: a missing value is treated as
            # "does not qualify", not "passes". The previous
            # `pd.notna(x) and x < threshold` form let NaN through.
            # Two distinct cases, handled differently:
            #  - rs_outage (NO stock in the universe has RS): the filter cannot
            #    be applied at all. Bypass it rather than returning an empty
            #    sheet, and rely on the red banner set from rs_outage to make
            #    the degradation impossible to miss.
            #  - this one stock lacks RS (e.g. <52 rows of history): fail
            #    CLOSED. It has not demonstrated market leadership, so it does
            #    not belong on a Weinstein shortlist.
            if not rs_outage:
                if pd.isna(rs_ratio) or rs_ratio < min_rs:
                    continue
            if pd.isna(deliv_30d) or deliv_30d < min_deliv:
                continue

            # Collect for ranking
            weeks_above = latest.get('weeks_above_wma', 0)
            price_vs_wma = latest.get('price_vs_wma')
            vol_ratio = latest.get('vol_ratio')
            deliv_avg_10d = latest.get('deliv_avg_10d')
            high_52w_pct = latest.get('52w_high_pct')
            roc_1m = latest.get('roc_1m')
            promoter_pct = latest.get('promoter_pct')
            promoter_change = latest.get('promoter_change')
            profit_growth = latest.get('profit_growth_yoy')
            wma_slope = latest.get('wma_slope')
            squeeze = latest.get('squeeze')
            divergence = latest.get('divergence')
            cross_above = False
            cross_confirmed = False
            if 'cross_above' in df.columns:
                cw = df[df['week'] == df.iloc[-1].get('week')]
                cross_above = cw['cross_above'].any() if len(cw) > 0 else False
                if cross_above and 'cross_above_confirmed' in df.columns:
                    cross_confirmed = cw['cross_above_confirmed'].any()
            cross_below = latest.get('cross_below_alert', '-')
            triple_confirm = latest.get('triple_confirm', 'No')
            pivot_price = latest.get('pivot_price')
            dist_pivot = latest.get('dist_to_pivot_pct')
            stop_level = latest.get('stop_level')
            dist_stop = latest.get('dist_to_stop_pct')
            base_wks = latest.get('base_length_weeks')

            meta = self.ticker_metadata.get(ticker, {})
            candidates.append({
                'ticker': ticker,
                'stage': stage,
                'mcap': meta.get('mcap', ''),
                'sector': meta.get('department', ''),
                'has_rs': pd.notna(rs_ratio),
                'rs_ratio': rs_ratio if pd.notna(rs_ratio) else -999,
                'deliv_30d': deliv_30d if pd.notna(deliv_30d) else 0,
                'deliv_10d': deliv_avg_10d if pd.notna(deliv_avg_10d) else 0,
                'adv_cr': adv_cr,
                'high_52w_pct': high_52w_pct,
                'weeks_above': weeks_above,
                'price_vs_wma': price_vs_wma,
                'vol_ratio': vol_ratio,
                'roc_1m': roc_1m,
                'wma_slope': wma_slope,
                'squeeze': squeeze,
                'divergence': divergence,
                'cross_above': cross_above,
                'cross_confirmed': cross_confirmed,
                'cross_below': cross_below,
                'promoter_pct': promoter_pct,
                'promoter_change': promoter_change,
                'profit_growth': profit_growth,
                'has_ca': has_ca,
                'triple_confirm': triple_confirm,
                'pivot_price': pivot_price,
                'dist_pivot': dist_pivot,
                'stop_level': stop_level,
                'dist_stop': dist_stop,
                'base_wks': base_wks,
            })

        if not candidates:
            msg = (f"No stocks pass the shortlist filters "
                   f"(stages={stages_ok}, RS>={min_rs}%, "
                   f"Dlv30>={min_deliv}%, ADV>={min_adv}cr)")
            if rs_outage:
                msg += " — ⚠ RS vs NIFTY UNAVAILABLE THIS RUN (fetch and cache both failed)"
            ws.cell(row=1, column=1, value=msg)
            ws.column_dimensions['A'].width = 60
            return

        # Rank: blended composite of RS percentile and entry quality.
        #
        # RS ALONE is a poor sort key — by the time a stock has high relative
        # strength it has usually already moved past its pivot (corr +0.79 with
        # dist_to_pivot). RS belongs in the FILTER (min_rs: 0 keeps laggards out),
        # and entry quality belongs in the SORT.
        #
        # The composite:
        #   45% RS percentile (Weinstein's "buy market leaders" — still matters)
        #   55% entry score (proximity to pivot + tightness of stop)
        #   +bonus for fresh cross-above / Triple Confirm
        #
        # Entry score: 100 = at pivot +1.5% with a 0% stop, 0 = 15%+ extended
        # or 20%+ stop. Names with no base at all score 0 on the entry term
        # rather than being ranked on RS alone.
        n = len(candidates)
        rs_candidates = [c for c in candidates if c['has_rs']]
        sorted_by_rs = sorted(rs_candidates, key=lambda x: x['rs_ratio'])
        n_rs = len(sorted_by_rs)
        for i, c in enumerate(sorted_by_rs):
            c['rank_rs'] = (i / (n_rs - 1)) * 100 if n_rs > 1 else 50
        for c in candidates:
            if not c['has_rs']:
                c['rank_rs'] = 50

        for c in candidates:
            # Entry quality score: penalises distance from pivot and wide stops.
            # Peak score at dist_pivot ≈ +1.5% (just through the pivot — early
            # enough, but a clear breakout). Score decays to zero at ~14% extended
            # or 20% stop. Names with no base get zero — they can't be ranked on
            # entry quality because there is no entry level to measure against.
            entry_score = 0.0
            if pd.notna(c['dist_pivot']):
                entry_score += max(0.0, 100.0 - abs(c['dist_pivot'] - 1.5) * 8.0)
            if pd.notna(c['dist_stop']):
                entry_score += max(0.0, 100.0 - c['dist_stop'] * 5.0)
                entry_score /= 2.0  # average the two sub-scores
            else:
                # No stop means no base — entry_score stays 0 regardless of
                # any partial dist_pivot contribution
                entry_score = 0.0

            c['composite'] = 0.45 * c['rank_rs'] + 0.55 * entry_score
            if c['cross_confirmed']:
                c['composite'] += 12
            elif c['cross_above']:
                c['composite'] += 8
            if c['triple_confirm'] == 'Yes':
                c['composite'] += 5

        candidates.sort(key=lambda x: x['composite'], reverse=True)
        candidates = candidates[:top_n]

        # ── Title ──
        title = (f"Shortlist — {len(candidates)} stocks "
                 f"(Stage 2/2P, RS≥{min_rs}%, Dlv30≥{min_deliv}%, ADV≥{min_adv}cr)")
        if rs_outage:
            title += "  —  ⚠ RS vs NIFTY UNAVAILABLE THIS RUN"
        ws.cell(row=1, column=1, value=title)
        ws.cell(row=1, column=1).font = _FONT_RED_BOLD_SIZE14 if rs_outage else _FONT_BOLD_SIZE14
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=23)

        # ── Headers ──
        headers = ['Rank', 'STOCK', 'MCAP', 'Sector', 'Stage', 'RS %',
                   '52WH %', 'Wks▲', 'Dlv30', 'Dlv10', 'ADV cr',
                   'Cross', 'Vol Ratio', 'WMA Slope', 'Squeeze', 'Diverge',
                   'Promoter %', 'Pivot', '→Pivot %', 'Stop', '→Stop %',
                   'Base Wks', 'Why']
        hdr_row = 2
        for idx, h in enumerate(headers):
            cell = ws.cell(row=hdr_row, column=idx + 1, value=h)
            cell.font = _FONT_BOLD
            cell.fill = _FILL_GREY
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

        # ── Data rows ──
        for rank, c in enumerate(candidates, start=1):
            r = hdr_row + rank
            ws.cell(row=r, column=1, value=rank).alignment = Alignment(horizontal='center')
            stock_c = ws.cell(row=r, column=2, value=c['ticker'])
            stock_c.font = _FONT_BOLD
            stock_c.alignment = Alignment(horizontal='center')
            ws.cell(row=r, column=3, value=c['mcap']).alignment = Alignment(horizontal='center')
            ws.cell(row=r, column=4, value=c['sector']).alignment = Alignment(horizontal='center')
            ws.cell(row=r, column=5, value=c['stage']).alignment = Alignment(horizontal='center')
            _rs = ws.cell(row=r, column=6, value=round(c['rs_ratio'] / 100, 4) if c['rs_ratio'] != -999 else None)
            _rs.number_format = _NUMBER_FMT_PCT; _rs.alignment = Alignment(horizontal='center')
            _52 = ws.cell(row=r, column=7, value=round(c['high_52w_pct'] / 100, 4) if pd.notna(c['high_52w_pct']) else None)
            _52.number_format = _NUMBER_FMT_PCT; _52.alignment = Alignment(horizontal='center')
            _wa = ws.cell(row=r, column=8, value=int(c['weeks_above']) if pd.notna(c['weeks_above']) else 0)
            _wa.number_format = _NUMBER_FMT_INT; _wa.alignment = Alignment(horizontal='center')
            _d30 = ws.cell(row=r, column=9, value=round(c['deliv_30d'] / 100, 4) if c['deliv_30d'] else None)
            _d30.number_format = _NUMBER_FMT_PCT; _d30.alignment = Alignment(horizontal='center')
            _d10 = ws.cell(row=r, column=10, value=round(c['deliv_10d'] / 100, 4) if c['deliv_10d'] else None)
            _d10.number_format = _NUMBER_FMT_PCT; _d10.alignment = Alignment(horizontal='center')
            _adv = ws.cell(row=r, column=11, value=round(c['adv_cr'], 1))
            _adv.number_format = _NUMBER_FMT_1DP; _adv.alignment = Alignment(horizontal='center')

            # Cross column: green "✓Vol" for confirmed, yellow "✓" for unconfirmed
            cross_cell = ws.cell(row=r, column=12)
            if c['cross_confirmed']:
                cross_cell.value = '✓Vol'; cross_cell.fill = _FILL_GREEN_BUY
                cross_cell.font = _FONT_BOLD_WHITE
            elif c['cross_above']:
                cross_cell.value = '✓'; cross_cell.fill = _FILL_YELLOW_WARN
                cross_cell.font = _FONT_BOLD
            cross_cell.alignment = Alignment(horizontal='center')

            _vr = ws.cell(row=r, column=13, value=round(c['vol_ratio'], 1) if pd.notna(c['vol_ratio']) else None)
            _vr.number_format = _NUMBER_FMT_1DP; _vr.alignment = Alignment(horizontal='center')
            ws.cell(row=r, column=14, value=c['wma_slope']).alignment = Alignment(horizontal='center')
            ws.cell(row=r, column=15, value=c['squeeze']).alignment = Alignment(horizontal='center')

            # Divergence
            div_cell = ws.cell(row=r, column=16, value=c.get('divergence', 'N/A'))
            div_cell.alignment = Alignment(horizontal='center')
            if c.get('divergence') == 'Bullish':
                div_cell.fill = _FILL_GREEN_BUY; div_cell.font = _FONT_BOLD_WHITE
            elif c.get('divergence') == 'Bearish':
                div_cell.fill = _FILL_RED_SELL; div_cell.font = _FONT_BOLD_WHITE

            _pr = ws.cell(row=r, column=17, value=round(c['promoter_pct'] / 100, 4) if pd.notna(c['promoter_pct']) else None)
            _pr.number_format = _NUMBER_FMT_PCT2; _pr.alignment = Alignment(horizontal='center')

            # ── Entry / exit levels (cols 18-22) ──
            _pv = ws.cell(row=r, column=18, value=round(float(c['pivot_price']), 2) if pd.notna(c['pivot_price']) else None)
            _pv.number_format = _NUMBER_FMT_2DP; _pv.alignment = Alignment(horizontal='center')
            _dp = ws.cell(row=r, column=19, value=round(c['dist_pivot'] / 100, 4) if pd.notna(c['dist_pivot']) else None)
            _dp.number_format = _NUMBER_FMT_PCT; _dp.alignment = Alignment(horizontal='center')
            _st = ws.cell(row=r, column=20, value=round(float(c['stop_level']), 2) if pd.notna(c['stop_level']) else None)
            _st.number_format = _NUMBER_FMT_2DP; _st.alignment = Alignment(horizontal='center')
            _ds = ws.cell(row=r, column=21, value=round(c['dist_stop'] / 100, 4) if pd.notna(c['dist_stop']) else None)
            _ds.number_format = _NUMBER_FMT_PCT; _ds.alignment = Alignment(horizontal='center')
            _bw = ws.cell(row=r, column=22, value=int(c['base_wks']) if pd.notna(c['base_wks']) else None)
            _bw.number_format = _NUMBER_FMT_INT; _bw.alignment = Alignment(horizontal='center')

            # Entry zone: at or just through the pivot is the actionable window.
            if pd.notna(c['dist_pivot']):
                if -2 <= c['dist_pivot'] <= 5:
                    _dp.fill = _FILL_GREEN_BUY; _dp.font = _FONT_BOLD_WHITE
                elif c['dist_pivot'] > 15:
                    _dp.fill = _FILL_YELLOW_WARN
            # A stop more than 15% away is a poor-risk entry regardless of signal.
            if pd.notna(c['dist_stop']) and c['dist_stop'] > 15:
                _ds.fill = _FILL_PINK_LIGHT

            # Why
            why = []
            if c['cross_confirmed']:
                why.append('Cross↑Vol')
            elif c['cross_above']:
                why.append('Cross↑')
            if pd.notna(c['rs_ratio']) and c['rs_ratio'] > 5:
                why.append(f"RS{c['rs_ratio']:.0f}%")
            if c['deliv_30d'] >= 55:
                why.append(f"Dlv{c['deliv_30d']:.0f}%")
            if c['squeeze'] in ['Coiling', 'Tight']:
                why.append(c['squeeze'])
            if c['divergence'] == 'Bullish':
                why.append('BullDiv')
            if c['triple_confirm'] == 'Yes':
                why.append('3xConfirm')
            if pd.notna(c['dist_pivot']) and -2 <= c['dist_pivot'] <= 5:
                why.append('AtPivot')
            elif pd.notna(c['dist_pivot']) and c['dist_pivot'] > 15:
                why.append(f"Ext{c['dist_pivot']:.0f}%")
            if pd.notna(c['dist_stop']) and c['dist_stop'] > 15:
                why.append(f"Risk{c['dist_stop']:.0f}%")
            if c['has_ca']:
                why.append('⚠CA')
            ws.cell(row=r, column=23, value='; '.join(why))

            # FNO grey. NOTE: must use c['ticker'] — `ticker` here would be the
            # leftover loop variable from the candidate-collection loop above,
            # i.e. the LAST ticker in ticker_data_dict, so every row would be
            # greyed or none would be, regardless of actual F&O membership.
            if c['ticker'] in fno_tickers:
                for ci in range(3, 23):
                    ws.cell(row=r, column=ci).fill = self.colors['grey']

        # Autofilter, freeze
        last_data_row = hdr_row + len(candidates)
        ws.auto_filter.ref = f"A{hdr_row}:W{last_data_row}"
        ws.freeze_panes = ws.cell(row=hdr_row + 1, column=3)

        # Column widths
        col_widths = {1: 5, 2: 16, 3: 10, 4: 16, 5: 16, 6: 6, 7: 7, 8: 7,
                      9: 6, 10: 7, 11: 7, 12: 8, 13: 5, 14: 7, 15: 8, 16: 8,
                      17: 8, 18: 10, 19: 9, 20: 10, 21: 9, 22: 7, 23: 32}
        for c, w in col_widths.items():
            ws.column_dimensions[get_column_letter(c)].width = w

    # ═══════════════════════════════════════════════════════════════
    #  SECTOR ANALYSIS sheet
    # ═══════════════════════════════════════════════════════════════

    def _build_sector_analysis_sheet(self, ws, ticker_data_dict):
        logger.info("Building Sector Analysis sheet...")

        all_dates = set()
        for df in ticker_data_dict.values():
            if not df.empty:
                all_dates.update(df['date'].tolist())
        if not all_dates:
            ws.cell(row=1, column=1, value="No data available")
            return

        trading_dates = sorted(list(all_dates))[-5:]

        sectors = set()
        for ticker, metadata in self.ticker_metadata.items():
            sectors.add(metadata.get('department', 'Unknown'))
        for ticker in ticker_data_dict:
            if ticker not in self.ticker_metadata:
                sectors.add('Unknown')
        sectors = sorted(list(sectors))

        color_bands = ['Purple (≥80%)', 'Dark Green (60-80%)',
                      'Light Green (50-60%)', 'Blue (40-50%)',
                      'Cream (Accum)', 'White (LowVol)']
        band_keys = ['purple', 'dark_green', 'light_green', 'blue', 'cream', 'white']

        ws.cell(row=1, column=1, value="SECTOR-WISE ACCUMULATION ANALYSIS")
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(sectors) + 2)
        title_cell = ws.cell(row=1, column=1)
        title_cell.font = _FONT_BOLD_SIZE14
        title_cell.alignment = Alignment(horizontal='center')

        ws.cell(row=2, column=1,
                value=f"Last 5 Trading Days: {trading_dates[0].strftime('%d-%b')} to {trading_dates[-1].strftime('%d-%b-%Y')}")
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(sectors) + 2)
        ws.cell(row=2, column=1).font = _FONT_ITALIC_SIZE11
        ws.cell(row=2, column=1).alignment = Alignment(horizontal='center')

        current_row = 4

        for day_idx, date in enumerate(trading_dates):
            date_str = date.strftime('%d-%b-%Y (%a)')
            ws.cell(row=current_row, column=1, value=f"Day {day_idx + 1}: {date_str}")
            ws.merge_cells(start_row=current_row, start_column=1,
                          end_row=current_row, end_column=len(sectors) + 2)
            dh = ws.cell(row=current_row, column=1)
            dh.fill = _FILL_BLUE_DARK; dh.font = _FONT_BOLD_SIZE12_WHITE
            current_row += 1

            ws.cell(row=current_row, column=1, value="Delivery Band")
            for idx, sector in enumerate(sectors):
                ws.cell(row=current_row, column=idx + 2, value=sector)
            ws.cell(row=current_row, column=len(sectors) + 2, value="TOTAL")
            for col in range(1, len(sectors) + 3):
                cell = ws.cell(row=current_row, column=col)
                cell.font = _FONT_BOLD; cell.fill = _FILL_BLUE_HEADER
                cell.alignment = Alignment(horizontal='center', vertical='center')
                cell.border = Border(left=Side(style='thin'), right=Side(style='thin'),
                                     top=Side(style='thin'), bottom=Side(style='thin'))
            current_row += 1

            sector_band_counts = {s: {b: 0 for b in band_keys} for s in sectors}
            for ticker, df in ticker_data_dict.items():
                metadata = self.ticker_metadata.get(ticker, {})
                sector = metadata.get('department', 'Unknown')
                if sector not in sectors:
                    continue
                date_data = df[df['date'] == date]
                if not date_data.empty:
                    color_band = date_data.iloc[0].get('color_band', 'white')
                    if color_band in sector_band_counts[sector]:
                        sector_band_counts[sector][color_band] += 1

            for band_label, band_key in zip(color_bands, band_keys):
                ws.cell(row=current_row, column=1, value=band_label)
                lc = ws.cell(row=current_row, column=1)
                lc.fill = self.colors.get(band_key, self.colors['white'])
                lc.font = _FONT_BOLD
                lc.alignment = Alignment(horizontal='left', vertical='center')
                lc.border = Border(left=Side(style='thin'), right=Side(style='thin'),
                                   top=Side(style='thin'), bottom=Side(style='thin'))

                row_total = 0
                for idx, sector in enumerate(sectors):
                    count = sector_band_counts[sector][band_key]
                    cell = ws.cell(row=current_row, column=idx + 2,
                                  value=count if count > 0 else "")
                    cell.alignment = Alignment(horizontal='center', vertical='center')
                    cell.border = Border(left=Side(style='thin'), right=Side(style='thin'),
                                         top=Side(style='thin'), bottom=Side(style='thin'))
                    row_total += count
                    if count >= 3:
                        cell.font = _FONT_BOLD; cell.fill = _FILL_YELLOW_SQUEEZE

                tc = ws.cell(row=current_row, column=len(sectors) + 2,
                            value=row_total if row_total > 0 else "")
                tc.font = _FONT_BOLD; tc.alignment = Alignment(horizontal='center', vertical='center')
                tc.border = Border(left=Side(style='thin'), right=Side(style='thin'),
                                   top=Side(style='thin'), bottom=Side(style='thin'))
                current_row += 1

            # TOTAL row
            ws.cell(row=current_row, column=1, value="TOTAL STOCKS")
            trc = ws.cell(row=current_row, column=1)
            trc.font = _FONT_BOLD; trc.fill = _FILL_GREEN_LIGHT
            grand_total = 0
            for idx, sector in enumerate(sectors):
                st = sum(sector_band_counts[sector].values())
                cell = ws.cell(row=current_row, column=idx + 2, value=st if st > 0 else "")
                cell.font = _FONT_BOLD; cell.fill = _FILL_GREEN_LIGHT
                cell.alignment = Alignment(horizontal='center', vertical='center')
                cell.border = Border(left=Side(style='thin'), right=Side(style='thin'),
                                     top=Side(style='thin'), bottom=Side(style='thin'))
                grand_total += st
            gtc = ws.cell(row=current_row, column=len(sectors) + 2, value=grand_total)
            gtc.font = _FONT_BOLD; gtc.fill = _FILL_GREEN_MED
            gtc.alignment = Alignment(horizontal='center', vertical='center')
            gtc.border = Border(left=Side(style='thin'), right=Side(style='thin'),
                                top=Side(style='thin'), bottom=Side(style='thin'))
            current_row += 2

        # Summary trend
        current_row += 1
        ws.cell(row=current_row, column=1, value="5-DAY ACCUMULATION SUMMARY (High Quality Stocks)")
        ws.merge_cells(start_row=current_row, start_column=1,
                      end_row=current_row, end_column=len(sectors) + 2)
        sh = ws.cell(row=current_row, column=1)
        sh.font = _FONT_BOLD_SIZE12; sh.fill = _FILL_ORANGE_LIGHT
        current_row += 1

        ws.cell(row=current_row, column=1, value="Sector")
        ws.cell(row=current_row, column=2, value="Avg Purple+DGreen")
        ws.cell(row=current_row, column=3, value="Avg Total Accum")
        ws.cell(row=current_row, column=4, value="Trend")
        ws.cell(row=current_row, column=5, value="Rank")
        for col in range(1, 6):
            cell = ws.cell(row=current_row, column=col)
            cell.font = _FONT_BOLD; cell.fill = _FILL_BLUE_HEADER
            cell.alignment = Alignment(horizontal='center', vertical='center')
        current_row += 1

        sector_summary = {}
        for sector in sectors:
            hq_counts, ta_counts = [], []
            for date in trading_dates:
                sbc = {b: 0 for b in band_keys}
                for ticker, df in ticker_data_dict.items():
                    metadata = self.ticker_metadata.get(ticker, {})
                    if metadata.get('department', 'Unknown') != sector:
                        continue
                    dd = df[df['date'] == date]
                    if not dd.empty:
                        cb = dd.iloc[0].get('color_band', 'white')
                        if cb in sbc:
                            sbc[cb] += 1
                hq = sbc['purple'] + sbc['dark_green']
                ta = sbc['purple'] + sbc['dark_green'] + sbc['light_green'] + sbc['blue']
                hq_counts.append(hq); ta_counts.append(ta)

            avg_hq = sum(hq_counts) / len(hq_counts) if hq_counts else 0
            avg_ta = sum(ta_counts) / len(ta_counts) if ta_counts else 0
            if len(hq_counts) >= 2:
                ea = (hq_counts[0] + hq_counts[1]) / 2
                ra = (hq_counts[-2] + hq_counts[-1]) / 2
                trend = "▲ Increasing" if ra > ea + 1 else ("▼ Decreasing" if ra < ea - 1 else "→ Stable")
            else:
                trend = "N/A"
            sector_summary[sector] = {'avg_high_quality': avg_hq, 'avg_total_accum': avg_ta, 'trend': trend}

        sorted_sectors = sorted(sectors, key=lambda s: sector_summary[s]['avg_high_quality'], reverse=True)
        for rank, sector in enumerate(sorted_sectors, start=1):
            s = sector_summary[sector]
            ws.cell(row=current_row, column=1, value=sector)
            ws.cell(row=current_row, column=2, value=f"{s['avg_high_quality']:.1f}")
            ws.cell(row=current_row, column=3, value=f"{s['avg_total_accum']:.1f}")
            ws.cell(row=current_row, column=4, value=s['trend'])
            ws.cell(row=current_row, column=5, value=rank)
            if rank <= 5:
                for col in range(1, 6):
                    ws.cell(row=current_row, column=col).fill = _FILL_GREEN_MED
                    ws.cell(row=current_row, column=col).font = _FONT_BOLD
            for col in range(2, 6):
                ws.cell(row=current_row, column=col).alignment = Alignment(horizontal='center', vertical='center')
            current_row += 1

        ws.column_dimensions['A'].width = 25
        for col in range(2, len(sectors) + 3):
            ws.column_dimensions[get_column_letter(col)].width = 18
        logger.info("Sector Analysis sheet completed")

    # ═══════════════════════════════════════════════════════════════
    #  Helpers
    # ═══════════════════════════════════════════════════════════════

    def _get_date_format(self):
        format_map = {'DD-MM-YYYY': '%d-%m-%Y', 'DD/MM/YYYY': '%d/%m/%Y',
                      'MM-DD-YYYY': '%m-%d-%Y', 'MM/DD/YYYY': '%m/%d/%Y',
                      'YYYY-MM-DD': '%Y-%m-%d'}
        return format_map.get(self.date_format, '%d-%m-%Y')

    def _load_ticker_metadata(self):
        import json, os
        metadata_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      'Stock_Information', 'ticker_metadata.json')
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Could not load ticker metadata: {e}")
                return {}
        return {}