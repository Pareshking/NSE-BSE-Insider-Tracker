"""Evidence-first NSE certification report."""
from __future__ import annotations
import json,os
from pathlib import Path
TARGET=os.environ.get('TARGET_DATE','2026-08-31');LOOKBACK=int(os.environ.get('LOOKBACK_DAYS','90'));OUT=Path('artifacts/nse_validation');OUT.mkdir(parents=True,exist_ok=True)
def load(p):return json.loads(Path(p).read_text()) if Path(p).exists() else None
def main():
 r={'source':'NSE','target_date':TARGET,'lookback_days':LOOKBACK,'datasets':{},'promoter_semantics':'BLOCKED','certification':'BLOCKED'}
 paths=[('insider','artifacts/nse_insider/report.json'),('bulk','artifacts/nse_bulk/report.json'),('block','artifacts/nse_block/report.json'),('rights','artifacts/nse_validation/rights/report.json'),('preferential','artifacts/nse_validation/preferential/report.json')]
 for ds,path in paths:
  d=load(path) or {};ws=d.get('windows',[]);ok=False;details={}
  if ds in ('bulk','block'):
   ok=bool(ws) and all(w.get('count',0)>0 and (w.get('name') not in ('7d','30d','90d') or len(w.get('distinct_dates',[]))>1) for w in ws);details={'windows':[(w.get('name'),w.get('count'),w.get('distinct_dates')) for w in ws],'native_columns':bool(d.get('columns'))}
  elif ds=='insider':
   ok=bool(ws) and all(w.get('count',0)>0 and w.get('distinct_transaction_dates') for w in ws);details={'windows':[(w.get('name'),w.get('count'),w.get('distinct_transaction_dates')) for w in ws],'native_columns':bool(next((w.get('columns') for w in ws if w.get('columns')),[]))}
  else:
   ok=bool(ws) and all(any(x.get('status')==200 and x.get('row_count',0)>0 for x in w.get('api',[])) for w in ws);details={'windows':[(w.get('name'),w.get('api_rows'),w.get('api_distinct_dates')) for w in ws]}
  r['datasets'][ds]={'status':'VERIFIED' if ok else 'BLOCKED',**details}
ins=load('artifacts/nse_insider/90d.json') or {};rows=ins.get('rows',[]);cats=[];acq=disp=0
for x in rows:
 if isinstance(x,dict):
  cat=str(x.get('personCategory') or x.get('person_category') or '').upper();typ=str(x.get('transactionType') or x.get('acqMode') or x.get('type') or '').upper();cats.append(cat);acq+=int('ACQUIS' in typ or x.get('buyQuantity',0) not in (0,'0',''));disp+=int('DISPOS' in typ or x.get('sellquantity',0) not in (0,'0',''))
prom=any('PROMOTER' in c for c in cats);r['promoter_semantics']='VERIFIED' if rows and prom and (acq or disp) else 'BLOCKED';r['promoter_evidence']={'rows':len(rows),'promoter_categories':[c for c in sorted(set(cats)) if 'PROMOTER' in c],'acquisition_or_buy_rows':acq,'disposal_or_sell_rows':disp}
r['certification']='VERIFIED' if all(x['status']=='VERIFIED' for x in r['datasets'].values()) and r['promoter_semantics']=='VERIFIED' else 'BLOCKED';(OUT/'certification_report.json').write_text(json.dumps(r,indent=2));print(json.dumps(r,indent=2))
if __name__=='__main__':main()
