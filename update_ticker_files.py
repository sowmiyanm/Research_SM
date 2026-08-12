#!/usr/bin/env python3
"""
Utility to update ticker.txt and fno_tickers.txt from Excel files in Stock_Information folder
"""

import pandas as pd
import os
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def update_ticker_files():
    """
    Update ticker.txt and fno_tickers.txt from Excel files

    - ticker.txt: Updated from Stock_Information/Tickers_MCAP_Industry.xlsx
    - fno_tickers.txt: Updated from Stock_Information/FNO_Stocks.xlsx
    """

    script_dir = Path(__file__).parent
    stock_info_dir = script_dir / 'Stock_Information'

    # File paths
    tickers_excel = stock_info_dir / 'Tickers_MCAP_Industry.xlsx'
    fno_excel = stock_info_dir / 'FNO_Stocks.xlsx'
    tickers_txt = script_dir / 'tickers.txt'
    fno_txt = script_dir / 'fno_tickers.txt'

    # Verify Excel files exist
    if not tickers_excel.exists():
        logger.error(f"File not found: {tickers_excel}")
        return False

    if not fno_excel.exists():
        logger.error(f"File not found: {fno_excel}")
        return False

    try:
        # Read Tickers_MCAP_Industry.xlsx
        logger.info(f"Reading {tickers_excel}")
        tickers_df = pd.read_excel(tickers_excel)

        # Validate columns
        if 'Ticker' not in tickers_df.columns:
            logger.error(f"'Ticker' column not found in {tickers_excel}")
            return False

        # Extract tickers in original Excel order (preserve order, remove duplicates)
        all_tickers = tickers_df['Ticker'].dropna()
        # Convert to string, strip, and maintain order while removing duplicates
        seen = set()
        all_tickers = []
        for t in tickers_df['Ticker'].dropna():
            ticker = str(t).strip()
            if ticker and ticker not in seen:
                seen.add(ticker)
                all_tickers.append(ticker)

        logger.info(f"Found {len(all_tickers)} unique tickers")

        # Write to tickers.txt
        logger.info(f"Writing {len(all_tickers)} tickers to {tickers_txt}")
        with open(tickers_txt, 'w') as f:
            f.write("# NSE Stock Tickers\n")
            f.write("# Auto-generated from Stock_Information/Tickers_MCAP_Industry.xlsx\n")
            f.write("# Lines starting with # are comments\n")
            f.write("\n")
            for ticker in all_tickers:
                f.write(f"{ticker}\n")

        logger.info(f"✓ Updated {tickers_txt}")

        # Read FNO_Stocks.xlsx
        logger.info(f"Reading {fno_excel}")
        fno_df = pd.read_excel(fno_excel)

        # Validate columns
        if 'Ticker' not in fno_df.columns:
            logger.error(f"'Ticker' column not found in {fno_excel}")
            return False

        # Extract FNO tickers in original Excel order (preserve order, remove duplicates)
        seen_fno = set()
        fno_tickers = []
        for t in fno_df['Ticker'].dropna():
            ticker = str(t).strip()
            if ticker and ticker not in seen_fno:
                seen_fno.add(ticker)
                fno_tickers.append(ticker)

        logger.info(f"Found {len(fno_tickers)} FNO tickers")

        # Write to fno_tickers.txt
        logger.info(f"Writing {len(fno_tickers)} FNO tickers to {fno_txt}")
        with open(fno_txt, 'w') as f:
            f.write("# FNO (Futures & Options) tickers\n")
            f.write("# Auto-generated from Stock_Information/FNO_Stocks.xlsx\n")
            f.write("# These will be styled with grey background in Excel reports\n")
            f.write("\n")
            for ticker in fno_tickers:
                f.write(f"{ticker}\n")

        logger.info(f"✓ Updated {fno_txt}")

        # Summary
        print("\n=== UPDATE SUMMARY ===")
        print(f"Total tickers: {len(all_tickers)}")
        print(f"FNO tickers: {len(fno_tickers)}")
        print(f"Non-FNO tickers: {len(all_tickers) - len(fno_tickers)}")
        print(f"\nFiles updated:")
        print(f"  ✓ {tickers_txt}")
        print(f"  ✓ {fno_txt}")

        return True

    except Exception as e:
        logger.error(f"Error updating ticker files: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    print("=" * 60)
    print("Updating ticker files from Excel sources")
    print("=" * 60)
    print()

    success = update_ticker_files()

    if success:
        print("\n✓ Update completed successfully")
    else:
        print("\n✗ Update failed - check error messages above")
        exit(1)
