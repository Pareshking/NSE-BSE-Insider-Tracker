"""Orchestrator only: NSE and BSE acquisition engines are intentionally separate."""
from __future__ import annotations
import json,os
from datetime import datetime
from nse_acquisition import acquire as acquire_nse
from bse_acquisition import acquire as acquire_bse

def main():
    os.makedirs('artifacts',exist_ok=True)
    nse=acquire_nse(); bse=acquire_bse(max_pages=5)
    report={'target_date':os.getenv('TARGET_DATE','2026-08-31'),'phase':'separate NSE/BSE acquisition probe','generated_at_utc':datetime.utcnow().isoformat(),'NSE':nse,'BSE':bse,'architecture':{'NSE':'scripts/nse_acquisition.py','BSE':'scripts/bse_acquisition.py','pagination_test_cap':5,'production_backfill':False}}
    with open('artifacts/acquisition_probe.json','w',encoding='utf-8') as f: json.dump(report,f,indent=2,default=str)
    print(json.dumps(report,indent=2,default=str))
if __name__=='__main__':main()
