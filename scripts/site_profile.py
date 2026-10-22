"""Where the site's time and memory go, page by page (read-only: reads R2 or a local folder, writes nothing there).

    python scripts/site_profile.py [OUT_FILE]

Renders each page the Site preview screenshots (Today, Company HCLTECH, Evidence, Filings, People, Data) in
one process with Streamlit's AppTest, the way the site runs them: the first page pays for loading every
table, the rest share the caches. For each page: seconds cold and warm (a second run), the process's
resident memory after it, and the functions that took the time (cProfile, cumulative). Then the size of
each table the pages share (screens/ctx.py). Uses the R2 secrets in the environment, or INSIDERS_LOCAL_DATA.
Run by .github/workflows/site-preview.yml after the screenshots; the text goes into its artifact.
"""
from __future__ import annotations

import cProfile
import io
import os
import pstats
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'streamlit_app'))
sys.path.insert(0, str(ROOT))

PAGES = [('home', {}, 'today'), ('company', {'symbol': 'HCLTECH'}, 'company-hcltech'), ('track_record', {}, 'evidence'),
         ('filings_all', {}, 'filings'), ('entity', {}, 'people'), ('data_status', {}, 'data')]
MB = 1024 ** 2


def rss_mb() -> tuple[float, float]:
    """(resident now, peak) in MB, from /proc on Linux, the process counters on Windows."""
    try:
        status = Path('/proc/self/status').read_text()
    except OSError:
        return _rss_windows()
    kb = {k: int(v.split()[0]) for k, v in (ln.split(':', 1) for ln in status.splitlines() if ln.startswith(('VmRSS', 'VmHWM')))}
    return kb.get('VmRSS', 0) / 1024, kb.get('VmHWM', 0) / 1024


def _rss_windows() -> tuple[float, float]:
    try:
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD), ('PeakWorkingSetSize', ctypes.c_size_t),
                        ('WorkingSetSize', ctypes.c_size_t), ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
                        ('QuotaPagedPoolUsage', ctypes.c_size_t), ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
                        ('QuotaNonPagedPoolUsage', ctypes.c_size_t), ('PagefileUsage', ctypes.c_size_t),
                        ('PeakPagefileUsage', ctypes.c_size_t)]
        c = Counters()
        c.cb = ctypes.sizeof(c)
        k32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb)
        return c.WorkingSetSize / MB, c.PeakWorkingSetSize / MB
    except Exception:  # noqa: BLE001 -- not Windows either
        return float('nan'), float('nan')


def script(screen: str, params: dict) -> str:
    return f"""
import sys
sys.path.insert(0, r'{ROOT / "streamlit_app"}')
sys.path.insert(0, r'{ROOT}')
import streamlit as st
for k, v in {params!r}.items():
    st.query_params[k] = v
from ui import theme
theme.inject()
import importlib
importlib.import_module('screens.{screen}').render()
"""


def top(prof: cProfile.Profile, n: int = 22) -> str:
    out = io.StringIO()
    st = pstats.Stats(prof, stream=out)
    st.sort_stats('cumulative').print_stats(r'(insiders_clean|streamlit_app|pandas/core/(groupby|frame|reshape)|pyarrow|botocore/endpoint)', n)
    lines = out.getvalue().splitlines()
    start = next((i for i, ln in enumerate(lines) if 'ncalls' in ln), 0)
    site = str(Path(pstats.__file__).parent)
    short = lambda ln: re.sub(r'\S*site-packages[\\/]', '', ln.replace(str(ROOT) + os.sep, '').replace(site + os.sep, ''))  # noqa: E731
    return '\n'.join(short(ln)[:160] for ln in lines[start:] if ln.strip())


def frames_report() -> str:
    from screens.ctx import load
    ctx = load()
    rows = []
    for name in ('trades', 'eligible', 'deals', 'securities', 'sast', 'actions', 'meetings', 'shareholding', 'preferential',
                 'rights', 'prices', 'results'):
        df = getattr(ctx, name)
        if df is None:
            continue
        rows.append(f'  {name:<13} {len(df):>7} rows {df.shape[1]:>3} cols {df.memory_usage(deep=True).sum() / MB:7.1f} MB (deep)')
    n_marks = sum(len(v) for v in (ctx.marks or {}).values())
    rows.append(f'  marks         {len(ctx.marks or {}):>7} ISINs, {n_marks} points')
    return '\n'.join(rows)


def main(out_path: str | None) -> None:
    from streamlit.testing.v1 import AppTest
    report = []
    say = lambda s='': (print(s), report.append(s))  # noqa: E731
    say(f'Site profile, Python {sys.version.split()[0]}, data from '
        f'{os.environ.get("INSIDERS_LOCAL_DATA") or "R2"}')
    say(f'Memory at start: {rss_mb()[0]:.0f} MB resident')
    summary = []
    for screen, params, label in PAGES:
        times = []
        for run in ('cold', 'warm'):
            prof = cProfile.Profile()
            at = AppTest.from_string(script(screen, params), default_timeout=600)
            t0 = time.perf_counter()
            prof.enable()
            at.run()
            prof.disable()
            times.append(time.perf_counter() - t0)
            if at.exception:
                say(f'!! {label} ({run}): {at.exception[0].value}')
            if run == 'cold':
                cold_prof = prof
        now, peak = rss_mb()
        summary.append((label, times[0], times[1], now, peak))
        say()
        say(f'== {label}: {times[0]:.2f} s cold, {times[1]:.2f} s warm; resident {now:.0f} MB, peak {peak:.0f} MB')
        say(top(cold_prof))
    say()
    say('== Tables the pages share (screens/ctx.py)')
    say(frames_report())
    say()
    say('| page | cold s | warm s | resident MB | peak MB |')
    say('|---|---:|---:|---:|---:|')
    for label, cold, warm, now, peak in summary:
        say(f'| {label} | {cold:.2f} | {warm:.2f} | {now:.0f} | {peak:.0f} |')
    if out_path:
        Path(out_path).write_text('\n'.join(report) + '\n', encoding='utf-8')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write('### Site profile (AppTest, one process)\n\n' + '\n'.join(report[-(len(summary) + 2):]) + '\n')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else None)
