#!/usr/bin/env python3
"""
marketlens_augment.py — pick up a MarketLens export from a drop folder,
expose its usable fundamentals to the pipeline, and cross-check price/volume.

WORKFLOW
--------
Drop your MarketLens export (the "stocks*.csv" you download from a screen with
`Current Market Price > 0` so it returns the whole universe) into:

    <repo>/marketlens_drop/

each time before you run the system. This module grabs the NEWEST file there —
you never have to rename it.

TWO JOBS
--------
1. AUGMENT  — parse the fields worth keeping (PE, Dividend Yield, Market Cap,
              Sector) keyed by NSE symbol, so main.py can merge them into the
              Report / Shortlist. Beta is dropped on purpose: the beta app
              exports a constant 1.00 placeholder. Returns/Volume are NOT merged
              (the codebase computes its own from bhavcopy) — they are used only
              for the validation below.

2. VALIDATE — an approximate cross-check of the price data feeding the system.
              It independently recomputes 1D / 1W / 1M return and latest volume
              from the local cache and compares them to MarketLens's own numbers.
              High correlation  => your cached prices agree with NSE's official
              figures. Big outliers => stale or mis-adjusted tickers to inspect.

CLI
---
    python3 marketlens_augment.py                 # newest file in marketlens_drop/
    python3 marketlens_augment.py path/to/file.csv
    python3 marketlens_augment.py --no-validate
    python3 marketlens_augment.py --cache-dir ./data_cache

For use inside the pipeline:
    from marketlens_augment import augmentation_frame
    aug = augmentation_frame()          # {symbol: {pe, div_yield, market_cap, ml_sector}}
"""

import argparse
import glob
import json
import os
import re
import sys

try:
    import pandas as pd
except ImportError:
    sys.exit("pandas is required — activate your .venv.")

HERE = os.path.dirname(os.path.abspath(__file__))
DROP_DIR = os.path.join(HERE, "marketlens_drop")
METADATA = os.path.join(HERE, "Stock_Information", "ticker_metadata.json")
CACHE_DIR = os.path.join(HERE, "data_cache")

# Ticker sits inside the Company field as "Reliance Industries Limited (RELIANCE)"
SYMBOL_RX = re.compile(r"\(([A-Z0-9&\-]+)\)\s*$")

# MarketLens column -> internal field. Only the ones worth merging.
AUG_COLS = {
    "PE Ratio":            "pe",
    "Dividend Yield (%)":  "div_yield",
    "Market Cap":          "market_cap",
    "Sector":              "ml_sector",
    "Sub Sector":          "ml_subsector",
}
# Used ONLY for the price/volume cross-check, never merged.
VALID_COLS = {
    "1D Return (%)": "ret_1d",
    "1W Return (%)": "ret_1w",
    "1M Return (%)": "ret_1m",
    "Volume":        "volume",
}


def parse_symbol(name):
    m = SYMBOL_RX.search(str(name))
    return m.group(1).upper() if m else None


def find_latest_export(drop_dir=DROP_DIR):
    """Newest .csv/.xlsx in the drop folder, or None."""
    if not os.path.isdir(drop_dir):
        return None
    files = [f for f in glob.glob(os.path.join(drop_dir, "*"))
             if f.lower().endswith((".csv", ".xlsx", ".xls"))]
    return max(files, key=os.path.getmtime) if files else None


def _read(path):
    if path.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(path)
    return pd.read_csv(path)


def load_export(path):
    """DataFrame indexed by NSE symbol with the usable + validation columns."""
    df = _read(path)
    if "Company" not in df.columns:
        raise ValueError("Expected a 'Company' column containing 'Name (SYMBOL)'.")
    df["symbol"] = df["Company"].map(parse_symbol)
    df = df[df["symbol"].notna()].copy()

    keep = {src: dst for src, dst in {**AUG_COLS, **VALID_COLS}.items() if src in df.columns}
    out = df[["symbol"] + list(keep)].rename(columns=keep)
    out = out.drop_duplicates("symbol").set_index("symbol")
    for c in out.columns:
        if c not in ("ml_sector", "ml_subsector"):
            out[c] = pd.to_numeric(out[c], errors="coerce")
    return out


