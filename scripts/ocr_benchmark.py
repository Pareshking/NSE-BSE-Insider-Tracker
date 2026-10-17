"""OCR / table-extraction benchmark on filing pages whose cells were read off the page images (owner's request, 17 Oct 2026).

One engine a run (ENGINE=tesseract|paddle|paddle_structure|docling|marker), the same page image or single-page PDF for each. Scored on the
cells read from the pages by eye: number recall (is every expected figure in the output, with its sign?) and row integrity (label, then its
figures in order within WINDOW characters). Failures of an engine to install or run are results, printed, not hidden. Nothing is written
outside OUT_DIR; no filing is changed.
"""
from __future__ import annotations

import io
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from r2_writer import BUCKET, r2_client  # noqa: E402
import announcement_sample as sample  # noqa: E402

ENGINE = os.environ.get('ENGINE', 'tesseract')
OUT_DIR = Path(os.environ.get('OUT_DIR', 'ocr_out'))
WINDOW = 300
# event_id -> (page, [(label, [figures in the order the page shows them])]); every figure read off the page image
TRUTH = {
    'bse:43aa426c-0e01-4c7f-b061-944ce743efed': (4, [   # Bajaj Healthcare results (a scan whose embedded text layer misreads 17,590.16 and 16,563.17)
        ('Revenue from operations', ['17,590.16', '16,563.17', '14,791.49', '34,153.33', '29,675.12', '61,103.14']),
        ('Other income', ['89.24', '81.14', '165.29', '170.38', '253.06', '713.39']),
        ('Total income', ['17,679.40', '16,644.31', '14,956.78', '34,323.71', '29,928.18', '61,816.53']),
        ('Profit before tax', ['1,847.59', '1,645.83', '1,596.21', '3,493.42', '3,048.72', '2,892.30'])]),
    'bse:fe68aee3-b3b9-4bbe-bff0-62c26c69cc5d': (5, [   # ixigo consolidated results (a scan)
        ('Revenue from operations', ['320.96', '356.75', '284.23', '677.71', '600.28', '1,228.04']),
        ('Total income', ['343.04', '385.90', '289.40', '728.94', '612.41', '1,275.35']),
        ('before tax', ['71.70', '44.16', '(3.96)', '115.86', '22.37', '88.54']),
        ('for the period', ['63.42', '34.24', '(3.46)', '97.66', '15.48', '71.48'])]),
    'nse:106821000': (2, [   # Maithan acquisition form (a scan)
        ('Turnover', ['2446']), ('Networth', ['1526']), ('Total Cost of acquisition', ['19.97']), ('0.04%', ['228000'])]),
    'bse:263abe2e-c21f-4f5b-934b-f4f33dbd2e28': (2, [   # Unimech pledge table (a scan)
        ('Preetham', ['48,71,194', '9.57', '29.09.2026', '1,87,500', '0.37'])]),
    'nse:106815713': (1, [   # Kernex rating table (a scan)
        ('Long-term', ['125.00', '100.00']), ('Long-term', ['10.00']), ('Long-term', ['525.00', '175.00'])]),
    'bse:e0983f88-a4d2-4e20-a0a0-372f8600fffa': (2, [   # Paushak results (a digital PDF drawn as an image)
        ('Revenue from Operations', ['8,932', '8,355', '5,878', '17,287', '11,466', '21,860']),
        ('Profit before Tax', ['1,860', '1,902', '1,134', '3,761', '2,697', '5,041']),
        ('Profit after tax', ['1,351', '1,510', '861', '2,862', '2,065', '3,933'])]),
    'nse:106820217': (4, [   # Jindal Saw standalone highlights (a slide)
        ('Total Income', ['38,814', '37,557', '34,091', '76,371', '67,359', '1,47,445']),
        ('Profit after Tax', ['707', '1,098', '793', '1,805', '4,432', '7,840'])]),
}


