"""BSE-only acquisition engine. Browser rendering and BSE pagination stay isolated from NSE."""
from __future__ import annotations
import os,time,re,json
from datetime import date
from pathlib import Path
TARGET_DATE=os.getenv('TARGET_DATE','2026-08-31'); D=date.fromisoformat(TARGET_DATE)
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139 Safari/537.36'
PAGES={'bulk_deals':'https://www.bseindia.com/markets/equity/EQReports/bulk_deals.aspx','block_deals':'https://www.bseindia.com/markets/equity/EQReports/block_deals.aspx','insider_trading':'https://www.bseindia.com/corporates/insider_trading_new?expandable=2','rights_issue':'https://www.bseindia.com/markets/publicissues/furtherissuesummary_ri','preferential_issue':'https://www.bseindia.com/markets/publicissues/furtherissuesummary_pref'}
def acquire(max_pages=5):
 from selenium import webdriver
 from selenium.webdriver.chrome.options import Options
 o=Options();[o.add_argument(x) for x in ('--headless=new','--no-sandbox','--disable-dev-shm-usage','--disable-gpu',f'--user-agent={UA}')]
 d=webdriver.Chrome(options=o);out=[]
 for dataset,url in PAGES.items():
  d.get(url);time.sleep(4);seen=set();pages=[]
  for page_no in range(1,max_pages+1):
   rows=d.execute_script("return Array.from(document.querySelectorAll('table')).flatMap(t=>Array.from(t.querySelectorAll('tbody tr')).map(r=>Array.from(r.cells).map(c=>c.innerText.trim())).filter(x=>x.length))")
   sig=json.dumps(rows[:3],sort_keys=True)
   if not rows or sig in seen:break
   seen.add(sig);pages.append({'page':page_no,'rows':rows})
   if dataset not in ('rights_issue','preferential_issue'):break
   moved=d.execute_script("const x=Array.from(document.querySelectorAll('button,input[type=submit],a')).find(e=>/^next$/i.test((e.innerText||e.value||'').trim())&&!e.disabled);if(x){x.click();return true}return false")
   if not moved:break
   time.sleep(2.5)
  body=d.find_element('tag name','body').text
  tokens=[D.strftime(f) for f in ('%Y-%m-%d','%d/%m/%Y','%d-%m-%Y','%d %b %Y','%d %b %y','%d/%b/%Y','%d-%b-%Y')]
  out.append({'source':'BSE','dataset':dataset,'method':'selenium_render','target_date':TARGET_DATE,'page_count':len(pages),'row_count':sum(len(p['rows']) for p in pages),'pages':pages,'contains_target_date':any(x in body for x in tokens),'target_tokens':tokens,'title':d.title,'url':d.current_url})
 d.quit();return out
if __name__=='__main__':print(json.dumps(acquire(),indent=2))
