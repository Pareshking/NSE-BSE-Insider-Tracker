"""NSE Rights Issue extraction/validation.

Uses the official NSE RI page with a real browser because the page is JS-rendered.
The extractor preserves the native lifecycle sections and validates date-window
coverage without treating page count as completeness.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, timedelta
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

TARGET = date.fromisoformat(os.getenv("TARGET_DATE", "2026-08-31"))
BASE = "https://www.nseindia.com"
URL = f"{BASE}/companies-listing/corporate-filings-RI"
OUT = Path("artifacts/nse_validation/rights")


def browser() -> webdriver.Chrome:
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--lang=en-US")
    options.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139 Safari/537.36")
    return webdriver.Chrome(options=options)


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def extract_tables(driver: webdriver.Chrome) -> list[dict]:
    tables = []
    for table in driver.find_elements(By.TAG_NAME, "table"):
        rows = []
        for tr in table.find_elements(By.TAG_NAME, "tr"):
            cells = [clean(c.text) for c in tr.find_elements(By.CSS_SELECTOR, "th,td")]
            if any(cells):
                rows.append(cells)
        if rows:
            tables.append({"rows": rows, "row_count": max(0, len(rows) - 1), "columns": rows[0], "sample": rows[1:4]})
    return tables


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    driver = browser()
    report = {"source": "NSE", "dataset": "rights_issue", "url": URL, "target_date": str(TARGET), "windows": []}
    try:
        for name, start in [("1d", TARGET), ("5d", TARGET - timedelta(days=4)), ("30d", TARGET - timedelta(days=29)), ("1y", TARGET - timedelta(days=364))]:
            query = f"?tabIndex=equity&from_date={start:%d-%m-%Y}&to_date={TARGET:%d-%m-%Y}"
            driver.get(URL + query)
            WebDriverWait(driver, 25).until(lambda d: len(d.find_elements(By.TAG_NAME, "table")) > 0)
            tables = extract_tables(driver)
            meaningful = [t for t in tables if t["row_count"] > 0]
            report["windows"].append({
                "name": name,
                "start": str(start),
                "end": str(TARGET),
                "final_url": driver.current_url,
                "title": driver.title,
                "table_count": len(tables),
                "meaningful_table_count": len(meaningful),
                "tables": tables,
            })
    finally:
        driver.quit()
    (OUT / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
