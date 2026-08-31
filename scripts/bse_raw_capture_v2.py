import json,time,re
from datetime import date
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
D=date.fromisoformat('2026-08-31'); H=date.fromisoformat('2026-08-28')
OUT=Path('artifacts/data_validation_v4');OUT.mkdir(parents=True,exist_ok=True)
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139 Safari/537.36'
pages={'bulk_deals':'https://www.bseindia.com/markets/equity/EQReports/bulk_deals.aspx','block_deals':'https://www.bseindia.com/markets/equity/EQReports/block_deals.aspx','insider_trading':'https://www.bseindia.com/corporates/insider_trading_new?expandable=2','rights_issue':'https://www.bseindia.com/markets/publicissues/furtherissuesummary_ri','preferential_issue':'https://www.bseindia.com/markets/publicissues/furtherissuesummary_pref'}
o=Options();[o.add_argument(x) for x in ('--headless=new','--no-sandbox','--disable-dev-shm-usage','--disable-gpu',f'--user-agent={UA}')]
d=webdriver.Chrome(options=o)
def tables(): return d.execute_script("""return Array.from(document.querySelectorAll('table')).map(t=>({rows:Array.from(t.querySelectorAll('tr')).map(r=>Array.from(r.cells).map(c=>(c.innerText||'').trim())).filter(x=>x.length),links:Array.from(t.querySelectorAll('a')).map(a=>({text:(a.innerText||'').trim(),href:a.href,onclick:a.getAttribute('onclick')||''}))})).filter(x=>x.rows.length);""")
def controls(): return d.execute_script("""return Array.from(document.querySelectorAll('input,select,button')).map(x=>({type:x.type||'',name:x.name||'',id:x.id||'',value:x.value||'',text:(x.innerText||'').trim(),disabled:!!x.disabled})).filter(x=>x.name||x.id||x.value||x.text);""")
def issue_rows():
 rows=[];links=[]
 for t in tables():
  for r in t['rows']:
   if len(r)>=3 and not any(z in (r[0] or '').lower() for z in ('company name','display','previous','next')) and not re.fullmatch(r'\d+',r[0] or ''):rows.append(r)
  links+=t['links']
 return rows,links
out={}
for ds,u in pages.items():
 d.get(u);time.sleep(4);initial,links=issue_rows();ctl=controls();pages_data=[];seen=set();hist={'attempted':False,'status':'not_available'}
 if ds in ('rights_issue','preferential_issue'):
  for _ in range(60):
   rs,ls=issue_rows();sig=tuple(tuple(r) for r in rs[:3])
   if sig in seen or not rs:break
   seen.add(sig);pages_data.append({'rows':rs,'links':ls})
   clicked=d.execute_script("""const bs=Array.from(document.querySelectorAll('button,input[type=submit],a'));const n=bs.find(x=>/^next$/i.test((x.innerText||x.value||'').trim())&&!x.disabled);if(n){n.click();return true}return false;""")
   if not clicked:break
   time.sleep(2.5)
 else:pages_data=[{'rows':tables()[0]['rows'] if tables() else [],'links':links}]
 date_nodes=[c for c in ctl if 'datepicker' in c['id'].lower() or 'date' in c['name'].lower()]
 if date_nodes:
  hist={'attempted':True,'status':'no_change','target_date':str(H),'controls':date_nodes[:10]}
  try:
   d.execute_script("""const v=arguments[0];const ns=Array.from(document.querySelectorAll('input')).filter(x=>/datepicker|date/i.test((x.id||'')+' '+(x.name||'')));for(const n of ns){n.value=v;n.dispatchEvent(new Event('input',{bubbles:true}));n.dispatchEvent(new Event('change',{bubbles:true}))}const b=Array.from(document.querySelectorAll('button,input[type=submit]')).find(x=>/search|submit/i.test((x.innerText||x.value||'').trim())&&!/reset/i.test((x.innerText||x.value||'').trim()));if(b)b.click();""",H.strftime('%d/%m/%Y'));time.sleep(3);hrs,_=issue_rows();hist.update(status='changed' if hrs!=initial else 'no_change',historical_row_count=len(hrs),initial_row_count=len(initial))
  except Exception as e:hist.update(status='error',error=str(e))
 out[ds]={'pages':pages_data,'controls':ctl,'historical_date_test':hist,'page_count':len(pages_data),'row_count':sum(len(x['rows']) for x in pages_data),'title':d.title,'url':d.current_url}
d.quit();Path(OUT/'bse_raw.json').write_text(json.dumps({'target_date':str(D),'datasets':out},indent=2),encoding='utf-8');print({k:(v['page_count'],v['row_count'],v['historical_date_test']) for k,v in out.items()})
