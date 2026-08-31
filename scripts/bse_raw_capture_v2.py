import json, os, re, time, hashlib
from datetime import date, timedelta
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys

TODAY = date.today()
END = date.fromisoformat(os.getenv("TARGET_DATE") or str(TODAY))
LOOKBACK = int(os.getenv("LOOKBACK_DAYS") or "90")
START = END - timedelta(days=max(0, LOOKBACK - 1))
OUT = Path("artifacts/data_validation_v5")
OUT.mkdir(parents=True, exist_ok=True)
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139 Safari/537.36"

PAGES = {
    "bulk_deals": "https://www.bseindia.com/markets/equity/EQReports/bulk_deals.aspx",
    "block_deals": "https://www.bseindia.com/markets/equity/EQReports/block_deals.aspx",
    "insider_trading": "https://www.bseindia.com/corporates/insider_trading_new?expandable=2",
    "rights_issue": "https://www.bseindia.com/markets/publicissues/furtherissuesummary_ri",
    "preferential_issue": "https://www.bseindia.com/markets/publicissues/furtherissuesummary_pref",
}

o = Options()
for arg in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", f"--user-agent={UA}"):
    o.add_argument(arg)
o.set_capability("goog:loggingPrefs", {"performance": "ALL", "browser": "ALL"})
d = webdriver.Chrome(options=o)


def tables():
    return d.execute_script("""
      return Array.from(document.querySelectorAll('table')).map(t => ({
        rows: Array.from(t.querySelectorAll('tr')).map(r => Array.from(r.cells).map(c => (c.innerText || '').trim())).filter(x => x.length),
        links: Array.from(t.querySelectorAll('a')).map(a => ({
          text:(a.innerText||'').trim(), href:a.href||'', onclick:a.getAttribute('onclick')||'',
          outer:a.outerHTML||'', data:Array.from(a.attributes).reduce((o,x)=>(o[x.name]=x.value,o),{})
        }))
      })).filter(x => x.rows.length);
    """)


def controls():
    return d.execute_script("""
      return Array.from(document.querySelectorAll('input,select,button')).map(x => ({
        type:x.type||'', name:x.name||'', id:x.id||'', value:x.value||'', text:(x.innerText||'').trim(),
        placeholder:x.getAttribute('placeholder')||'', cls:x.className||'', disabled:!!x.disabled,
        outer:x.outerHTML||''
      })).filter(x => x.name||x.id||x.value||x.text);
    """)


def page_rows():
    rows, links = [], []
    for t in tables():
        rows.extend(t["rows"])
        links.extend(t["links"])
    return rows, links


def network():
    events = []
    for item in d.get_log("performance"):
        try:
            msg = json.loads(item["message"])["message"]
            if msg.get("method") == "Network.requestWillBeSent":
                p = msg.get("params", {})
                req = p.get("request", {})
                url = req.get("url", "")
                if "bseindia.com" in url:
                    events.append({"url": url, "method": req.get("method"), "type": p.get("type"), "postData": req.get("postData", "")})
        except Exception:
            pass
    seen, out = set(), []
    for x in events:
        k = (x["method"], x["url"], x.get("postData", ""))
        if k not in seen:
            seen.add(k); out.append(x)
    return out


def click_search():
    return d.execute_script("""
      const xs=Array.from(document.querySelectorAll('button,input[type=submit],input[type=button],a'));
      const n=xs.find(x=>/search|submit|show/i.test((x.innerText||x.value||'').trim())&&!/reset|clear/i.test((x.innerText||x.value||'').trim()));
      if(n){n.click();return true} return false;
    """)


