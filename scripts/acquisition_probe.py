from __future__ import annotations

import json
import os
import time
from datetime import date, datetime
from io import StringIO
from typing import Any

import pandas as pd
import requests

TARGET_DATE = os.getenv("TARGET_DATE", "2026-08-31")
D = date.fromisoformat(TARGET_DATE)
DDMMYYYY = D.strftime("%d-%m-%Y")
YYYYMMDD = D.strftime("%Y%m%d")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0 Safari/537.36"


def make_result(source: str, dataset: str, method: str, **kw: Any) -> dict[str, Any]:
    return {"source": source, "dataset": dataset, "method": method, **kw}


def compact_json(obj: Any) -> dict[str, Any]:
    if isinstance(obj, list):
        return {"type": "list", "count": len(obj), "sample_keys": sorted(obj[0].keys()) if obj and isinstance(obj[0], dict) else []}
    if isinstance(obj, dict):
        return {"type": "dict", "keys": sorted(obj.keys())}
    return {"type": type(obj).__name__}


def nse_direct() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json,text/plain,*/*", "Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-insider-trading"})
    try:
        home = s.get("https://www.nseindia.com/", timeout=20)
        out.append(make_result("NSE", "homepage", "direct_api", status_code=home.status_code, bytes=len(home.content)))
    except Exception as exc:
        out.append(make_result("NSE", "homepage", "direct_api", status="error", error=f"{type(exc).__name__}: {exc}"))
        return out
    endpoints = {
        "insider_trading": f"https://www.nseindia.com/api/corporates-pit?index=equities&from_date={DDMMYYYY}&to_date={DDMMYYYY}&csv=true",
        "bulk_deals": f"https://www.nseindia.com/api/historical/bulk-deals?from={DDMMYYYY}&to={DDMMYYYY}",
        "block_deals": f"https://www.nseindia.com/api/historical/block-deals?from={DDMMYYYY}&to={DDMMYYYY}",
    }
    for name, url in endpoints.items():
        t = time.perf_counter()
        try:
            r = s.get(url, timeout=30)
            rec = make_result("NSE", name, "direct_api", status_code=r.status_code, elapsed_s=round(time.perf_counter()-t,3), bytes=len(r.content), content_type=r.headers.get("content-type",""), url=url)
            if r.ok:
                try: rec["payload"] = compact_json(r.json())
                except Exception: rec["body_prefix"] = r.text[:500]
            else: rec["error_prefix"] = r.text[:300]
            out.append(rec)
        except Exception as exc:
            out.append(make_result("NSE", name, "direct_api", status="error", elapsed_s=round(time.perf_counter()-t,3), error=f"{type(exc).__name__}: {exc}"))
    return out


def nse_package() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        from nse import NSE
        with NSE(download_folder="artifacts/nse", server=True, timeout=30) as nse:
            for kind in ("bulk_deals", "block_deals"):
                t = time.perf_counter()
                try:
                    rows = nse.bulkdeals(kind, datetime.combine(D, datetime.min.time()), datetime.combine(D, datetime.min.time()))
                    out.append(make_result("NSE", kind, "nse_package_server", status="success", count=len(rows), elapsed_s=round(time.perf_counter()-t,3), sample_keys=sorted(rows[0].keys()) if rows else []))
                except Exception as exc:
                    out.append(make_result("NSE", kind, "nse_package_server", status="error", error=f"{type(exc).__name__}: {exc}"))
    except Exception as exc:
        out.append(make_result("NSE", "library_import", "nse_package_server", status="error", error=f"{type(exc).__name__}: {exc}"))
    return out


def nse_selenium() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        options = Options()
        options.add_argument("--headless=new"); options.add_argument("--no-sandbox"); options.add_argument("--disable-dev-shm-usage"); options.add_argument("--disable-gpu"); options.add_argument(f"--user-agent={UA}")
        driver = webdriver.Chrome(options=options)
        try:
            page = "https://www.nseindia.com/companies-listing/corporate-filings-insider-trading"
            t = time.perf_counter(); driver.get(page); time.sleep(4)
            script = """
            const done = arguments[0], url = arguments[1];
            fetch(url, {credentials:'include', headers:{'Accept':'application/json,text/plain,*/*'}})
              .then(async r => done({status:r.status, type:r.headers.get('content-type'), text:(await r.text()).slice(0,5000)}))
              .catch(e => done({error:String(e)}));
            """
            url = f"https://www.nseindia.com/api/corporates-pit?index=equities&from_date={DDMMYYYY}&to_date={DDMMYYYY}"
            fetched = driver.execute_async_script(script, url)
            rec = make_result("NSE", "insider_trading", "selenium_browser_fetch", status="success" if fetched.get("status") == 200 else "failed", http_status=fetched.get("status"), content_type=fetched.get("type"), body_prefix=fetched.get("text","")[:500], elapsed_s=round(time.perf_counter()-t,3), page_title=driver.title, current_url=driver.current_url)
            if fetched.get("status") == 200:
                try:
                    payload = json.loads(fetched.get("text", "")); rec["payload"] = compact_json(payload)
                    data = payload.get("data", payload.get("Data", [])) if isinstance(payload, dict) else []
                    rec["record_count"] = len(data) if isinstance(data, list) else None
                    rec["sample"] = data[:2] if isinstance(data, list) else None
                except Exception as exc: rec["parse_error"] = f"{type(exc).__name__}: {exc}"
            out.append(rec)
        finally:
            driver.quit()
    except Exception as exc:
        out.append(make_result("NSE", "insider_trading", "selenium_browser_fetch", status="error", error=f"{type(exc).__name__}: {exc}"))
    return out


def nse_further_issue_pages() -> list[dict[str, Any]]:
    """Probe the same official NSE pages shown in the UI for Preferential and Right Issues.
    Browser mode is used because NSE often blocks non-browser requests from cloud runners.
    We record rendered row counts and API resource URLs so the next collector can use the
    structured endpoint instead of scraping rendered text.
    """
    out: list[dict[str, Any]] = []
    pages = {
        "preferential_issue": "https://www.nseindia.com/companies-listing/corporate-filings-PREF",
        "right_issue": "https://www.nseindia.com/companies-listing/corporate-filings-RI",
    }
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        options = Options()
        for arg in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", f"--user-agent={UA}"):
            options.add_argument(arg)
        driver = webdriver.Chrome(options=options)
        try:
            for dataset, page in pages.items():
                t = time.perf_counter()
                try:
                    driver.get(page); time.sleep(5)
                    rows = driver.execute_script("return Array.from(document.querySelectorAll('table tbody tr')).map(r => Array.from(r.cells).map(c => c.innerText.trim())).filter(r => r.length)")
                    resources = driver.execute_script("return performance.getEntriesByType('resource').map(x => x.name).filter(x => x.includes('/api/')).slice(-80)")
                    body = driver.find_element("tag name", "body").text
                    out.append(make_result("NSE", dataset, "selenium_rendered_page", status="success", http_status=200, row_count=len(rows), sample_rows=rows[:3], api_resources=resources, contains_download_csv="Download (.csv)" in body, contains_xbrl="XBRL" in body, elapsed_s=round(time.perf_counter()-t,3), current_url=driver.current_url))
                except Exception as exc:
                    out.append(make_result("NSE", dataset, "selenium_rendered_page", status="error", error=f"{type(exc).__name__}: {exc}", elapsed_s=round(time.perf_counter()-t,3)))
        finally:
            driver.quit()
    except Exception as exc:
        out.append(make_result("NSE", "further_issue_import", "selenium_rendered_page", status="error", error=f"{type(exc).__name__}: {exc}"))
    return out


def bse_headers() -> dict[str, str]:
    return {"User-Agent": UA, "Referer": "https://www.bseindia.com/", "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9"}


def bse_bulk_block() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name, url in (("bulk_deals", "https://www.bseindia.com/markets/equity/EQReports/bulk_deals.aspx"), ("block_deals", "https://www.bseindia.com/markets/equity/EQReports/block_deals.aspx")):
        t = time.perf_counter()
        try:
            s = requests.Session(); s.headers.update(bse_headers()); s.get("https://www.bseindia.com/", timeout=20); r = s.get(url, timeout=30)
            tables = pd.read_html(StringIO(r.text)) if r.ok else []
            out.append(make_result("BSE", name, "official_html", status="success" if r.ok and tables else "empty_or_error", status_code=r.status_code, table_count=len(tables), row_counts=[len(x) for x in tables], bytes=len(r.content), elapsed_s=round(time.perf_counter()-t,3)))
        except Exception as exc: out.append(make_result("BSE", name, "official_html", status="error", error=f"{type(exc).__name__}: {exc}"))
    return out


def bse_announcements() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    url = "https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w"
    for term in ("Preferential", "Rights Issue", "Allotment"):
        params = {"pageno":"1", "strCat":"-1", "strPrevDate":YYYYMMDD, "strScrip":"", "strSearch":term, "strToDate":YYYYMMDD, "strType":"C"}
        try:
            s = requests.Session(); s.headers.update(bse_headers()); s.get("https://www.bseindia.com/", timeout=20); r = s.get(url, params=params, timeout=30)
            rec = make_result("BSE", f"corporate_announcements_{term.lower().replace(' ','_')}", "official_api", status="success" if r.ok else "failed", status_code=r.status_code, bytes=len(r.content), content_type=r.headers.get("content-type",""), url=r.url)
            if r.ok:
                try:
                    payload = r.json(); table = payload.get("Table", []) if isinstance(payload, dict) else []
                    rec.update(total_records=len(table), sample=table[:5])
                except Exception as exc: rec["parse_error"] = f"{type(exc).__name__}: {exc}"
            else: rec["error_prefix"] = r.text[:300]
            out.append(rec)
        except Exception as exc: out.append(make_result("BSE", f"corporate_announcements_{term.lower().replace(' ','_')}", "official_api", status="error", error=f"{type(exc).__name__}: {exc}"))
    return out


def bse_further_issue_pages() -> list[dict[str, Any]]:
    """Probe BSE's official further-issue/public-issue and listing-notice surfaces.
    BSE does not expose a single equivalent XBRL table as clearly as NSE, so we test
    rights issue public-issue data plus corporate/listing notices used for allotments.
    """
    out: list[dict[str, Any]] = []
    pages = {
        "right_issue_public_issues": "https://www.bseindia.com/markets/PublicIssues/IPOIssues_new.aspx?id=2&Type=P",
        "issue_summary": "https://www.bseindia.com/markets/PublicIssues/Issuesummary.aspx",
        "corporate_announcements": "https://m.bseindia.com/corporates.aspx",
    }
    for dataset, url in pages.items():
        t = time.perf_counter()
        try:
            s = requests.Session(); s.headers.update(bse_headers()); s.get("https://www.bseindia.com/", timeout=20); r = s.get(url, timeout=30)
            tables = pd.read_html(StringIO(r.text)) if r.ok else []
            text = r.text.lower()
            out.append(make_result("BSE", dataset, "official_html", status="success" if r.ok else "failed", status_code=r.status_code, table_count=len(tables), row_counts=[len(x) for x in tables[:10]], contains_right_issue="right" in text, contains_preferential="preferential" in text, contains_allotment="allot" in text, bytes=len(r.content), elapsed_s=round(time.perf_counter()-t,3)))
        except Exception as exc:
            out.append(make_result("BSE", dataset, "official_html", status="error", error=f"{type(exc).__name__}: {exc}"))
    return out


def bse_api_wrapper() -> list[dict[str, Any]]:
    try:
        from bse import BSE
        t = time.perf_counter()
        with BSE(download_folder="artifacts/bse") as bse: code = bse.getScripCode("TCS")
        return [make_result("BSE", "api_reachability", "BseIndiaApi", status="success", tcs_code=code, elapsed_s=round(time.perf_counter()-t,3))]
    except Exception as exc: return [make_result("BSE", "api_reachability", "BseIndiaApi", status="error", error=f"{type(exc).__name__}: {exc}")]


def main() -> int:
    os.makedirs("artifacts/nse", exist_ok=True); os.makedirs("artifacts/bse", exist_ok=True)
    report = {"target_date": TARGET_DATE, "phase": "1+2 acquisition probe", "generated_at_utc": datetime.utcnow().isoformat(), "results": []}
    report["results"] += nse_direct(); report["results"] += nse_package(); report["results"] += nse_selenium(); report["results"] += nse_further_issue_pages(); report["results"] += bse_bulk_block(); report["results"] += bse_announcements(); report["results"] += bse_further_issue_pages(); report["results"] += bse_api_wrapper()
    with open("artifacts/acquisition_probe.json", "w", encoding="utf-8") as f: json.dump(report, f, indent=2, default=str)
    print(json.dumps(report, indent=2, default=str)); return 0

if __name__ == "__main__": raise SystemExit(main())
