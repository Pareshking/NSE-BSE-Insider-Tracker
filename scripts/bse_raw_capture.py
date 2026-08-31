import json,time
from datetime import date
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
D=date.fromisoformat('2026-08-31')
OUT=Path('artifacts/data_validation_v3');OUT.mkdir(parents=True,exist_ok=True)
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139 Safari/537.36'
pages={'bulk_deals':'https://www.bseindia.com/markets/equity/EQReports/bulk_deals.aspx','block_deals':'https://www.bseindia.com/markets/equity/EQReports/block_deals.aspx','insider_trading':'https://www.bseindia.com/corporates/insider_trading_new?expandable=2','rights_issue':'https://www.bseindia.com/markets/publicissues/furtherissuesummary_ri','preferential_issue':'https://www.bseindia.com/markets/publicissues/furtherissuesummary_pref'}
o=Options();[o.add_argument(x) for x in ('--headless=new','--no-sandbox','--disable-dev-shm-usage','--disable-gpu',f'--user-agent={UA}')]
d=webdriver.Chrome(options=o);out={}
for ds,u in pages.items():
 d.get(u);time.sleep(4)
 tabs=d.execute_script("""return Array.from(document.querySelectorAll('table')).map(t=>({rows:Array.from(t.querySelectorAll('tr')).map(r=>Array.from(r.cells).map(c=>(c.innerText||'').trim())).filter(x=>x.length),links:Array.from(t.querySelectorAll('a')).map(a=>({text:(a.innerText||'').trim(),href:a.href,onclick:a.getAttribute('onclick')||''}))})).filter(x=>x.rows.length);""")
 ctl=d.execute_script("""return Array.from(document.querySelectorAll('input,select,button')).map(x=>({type:x.type||'',name:x.name||'',id:x.id||'',value:x.value||'',text:(x.innerText||'').trim()})).filter(x=>x.name||x.id||x.value||x.text);""")
 out[ds]={'tables':tabs,'controls':ctl,'url':d.current_url,'title':d.title}
d.quit();Path(OUT/'bse_raw.json').write_text(json.dumps({'target_date':str(D),'datasets':out},indent=2),encoding='utf-8');print({k:sum(len(t['rows']) for t in v['tables']) for k,v in out.items()})