def render(pdf: bytes, page: int, dpi: int = 200) -> tuple[Path, Path]:
    d = Path(tempfile.mkdtemp())
    src = d / 'f.pdf'
    src.write_bytes(pdf)
    subprocess.run(['pdftoppm', '-r', str(dpi), '-png', '-singlefile', '-f', str(page), '-l', str(page), str(src), str(d / 'p')], capture_output=True, timeout=180, check=False)
    import pymupdf
    one = d / 'one.pdf'
    with pymupdf.open(str(src)) as a, pymupdf.open() as b:
        b.insert_pdf(a, from_page=page - 1, to_page=page - 1)
        b.save(str(one))
    return d / 'p.png', one


def run_tesseract(png: Path, pdf: Path) -> str:
    return subprocess.run(['tesseract', str(png), '-', '--psm', '6'], capture_output=True, timeout=300, check=False).stdout.decode('utf-8', errors='replace')


_PADDLE = {}


def _lines(items) -> str:
    """Text boxes (y, x, text) joined into lines by their vertical position."""
    items = sorted(items, key=lambda t: (round(t[0] / 12), t[1]))
    out, cur, last = [], [], None
    for y, x, t in items:
        k = round(y / 12)
        if last is not None and k != last:
            out.append('  '.join(cur))
            cur = []
        cur.append(t)
        last = k
    if cur:
        out.append('  '.join(cur))
    return '\n'.join(out)


def run_paddle(png: Path, pdf: Path) -> str:
    from paddleocr import PaddleOCR
    if 'ocr' not in _PADDLE:   # mkldnn off: Paddle 3.x's oneDNN path raised NotImplementedError (ConvertPirAttribute2RuntimeAttribute) on the CPU runner
        _PADDLE['ocr'] = PaddleOCR(lang='en', enable_mkldnn=False, use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False)
    ocr = _PADDLE['ocr']
    res = ocr.predict(str(png)) if hasattr(ocr, 'predict') else ocr.ocr(str(png))
    items = []
    for r in res:
        data = r if isinstance(r, dict) else getattr(r, 'json', {}) or {}
        data = data.get('res', data)
        texts, boxes = data.get('rec_texts'), data.get('rec_boxes') if data.get('rec_boxes') is not None else data.get('rec_polys')
        if texts is not None and boxes is not None:
            for t, b in zip(texts, boxes):
                b = [float(v) for v in (b if len(getattr(b, 'shape', [])) == 1 else [x for p in b for x in p])]
                xs, ys = b[0::2] if len(b) > 4 else [b[0], b[2]], b[1::2] if len(b) > 4 else [b[1], b[3]]
                items.append(((min(ys) + max(ys)) / 2, min(xs), t))
        elif isinstance(r, list):          # PaddleOCR 2.x: [[box, (text, conf)], ...]
            for box, (t, _) in r:
                ys, xs = [p[1] for p in box], [p[0] for p in box]
                items.append(((min(ys) + max(ys)) / 2, min(xs), t))
    return _lines(items)


def run_paddle_mobile(png: Path, pdf: Path) -> str:
    """PP-OCRv5 mobile models: the same engine with the small detector and recogniser (speed against accuracy)."""
    from paddleocr import PaddleOCR
    if 'mobile' not in _PADDLE:
        _PADDLE['mobile'] = PaddleOCR(lang='en', enable_mkldnn=False, text_detection_model_name='PP-OCRv5_mobile_det', text_recognition_model_name='PP-OCRv5_mobile_rec',
                                      use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False)
    _PADDLE['ocr'] = _PADDLE['mobile']
    return run_paddle(png, pdf)


def _structure(key: str, **kw):
    """PPStructureV3 built with the given options; options this PaddleOCR version does not know are dropped one at a time."""
    from paddleocr import PPStructureV3
    kw = dict(kw)
    while True:
        try:
            return PPStructureV3(enable_mkldnn=False, **kw)
        except TypeError as exc:
            bad = next((k for k in kw if k in str(exc)), None)
            if bad is None:
                raise
            print(f'NOTE PPStructureV3 does not take {bad}; dropped', flush=True)
            kw.pop(bad)