def set_date_range():
    nodes = d.find_elements("css selector", "input[name='datepicker'], input[id*='datepicker' i], input[class*='datepicker' i]")
    if len(nodes) < 2:
        nodes = d.find_elements("css selector", "input")
        nodes = [x for x in nodes if re.search(r"date|from|to", ((x.get_attribute("id") or "") + " " + (x.get_attribute("name") or "") + " " + (x.get_attribute("class") or "")), re.I)]
    if len(nodes) < 2:
        return {"status":"no_date_controls", "count":len(nodes), "controls":controls()}
    vals = [START.strftime("%d/%m/%Y"), END.strftime("%d/%m/%Y")]
    for node, value in zip(nodes[:2], vals):
        try:
            node.click()
            node.send_keys(Keys.CONTROL, "a")
            node.send_keys(value)
            node.send_keys(Keys.TAB)
        except Exception:
            pass
    before = page_rows()[0]
    clicked = click_search()
    time.sleep(4)
    # Some BSE datepickers raise a JS alert when a field was not registered by the widget.
    alert_text = None
    try:
        alert = d.switch_to.alert
        alert_text = alert.text
        alert.accept()
    except Exception:
        pass
    after, _ = page_rows()
    return {
        "status": "changed" if after != before else "no_change",
        "clicked_search": bool(clicked),
        "alert": alert_text,
        "start_date": str(START), "end_date": str(END),
        "before_row_count": len(before), "after_row_count": len(after),
        "controls": controls(),
    }


out = {}
for ds, url in PAGES.items():
    d.get(url)
    time.sleep(5)
    initial, links = page_rows()
    ctl = controls()
    pages_data = []
    seen_sigs = set()
    detail = []
    hist = {"attempted": False, "status": "not_attempted"}

    if ds in ("rights_issue", "preferential_issue"):
        for page_no in range(1, 11):
            rs, ls = page_rows()
            sig = hashlib.sha256(json.dumps(rs, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            if not rs or sig in seen_sigs:
                break
            seen_sigs.add(sig)
            pages_data.append({"page": page_no, "rows": rs, "links": ls})
            clicked = d.execute_script("""
              const xs=Array.from(document.querySelectorAll('button,input[type=button],input[type=submit],a'));
              const n=xs.find(x=>/^next$/i.test((x.innerText||x.value||'').trim())&&!x.disabled&&!x.classList.contains('disabled'));
              if(n){n.click();return true} return false;
            """)
            if not clicked:
                break
            time.sleep(3)
        # Preserve the actual detail target attributes. Follow unique hrefs when available.
        hrefs=[]
        for p in pages_data:
            for l in p["links"]:
                if re.search(r"view.*detail|view.*details", l.get("text",""), re.I):
                    if l.get("href") and l["href"] not in hrefs: hrefs.append(l["href"])
        for href in hrefs[:20]:
            try:
                d.get(href); time.sleep(2.5)
                rs, ls = page_rows()
                detail.append({"href":href, "title":d.title, "url":d.current_url, "rows":rs[:200], "controls":controls()})
            except Exception as e:
                detail.append({"href":href, "error":str(e)})
        # Return to the index before date testing is attempted.
        d.get(url); time.sleep(4)
    else:
        pages_data = [{"page":1, "rows":initial, "links":links}]

    date_nodes = [c for c in ctl if re.search(r"date|from|to", (c.get("id","")+c.get("name","")+c.get("cls","")).lower())]
    if date_nodes or ds == "insider_trading":
        hist = set_date_range()
        hist["attempted"] = True

    out[ds] = {
        "pages": pages_data,
        "controls": ctl,
        "historical_date_test": hist,
        "page_count": len(pages_data),
        "row_count": sum(len(x["rows"]) for x in pages_data),
        "detail_pages": detail,
        "network_requests": network(),
        "title": d.title,
        "url": d.current_url,
    }

d.quit()
result = {
    "target_date": str(END),
    "start_date": str(START),
    "lookback_days": LOOKBACK,
    "datasets": out,
}
Path(OUT / "bse_raw.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
print({k:(v['page_count'],v['row_count'],v['historical_date_test'].get('status')) for k,v in out.items()})
