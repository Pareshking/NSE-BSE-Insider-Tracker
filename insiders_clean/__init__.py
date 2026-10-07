"""Cleaning layer: turns the canonical NSE/BSE datasets in R2 into clean
tables the site reads directly (clean/{date}/...).

Pure functions live in the submodules and take DataFrames in and out, so
every rule is testable without R2. scripts/clean_writer.py is the only part
that touches the bucket.
"""