def _structure_text(pipe, png: Path) -> str:
    out = []
    for r in pipe.predict(str(png)):
        md = getattr(r, 'markdown', None) or (r.get('markdown') if isinstance(r, dict) else None)
        out.append(md.get('markdown_texts', '') if isinstance(md, dict) else str(md))
    return '\n'.join(out)


def run_paddle_structure(png: Path, pdf: Path) -> str:
    """PP-StructureV3 with its default models (asked for 20 GB on the 7 GB runner in the first run)."""
    if 'st' not in _PADDLE:
        _PADDLE['st'] = _structure('st', use_doc_orientation_classify=False, use_doc_unwarping=False)
    return _structure_text(_PADDLE['st'], png)


def run_paddle_structure_text(png: Path, pdf: Path) -> str:
    """PP-StructureV3 as layout + OCR in reading order (no table, seal, formula or chart models; mobile OCR models)."""
    if 'text' not in _PADDLE:
        _PADDLE['text'] = _structure('text', use_doc_orientation_classify=False, use_doc_unwarping=False, use_seal_recognition=False,
                                     use_formula_recognition=False, use_chart_recognition=False, use_region_detection=False,
                                     use_table_recognition=False, text_detection_model_name='PP-OCRv5_mobile_det',
                                     text_recognition_model_name='PP-OCRv5_mobile_rec')
    return _structure_text(_PADDLE['text'], png)


def run_paddle_structure_lite(png: Path, pdf: Path) -> str:
    """PP-StructureV3 with the small models and only the parts a filing needs (layout, OCR, tables)."""
    if 'lite' not in _PADDLE:
        _PADDLE['lite'] = _structure('lite', use_doc_orientation_classify=False, use_doc_unwarping=False, use_seal_recognition=False,
                                     use_formula_recognition=False, use_chart_recognition=False, use_region_detection=False,
                                     text_detection_model_name='PP-OCRv5_mobile_det', text_recognition_model_name='PP-OCRv5_mobile_rec',
                                     layout_detection_model_name='PP-DocLayout-S',
                                     wired_table_structure_recognition_model_name='SLANet', wireless_table_structure_recognition_model_name='SLANet')
    return _structure_text(_PADDLE['lite'], png)


_DOC = {}


def run_docling(png: Path, pdf: Path) -> str:
    from docling.document_converter import DocumentConverter
    if 'c' not in _DOC:
        _DOC['c'] = DocumentConverter()
    return _DOC['c'].convert(str(pdf)).document.export_to_markdown()


_MARKER = {}


def run_marker(png: Path, pdf: Path) -> str:
    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict
    if 'c' not in _MARKER:
        _MARKER['c'] = PdfConverter(artifact_dict=create_model_dict())
    rendered = _MARKER['c'](str(pdf))
    return getattr(rendered, 'markdown', None) or str(rendered)


ENGINES = {'tesseract': run_tesseract, 'paddle': run_paddle, 'paddle_mobile': run_paddle_mobile, 'paddle_structure': run_paddle_structure, 'paddle_structure_lite': run_paddle_structure_lite, 'paddle_structure_text': run_paddle_structure_text, 'docling': run_docling, 'marker': run_marker}


def norm(s: str) -> str:
    return re.sub(r'\s+', ' ', str(s).replace('|', ' ').replace('−', '-'))


def has(text: str, fig: str) -> tuple[bool, bool]:
    """(figure present as a figure, present with its sign: '(3.96)' or '-3.96' for a negative)."""
    neg = fig.startswith('(')
    core = fig.strip('()')
    present = re.search(r'(?<![\d.,])' + re.escape(core) + r'(?![\d])', text) is not None
    if not neg:
        return present, present
    return present, re.search(r'\(\s*' + re.escape(core) + r'\s*\)|-\s*' + re.escape(core), text) is not None


