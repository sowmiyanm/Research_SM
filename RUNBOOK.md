# Runbook

Two commands. That's the whole workflow.

```bash
cd ~/Desktop/Research_SM

python3 main.py                    # daily   — a few minutes
python3 main.py --mode monthly     # monthly — 40-70 min, full rebuild
```

`daily` is now the default, so plain `python3 main.py` is the daily run.

---

## What each mode does

| | `--mode daily` (default) | `--mode monthly` |
|---|---|---|
| Fetches | only trading days since the last run | the full 2-year history, from scratch |
| Cache | added to | backed up, wiped, rebuilt |
| Time | a few minutes | 40–70 min, ~0.7 GB |
| If it fails | you keep everything, just slightly stale | **automatically rolls back to the backup** |

The old `auto` / `initial` / `incremental` modes still work — `daily` and `monthly` are just friendlier names for the two you'll actually use.

---

## The monthly rebuild is now safe to interrupt

Deleting the cache used to be risky: a rebuild that died partway left you with a partial universe and nothing to fall back on. That already happened once — a run stopped at ticker 823 and left 229 tickers nine trading days stale, plus one corrupt cache file, with nothing reporting it.

`--mode monthly` now does this:

1. **Backs up** `data_cache/` to `data_cache_backup_<timestamp>/`
2. Wipes the cache and rebuilds from scratch
3. **Health-checks** the result
4. **Rolls back automatically** if coverage lands below 80% — the failed attempt is kept as `data_cache_failed_<timestamp>/` so you can inspect it
5. Prunes old backups, keeping the last 2

Rollback also fires on Ctrl-C and on an unhandled crash. Tested: backup → wipe → simulated partial rebuild (25% coverage) → automatic restore, verified byte-for-byte against the original.

Tune the threshold with `--min-coverage 90`, or skip the backup with `--no-backup` (not recommended).

---

## Every run now ends with a health check

```
================================================================================
HEALTH CHECK
================================================================================
Coverage   : 1058/1061 tickers cached (99.7%)
Newest date: 2026-08-27
Stale (3d+): 0
Duplicates : 0 tickers
Corrupt xlsx: 0
All clear — cache is complete, current and clean.
```

When something is wrong it says so at WARNING level:

```
WARNING MISSING from cache (3): BFINVEST, GRAVITA, TIMKEN
WARNING STALE — not on 2026-08-27 (229). Oldest: TIMKEN 2026-08-14, ...
WARNING   Re-run to catch these up. Check the 'As Of' column before trusting
WARNING   signals for any of them.
WARNING DUPLICATE trading days in 2 tickers: ['ABC', 'XYZ'] — rolling windows
WARNING   are wrong for these. Rebuild them.
WARNING CORRUPT Excel backups (1): ['GRAVITA_historical.xlsx']
```

**This is the line that makes the workflow stress-free.** Previously a killed process printed nothing and a partial cache looked identical to a complete one. Now the run tells you.

---

## Fetch failures now say why

Before, every per-symbol failure went to `logger.debug` — off by default. Your `0/1061` run gave no diagnostic at all because 1,061 exceptions were caught and silently discarded.

Now:

```
WARNING Quote data fetched: 0/1061 tickers succeeded | failures: 1061x HTTP 401
        <-- NOTHING succeeded; the dependent columns will be blank
```

Logged at WARNING when nothing succeeds or fewer than half do. That one line names the cause.

---

## Other fixes in this change set

**Atomic Excel cache writes.** The pickle was already written via temp-file + `os.replace`; the Excel wasn't, which is what produced the corrupt `GRAVITA_historical.xlsx`. Now both are atomic. Verified: a simulated Ctrl-C mid-write leaves the existing file byte-identical and no stray temp files. (Note for the curious — the temp file has to keep a `.xlsx` suffix, because pandas picks its Excel engine from the extension.)

**Duplicate-date guard in `process_ticker_data`.** `merge_new_data` was the only line of defence. A duplicated day halves the span of every rolling window — measured on RELIANCE: `52w_high` 1592 → 1464, `RSI` 41.5 → 31.6, enough to flip an Oversold call. Now caught and logged wherever it comes from. Verified: 1,014 rows in → 507 out, every indicator matching a clean run exactly.

**`calculate_weekly_wma` is now idempotent.** Re-running the calculator over its own output used to die with `KeyError: 'cross_above'`. Now it drops stale columns first. Verified: no `_x`/`_y` suffixes, identical stage.

**Removed the corrupt `GRAVITA_historical.xlsx`.** The pickle held the real data, so nothing was lost — it rebuilds on the next save.

---

## Suggested rhythm

- **Weekday mornings:** `python3 main.py`, then check the HEALTH CHECK block at the bottom. If it says "All clear", open the workbook and go straight to the Shortlist.
- **First weekend of the month:** `python3 main.py --mode monthly`. Leave it running; it protects itself.
- **Never** run two instances at once — that's the one remaining path to duplicate data.

## Reading the output

Open **Shortlist** (it's the first sheet). Sort by `→Stop %` ascending or scan the `Why` column for `AtPivot`. Check `As Of` is current. Buy zone is `→Pivot %` between −2% and +5%; sell on `Cross↓ WMA` or your stop being hit.

Ignore `PE`, `Sector PE`, `Promoter %` and `Profit Gr. YoY` — the NSE fundamental APIs return nothing (that's the `0/1061` above, still unfixed).
