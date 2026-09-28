#!/usr/bin/env python3
"""
test_marketlens_import.py  —  data-augmentation IMPORT PROBE
============================================================

Purpose
-------
Check whether a data file you EXPORTED YOURSELF from NSE Market Lens (or any
other source: a broker export, a fundamentals CSV, etc.) can augment this
screener — i.e. does it contain the fields we're missing (PE, ROE, growth,
promoter %, ...) and does it join cleanly to your ticker universe.

This is deliberately an IMPORT probe, not a crawler. It reads a file that is
already on your disk. It never contacts Market Lens or nseindia.com — NSE's
Terms of Use prohibit automated collection from their site, so the compliant
flow is: you open Market Lens, use its Export/Download button on a screen,
then point this script at the file it saves.

Usage
-----
    python3 test_marketlens_import.py  <path-to-export.csv|.xlsx>

    # examples
    python3 test_marketlens_import.py ~/Downloads/marketlens_export.csv
    python3 test_marketlens_import.py "Stock_Information/ml_quality_screen.xlsx"

What it reports
---------------
1. File shape + every column it found.
2. Which column looks like the ticker/symbol (auto-detected by best overlap
   with your own universe).
3. Which of the "useful augmentation fields" are present, and how populated.
4. Join quality: how many rows match tickers you actually track.
5. A small merged preview so you can eyeball it.

If the join rate is high and the fields are populated, tell me and I'll build
the full importer that merges these columns into the Report/Shortlist.
"""

import argparse
import json
import os
import re
import sys

try:
    import pandas as pd
except ImportError:
    sys.exit("pandas is required — activate your .venv (it's already a project dep).")

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_METADATA = os.path.join(HERE, "Stock_Information", "ticker_metadata.json")
DEFAULT_TICKERS = os.path.join(HERE, "tickers.txt")

# Fields worth pulling in, with loose regex patterns to survive whatever
# Market Lens names its columns. Extend freely.
TARGET_FIELDS = {
    # --- valuation ---
    "market_cap":        r"market\s*cap",
    "pe":                r"price\s*to\s*earning|\bp\s*/?\s*e\b|pe ratio",
    "eps":               r"earning\s*per\s*share|\beps\b",
    "peg":               r"\bpeg\b",
    # --- raw financials (let the codebase compute ROE/ROCE/quality itself) ---
    "pbt":               r"profit\s*before\s*tax|\bpbt\b",
    "deferred_tax":      r"deferred\s*tax",
    "total_equity":      r"total\s*equity",
    "total_assets":      r"total\s*assets",
    "total_liabilities": r"total\s*liabilit",
    "roe":               r"\broe\b|return on equity",
    "roce":              r"\broce\b|return on capital",
    # --- leverage / solvency ---
    "debt_equity":       r"debt\s*to\s*equity|debt.*equity|\bd\s*/\s*e\b",
    "lt_borrowings":     r"long\s*term\s*borrow",
    "st_borrowings":     r"short\s*term\s*borrow",
    "interest_coverage": r"interest\s*coverage",
    # --- cash-flow quality (the negative-OCF flag, now automatable) ---
    "operating_cf":      r"operating\s*cash",
    "investing_cf":      r"investing\s*cash",
    "net_cf":            r"net\s*cash",
    # --- ownership ---
    "promoter":          r"promoter\s*holding|promoter",
    "public_holding":    r"public\s*holding",
    # --- price / technical context ---
    "cmp":               r"current\s*market\s*price|\bcmp\b",
    "vwap":              r"\bvwap\b",
    "all_time_high":     r"all\s*time\s*high",
    "price_band_lower":  r"price\s*band",
    "volatility":        r"daily\s*volatilit|volatilit",
    "ret_1m":            r"return.*1\s*month|1\s*month.*return|return over.*month",
    "dma_20":            r"\b20\s*d\.?\s*m\.?\s*a\b|\b20\s*dma\b",
    "dma_50":            r"\b50\s*d\.?\s*m\.?\s*a\b|\b50\s*dma\b",
    "dma_200":           r"\b200\s*d\.?\s*m\.?\s*a\b|\b200\s*dma\b",
    # --- optional extras (harmless if absent) ---
    "div_yield":         r"div(idend)?\s*yield",
    "sector":            r"\b(sector|industry)\b",
}

# Candidate names for the symbol/ticker column
TICKER_HINTS = ["symbol", "ticker", "nse", "scrip", "code", "stock", "security", "name"]


def norm_ticker(x) -> str:
    """Normalise to the codebase's convention: UPPER, no exchange suffix/series."""
    if x is None:
        return ""
    s = str(x).strip().upper()
    s = re.sub(r"\.(NS|BO|NSE|BSE)$", "", s)     # ADANIENT.NS -> ADANIENT
    s = re.sub(r"[-\s](EQ|BE|BZ|SM)$", "", s)    # FOO-EQ -> FOO
    s = s.replace(" ", "")
    return s