def load_universe():
    if os.path.exists(METADATA):
        try:
            with open(METADATA) as f:
                return {k.upper() for k in json.load(f)}
        except Exception:
            pass
    return set()


# ────────────────────────────────────────────────────────────────────
#  AUGMENT — payload the pipeline merges
# ────────────────────────────────────────────────────────────────────
def augmentation_frame(path=None):
    """
    {symbol: {pe, div_yield, market_cap, ml_sector}} for main.py to merge.
    Loss-makers keep their negative/zero PE; the caller decides how to treat it.
    """
    path = path or find_latest_export()
    if not path:
        return {}
    df = load_export(path)
    cols = [c for c in ("pe", "div_yield", "market_cap", "ml_sector") if c in df.columns]
    return df[cols].to_dict("index")


# ────────────────────────────────────────────────────────────────────
#  VALIDATE — recompute returns/volume from cache, compare to MarketLens
# ────────────────────────────────────────────────────────────────────
def _load_cache_prices(symbol, cache_dir):
    """(dates, closes, volumes) from the local cache for one symbol, or None."""
    d = None
    try:                                     # prefer the project's own loader
        from data_cache import DataCache
        d = DataCache(cache_dir).load_ticker_data(symbol)
    except Exception:
        p = os.path.join(cache_dir, f"{symbol}.pkl")
        if os.path.exists(p):
            try:
                d = pd.read_pickle(p)
            except Exception:
                d = None
    if d is None or getattr(d, "empty", True) or "close" not in d or "date" not in d:
        return None
    d = d.sort_values("date")
    close = pd.to_numeric(d["close"], errors="coerce")
    vol = pd.to_numeric(d["traded_quantity"], errors="coerce") if "traded_quantity" in d else None
    return d["date"].tolist(), close.tolist(), (vol.tolist() if vol is not None else None)


def _pct(a, b):
    if pd.notna(a) and pd.notna(b) and b:
        return (a / b - 1.0) * 100.0
    return None


def validate_returns_volume(ml_df, cache_dir=CACHE_DIR, universe=None):
    """Compare cache-recomputed 1D/1W/1M/volume to MarketLens. Returns a frame."""
    syms = list(ml_df.index) if universe is None else [s for s in ml_df.index if s in universe]
    rows = []
    for s in syms:
        got = _load_cache_prices(s, cache_dir)
        if not got:
            continue
        dates, close, vol = got
        if len(close) < 22:
            continue
        comp = {
            "ret_1d": _pct(close[-1], close[-2]),
            "ret_1w": _pct(close[-1], close[-6]),    # 5 trading sessions
            "ret_1m": _pct(close[-1], close[-22]),   # ~21 trading sessions
            "volume": vol[-1] if vol else None,
        }
        r = {"symbol": s, "cache_date": str(dates[-1])[:10]}
        for k in ("ret_1d", "ret_1w", "ret_1m", "volume"):
            if k in ml_df.columns:
                r[k + "_ml"] = ml_df.at[s, k]
                r[k + "_sys"] = comp[k]
        rows.append(r)
    return pd.DataFrame(rows)


def _report_metric(cmp, ml, sys_, label, tol):
    d = cmp[[ml, sys_]].dropna()
    if len(d) < 5:
        print(f"  {label:<10} too few rows to compare")
        return
    corr = d[ml].corr(d[sys_])
    diff = (d[sys_] - d[ml]).abs()
    within = (diff <= tol).mean() * 100
    print(f"  {label:<10} n={len(d):<5} corr={corr:+.3f}  median|Δ|={diff.median():.2f}pp  "
          f"within {tol}pp: {within:.0f}%")
    worst = d.assign(delta=d[sys_] - d[ml]).reindex(diff.sort_values(ascending=False).index).head(5)
    for sym, row in worst.iterrows():
        print(f"        {str(sym):<12} ml={row[ml]:>9.2f}  sys={row[sys_]:>9.2f}  Δ={row['delta']:+.2f}")


