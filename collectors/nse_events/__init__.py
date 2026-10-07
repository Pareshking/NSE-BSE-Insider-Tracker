"""NSE corporate events collector: SAST Reg 29, corporate actions, board
meetings, shareholding pattern (with promoter pledge from each filing's XBRL).

Parsers (parsers.py) are pure; client.py talks to NSE; run_daily.py is the
nightly job that fetches a rolling 10-day window, merges it into the archive
and rebuilds clean/current/{event_type}.parquet. See docs/DATA_DICTIONARY.md.
"""