def intact(text: str, label: str, figs: list[str]) -> bool:
    flat = norm(text)
    for m in re.finditer(re.escape(label), flat, re.IGNORECASE):
        at, ok = m.end(), True
        for f in figs:
            core = f.strip('()')
            i = flat.find(core, at)
            if i < 0 or i - m.end() > WINDOW:
                ok = False
                break
            at = i + len(core)
        if ok:
            return True
    return False


def main() -> int:
    r2 = r2_client()
    frames = []
    for ex in ('nse', 'bse'):
        keys = sorted(o['Key'] for p in r2.get_paginator('list_objects_v2').paginate(Bucket=BUCKET, Prefix=f'archive/announcements/{ex}/')
                      for o in p.get('Contents', []) if o['Key'].endswith('.parquet'))
        for k in keys:
            df = pd.read_parquet(io.BytesIO(r2.get_object(Bucket=BUCKET, Key=k)['Body'].read()), columns=['event_id', 'file_url', 'subject'])
            frames.append(df[df['event_id'].isin(TRUTH)])
    allr = pd.concat(frames).drop_duplicates('event_id') if frames else pd.DataFrame(columns=['event_id', 'file_url', 'subject'])
    urls = HERE / 'vision_urls.txt'
    if urls.exists():
        extra = pd.DataFrame([dict(zip(('event_id', 'file_url', 'subject'), ln.split('\t'))) for ln in urls.read_text().splitlines() if ln.count('\t') >= 2])
        extra = extra[extra['event_id'].isin(TRUTH)]
        allr = pd.concat([allr, extra]).drop_duplicates('event_id')
    OUT_DIR.mkdir(exist_ok=True)
    run = ENGINES[ENGINE]
    md = [f'## OCR benchmark: {ENGINE}', '']
    tot = {'figs': 0, 'present': 0, 'signed': 0, 'rows': 0, 'intact': 0, 'secs': 0.0, 'pages': 0, 'failed': 0}
    for _, f in allr.iterrows():
        eid = f['event_id']
        page, rows = TRUTH[eid]
        try:
            png, one = render(sample.download(f['file_url']), page)
        except Exception as exc:  # noqa: BLE001
            md.append(f'- {eid}: could not draw page {page}: {exc}')
            continue
        t0 = time.monotonic()
        try:
            text = run(png, one)
            err = ''
        except Exception as exc:  # noqa: BLE001 -- an engine that fails is a result
            text, err = '', f'{type(exc).__name__}: {str(exc)[:700]}'
            tot['failed'] += 1
        secs = time.monotonic() - t0
        (OUT_DIR / f'{eid.replace(":", "_")}_{ENGINE}.txt').write_text(text or err)
        flat = norm(text)
        figs = [x for _, fs in rows for x in fs]
        pres = [has(flat, x) for x in figs]
        ints = [intact(text, lab, fs) for lab, fs in rows]
        tot['figs'] += len(figs); tot['present'] += sum(p for p, _ in pres); tot['signed'] += sum(s for _, s in pres)
        tot['rows'] += len(ints); tot['intact'] += sum(ints); tot['secs'] += secs; tot['pages'] += 1
        md.append(f'- {eid} p{page}: figures {sum(p for p, _ in pres)}/{len(figs)} (sign ok {sum(s for _, s in pres)}), rows intact {sum(ints)}/{len(ints)}, {secs:.1f} s' + (f' ERROR {err}' if err else ''))
    md += ['', f'**{ENGINE}**: figures {tot["present"]}/{tot["figs"]}, with sign {tot["signed"]}/{tot["figs"]}, rows intact {tot["intact"]}/{tot["rows"]}, '
               f'{tot["secs"] / max(1, tot["pages"]):.1f} s a page, {tot["failed"]} pages failed']
    out = '\n'.join(md)
    print(out)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        Path(os.environ['GITHUB_STEP_SUMMARY']).write_text(out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