def load_universe(metadata_path, tickers_path):
    universe = set()
    if os.path.exists(metadata_path):
        try:
            with open(metadata_path) as f:
                universe |= {norm_ticker(k) for k in json.load(f).keys()}
        except Exception as e:
            print(f"  ! could not read metadata: {e}")
    if os.path.exists(tickers_path):
        try:
            with open(tickers_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        universe.add(norm_ticker(line))
        except Exception as e:
            print(f"  ! could not read tickers.txt: {e}")
    return universe


def load_file(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xls", ".xlsm"):
        return pd.read_excel(path)          # needs openpyxl (already a dep)
    if ext in (".csv", ".txt"):
        return pd.read_csv(path)
    if ext == ".tsv":
        return pd.read_csv(path, sep="\t")
    # last resort: try csv
    return pd.read_csv(path)


def detect_ticker_column(df, universe):
    """Pick the column whose values best overlap the known universe; fall back
    to name hints if the universe is empty."""
    best_col, best_hits = None, -1
    for col in df.columns:
        vals = {norm_ticker(v) for v in df[col].dropna().astype(str).head(500)}
        hits = len(vals & universe) if universe else 0
        if hits > best_hits:
            best_col, best_hits = col, hits
    if best_hits > 0:
        return best_col, best_hits
    # universe empty or no overlap -> guess by column name
    for col in df.columns:
        if any(h in str(col).lower() for h in TICKER_HINTS):
            return col, 0
    return df.columns[0], 0


def detect_fields(df):
    found = {}
    for field, pat in TARGET_FIELDS.items():
        rx = re.compile(pat, re.I)
        for col in df.columns:
            if rx.search(str(col)):
                found[field] = col
                break
    return found


def main():
    ap = argparse.ArgumentParser(description="Probe a Market Lens / fundamentals export for augmentation.")
    ap.add_argument("file", nargs="?", help="Path to the exported .csv/.xlsx file")
    ap.add_argument("--metadata", default=DEFAULT_METADATA)
    ap.add_argument("--tickers", default=DEFAULT_TICKERS)
    args = ap.parse_args()

    if not args.file:
        print(__doc__)
        print("\n>> Give me a file:  python3 test_marketlens_import.py <export.csv>")
        return
    if not os.path.exists(args.file):
        sys.exit(f"File not found: {args.file}")

    print("=" * 70)
    print(f"IMPORT PROBE  —  {os.path.basename(args.file)}")
    print("=" * 70)

    try:
        df = load_file(args.file)
    except Exception as e:
        sys.exit(f"Could not read file: {e}")

    print(f"\n[1] Shape: {df.shape[0]} rows x {df.shape[1]} columns")
    print("    Columns found:")
    for c in df.columns:
        print(f"      - {c}")

    universe = load_universe(args.metadata, args.tickers)
    print(f"\n[2] Your universe: {len(universe)} tickers "
          f"({'metadata+tickers' if universe else 'NOT FOUND — join test skipped'})")

    tcol, hits = detect_ticker_column(df, universe)
    print(f"    Ticker column detected: '{tcol}'"
          + (f"  ({hits} values match your universe)" if universe else "  (by name hint)"))

    fields = detect_fields(df)
    print(f"\n[3] Useful augmentation fields detected: {len(fields)}/{len(TARGET_FIELDS)}")
    for field in TARGET_FIELDS:
        if field in fields:
            col = fields[field]
            nonnull = df[col].notna().mean() * 100
            print(f"      ✓ {field:<14} <- '{col}'  ({nonnull:.0f}% populated)")
        else:
            print(f"      · {field:<14} (not found)")

    # Join quality
    if universe:
        keys = df[tcol].map(norm_ticker)
        matched = keys[keys.isin(universe)]
        n_match = matched.nunique()
        print(f"\n[4] Join quality:")
        print(f"      {n_match} of your {len(universe)} tracked tickers are covered "
              f"({n_match/len(universe)*100:.0f}%)")
        unmatched = sorted(set(keys) - universe - {''})
        print(f"      {len(unmatched)} export rows didn't match your universe"
              + (f" (e.g. {', '.join(unmatched[:8])} ...)" if unmatched else ""))

    # Preview
    if fields:
        cols = [tcol] + list(dict.fromkeys(fields.values()))
        print(f"\n[5] Merged preview (first 8 rows of usable columns):")
        with pd.option_context("display.max_columns", None, "display.width", 200):
            print(df[cols].head(8).to_string(index=False))

    # Verdict
    print("\n" + "=" * 70)
    ok_fields = len(fields) >= 3
    ok_join = (not universe) or (n_match / max(len(universe), 1) >= 0.5)
    if ok_fields and ok_join:
        print("VERDICT: Looks usable ✓  — good field coverage and join rate.")
        print("Send me this output (or the file) and I'll build the full importer\n"
              "that merges these columns into the Report + a PEG/Quality overlay.")
    else:
        print("VERDICT: Partial.")
        if not ok_fields:
            print("  - Few target fields found — try exporting a screen that includes\n"
                  "    fundamentals (PE, ROE, growth), or share the column names and I'll\n"
                  "    widen the detection patterns.")
        if universe and not ok_join:
            print("  - Low join rate — the ticker column may use a different symbology.\n"
                  "    Share a few raw values and I'll fix the normaliser.")
    print("=" * 70)


if __name__ == "__main__":
    main()