def main():
    ap = argparse.ArgumentParser(description="MarketLens augment + price/volume validation.")
    ap.add_argument("file", nargs="?", help="Explicit export file (default: newest in drop dir)")
    ap.add_argument("--drop-dir", default=DROP_DIR)
    ap.add_argument("--cache-dir", default=CACHE_DIR)
    ap.add_argument("--no-validate", action="store_true")
    args = ap.parse_args()

    os.makedirs(args.drop_dir, exist_ok=True)   # create the drop folder if absent

    path = args.file or find_latest_export(args.drop_dir)
    if not path:
        sys.exit(f"No export found. Drop a MarketLens CSV into:\n    {args.drop_dir}")
    print("=" * 68)
    print(f"Export: {os.path.basename(path)}  ({os.path.getsize(path)//1024} KB)")
    print("=" * 68)

    df = load_export(path)
    print(f"Parsed {len(df)} stocks (symbol extracted from 'Company').")

    uni = load_universe()
    if uni:
        matched = [s for s in df.index if s in uni]
        missing = sorted(set(uni) - set(df.index))
        print(f"Universe match: {len(matched)}/{len(uni)} tracked tickers "
              f"({len(matched)/len(uni)*100:.0f}%)")
        if missing:
            print(f"  not in export ({len(missing)}): {', '.join(missing[:12])}"
                  + (" ..." if len(missing) > 12 else ""))

    print("\n[AUGMENT] fields available to merge:")
    for c in ("pe", "div_yield", "market_cap", "ml_sector"):
        if c in df.columns:
            if c == "ml_sector":
                nn = (df[c].astype(str).str.strip() != "").mean() * 100
                print(f"  {c:<12} {nn:.0f}% populated")
            else:
                nn = df[c].notna().mean() * 100
                extra = f"   ({int((df['pe'] <= 0).sum())} loss-makers, PE<=0)" if c == "pe" else ""
                print(f"  {c:<12} {nn:.0f}% populated{extra}")

    if not args.no_validate:
        print("\n[VALIDATE] system cache vs MarketLens (approx cross-check):")
        cmp = validate_returns_volume(df, args.cache_dir, uni or None)
        if cmp.empty:
            print("  No cache overlap — check --cache-dir, and run this on the machine\n"
                  "  that holds data_cache/ (the sandbox can't read your .pkl cache).")
        else:
            print(f"  compared {len(cmp)} tickers | cache dates {cmp['cache_date'].min()}"
                  f"..{cmp['cache_date'].max()}")
            print("  (1D needs the cache's last day == MarketLens export day to line up;")
            print("   1W/1M correlation is the robust signal. Big Δ = inspect that ticker.)")
            if "ret_1d_ml" in cmp: _report_metric(cmp, "ret_1d_ml", "ret_1d_sys", "1D ret", 1.0)
            if "ret_1w_ml" in cmp: _report_metric(cmp, "ret_1w_ml", "ret_1w_sys", "1W ret", 3.0)
            if "ret_1m_ml" in cmp: _report_metric(cmp, "ret_1m_ml", "ret_1m_sys", "1M ret", 6.0)
            if "volume_ml" in cmp:
                v = cmp[["volume_ml", "volume_sys"]].dropna()
                v = v[(v["volume_ml"] > 0) & (v["volume_sys"] > 0)]
                if len(v) >= 5:
                    ratio = (v["volume_sys"] / v["volume_ml"])
                    print(f"  {'Volume':<10} n={len(v):<5} median sys/ml ratio={ratio.median():.2f}  "
                          f"(≈1.0 = same day/basis)")
    print("\nDone.")


if __name__ == "__main__":
    main()
