from __future__ import annotations
import json, os, re, hashlib, time
from datetime import date, datetime
from io import StringIO
import pandas as pd, requests
TARGET=date.fromisoformat(os.getenv('TARGET_DATE','2026-08-31'))
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139.0 Safari/537.36'

def norm(s):
    s='' if s is None else str(s).strip().upper()
    return re.sub(r'[^A-Z0-9]+',' ',s).strip()
def num(s):
    if s in (None,''): return None
    try: return float(re.sub(r'[^0-9.-]','',str(s).replace(',','')))
    except: return None
def parse_date(v):
    if v in (None,''): return None
    for fmt in ('%d/%m/%Y','%d-%m-%Y','%d %b %Y','%d %b %y','%d/%b/%Y','%d-%b-%Y','%Y-%m-%d'):
        try: return datetime.strptime(str(v).strip(),fmt).date().isoformat()
        except: pass
    return None
def fp(row,fields):
    return hashlib.sha256('|'.join(norm(row.get(f,'')) for f in fields).encode()).hexdigest()[:20]
def nse():
    out={}
    s=requests.Session(); s.headers.update({'User-Agent':UA,'Referer':'https://www.nseindia.com/companies-listing/corporate-filings-insider-trading'})
    dd=TARGET.strftime('%d-%m-%Y')
    u=f'https://www.nseindia.com/api/corporates-pit?index=equities&from_date={dd}&to_date={dd}&csv=true'
    try:
        r=s.get(u,timeout=30); df=pd.read_csv(StringIO(r.text)) if r.ok and 'csv' in r.headers.get('content-type','') else pd.DataFrame()
        out['insider']={'status':r.status_code,'columns':list(df.columns),'rows':df.fillna('').to_dict('records')}
    except Exception as e: out['insider']={'error':str(e),'rows':[]}
    try:
        from nse import NSE
        with NSE(download_folder='artifacts/nse',server=True,timeout=30) as api:
            for k in ('bulk_deals','block_deals'):
                rows=[dict(x) for x in api.bulkdeals(k,datetime.combine(TARGET,datetime.min.time()),datetime.combine(TARGET,datetime.min.time()))]
                out[k]={'columns':sorted(rows[0]) if rows else [],'rows':rows}
    except Exception as e:
        out['bulk_deals']=out.get('bulk_deals',{'rows':[]}); out['block_deals']=out.get('block_deals',{'rows':[]}); out['package_error']=str(e)
    return out
def bse_pages():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    o=Options(); [o.add_argument(x) for x in ('--headless=new','--no-sandbox','--disable-dev-shm-usage','--disable-gpu',f'--user-agent={UA}')]
    d=webdriver.Chrome(options=o); out={}
    pages={'insider':'https://www.bseindia.com/corporates/insider_trading_new?expandable=2','bulk_deals':'https://www.bseindia.com/markets/equity/EQReports/bulk_deals.aspx','block_deals':'https://www.bseindia.com/markets/equity/EQReports/block_deals.aspx','rights':'https://www.bseindia.com/markets/publicissues/furtherissuesummary_ri','preferential':'https://www.bseindia.com/markets/publicissues/furtherissuesummary_pref'}
    for name,url in pages.items():
        d.get(url); time.sleep(4)
        data=d.execute_script("return Array.from(document.querySelectorAll('table')).map((t,i)=>({headers:Array.from(t.querySelectorAll('thead th')).map(x=>x.innerText.trim()),rows:Array.from(t.querySelectorAll('tbody tr')).map(r=>Array.from(r.cells).map(c=>c.innerText.trim())).filter(x=>x.length)})).filter(x=>x.rows.length)")
        rows=[]
        for t in data:
            for r in t['rows']:
                rows.append(dict(zip(t['headers'],r)) if len(t['headers'])==len(r) else {'_cells':r})
        out[name]={'columns':sorted(rows[0]) if rows else [],'rows':rows,'table_count':len(data),'title':d.title}
    d.quit(); return out
def audit(source,data):
    specs={'insider':['SYMBOL','COMPANY','NAME OF THE ACQUIRER/DISPOSER','BUY/SELL','NO. OF SECURITIES (ACQUIRED/DISPOSED)','DATE OF ALLOTMENT/ACQUISITION FROM','DATE OF ALLOTMENT/ACQUISITION TO'],'bulk_deals':['BD_DT_DATE','BD_SYMBOL','BD_CLIENT_NAME','BD_BUY_SELL','BD_QTY_TRD','BD_TP_WATP'],'block_deals':['BD_DT_DATE','BD_SYMBOL','BD_CLIENT_NAME','BD_BUY_SELL','BD_QTY_TRD','BD_TP_WATP'],'rights':[],'preferential':[]}
    report={}
    for k,v in data.items():
        rows=v.get('rows',[]); cols=v.get('columns',[]); dates=[]
        for r in rows:
            for c in cols:
                if 'DATE' in c.upper() or 'FROM' in c.upper() or 'TO' in c.upper():
                    p=parse_date(r.get(c));
                    if p: dates.append(p)
        fields=specs.get(k,[]); keys=[x for x in fields if x in cols]
        fps=[fp(r,keys) for r in rows] if keys else []
        report[k]={'rows':len(rows),'columns':cols,'date_min':min(dates) if dates else None,'date_max':max(dates) if dates else None,'duplicate_fingerprints':len(fps)-len(set(fps)) if fps else None,'buy_sell':{str(x):sum(1 for r in rows if norm(r.get(x,'')) in ('B','BUY')) for x in ['BD_BUY_SELL','BUY/SELL'] if x in cols}}
    return report
def main():
    os.makedirs('artifacts',exist_ok=True)
    n=nse(); b=bse_pages()
    report={'target_date':TARGET.isoformat(),'generated_at_utc':datetime.utcnow().isoformat(),'nse_audit':audit('NSE',n),'bse_audit':audit('BSE',b),'raw':{'NSE':n,'BSE':b}}
    # Insider cross-exchange candidate matching; never delete rows here.
    nr=n.get('insider',{}).get('rows',[]); br=b.get('insider',{}).get('rows',[])
    def candidate(r):
        vals={norm(v) for k,v in r.items() if any(x in k.upper() for x in ('SYMBOL','COMPANY','NAME','ACQUIRER','DISPOSER'))}; return vals
    matches=0
    for x in nr:
        nx=candidate(x)
        if nx and any(nx & candidate(y) for y in br): matches+=1
    report['cross_exchange']={'insider_candidate_overlap_count':matches,'nse_rows':len(nr),'bse_rows':len(br),'rule':'candidate overlap only; source observations retained'}
    with open('artifacts/exchange_validation.json','w',encoding='utf-8') as f: json.dump(report,f,ensure_ascii=False,indent=2,default=str)
    print(json.dumps({k:v for k,v in report.items() if k!='raw'},indent=2,default=str))
if __name__=='__main__': main()
