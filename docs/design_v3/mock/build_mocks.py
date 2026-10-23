"""Design mocks of the proposed pages: the site's own CSS and cell helpers, real rows from the test fixtures.
Cells with a dotted underline are placeholders (market cap, price, 52-week range): not in the fixtures."""
import html
import sys
from pathlib import Path

S = Path(__file__).resolve().parent
sys.path.insert(0, str(S))
sys.path.insert(0, str(S.parents[2] / 'streamlit_app'))
import mock_data as md  # noqa: E402
from ui import kit  # noqa: E402

CSS = ((Path(md.ROOT) / 'streamlit_app/ui/insiders.css').read_text() + (Path(md.ROOT) / 'streamlit_app/ui/table.css').read_text())
import tempfile  # noqa: E402

OUT = Path(tempfile.gettempdir()) / 'design_v3_html'   # the HTML pages; shoot.py turns them into the PNGs
OUT.mkdir(exist_ok=True)
esc = html.escape

TOG_ON = '<span class="tog"><i></i>Real money only</span>'
TOG_OFF = '<span class="tog off"><i></i>Real money only</span>'
MOCK_CSS = """
html, body { margin: 0; background: #fff; color: var(--ink); font-family: var(--ui); font-size: 14px; -webkit-font-smoothing: antialiased; }
.banner { background: #FFF8E6; border-bottom: 1px solid #F1DDA8; color: #6B4A06; font-size: 12px; padding: 6px 24px; }
.banner b { font-weight: 650; } .banner .ph { border-bottom: 1px dotted #6B4A06; }
.mtop { display: flex; align-items: center; gap: 28px; height: 54px; padding: 0 24px; border-bottom: 1px solid var(--line); background: #fff; }
.mtop .brand { font-weight: 700; font-size: 16px; letter-spacing: -.01em; }
.mtop nav { display: flex; gap: 4px; flex: 1; }
.mtop nav a { padding: 16px 12px 14px; color: var(--ink-2); text-decoration: none; font-size: 14px; border-bottom: 2px solid transparent; }
.mtop nav a.on { color: var(--accent-ink); font-weight: 600; border-bottom-color: var(--accent); }
.mtop .search { border: 1px solid var(--line); border-radius: 8px; padding: 7px 12px; width: 260px; color: var(--ink-3); font-size: 13px; background: var(--subtle); }
.wrap { max-width: 1380px; margin: 0 auto; padding: 0 24px 56px; }
.strip { margin-top: 12px; }
.bar { display: flex; flex-wrap: wrap; gap: 10px 14px; align-items: center; margin: 4px 0 14px; }
.pills { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.pills .lbl { font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: var(--ink-3); font-weight: 600; margin-right: 2px; }
.p { border: 1px solid var(--line); border-radius: 999px; padding: 5px 13px; font-size: 13px; color: var(--ink-2); background: #fff; white-space: nowrap; }
.p.on { background: var(--accent-tint); color: var(--accent-ink); border-color: #C9CDFB; font-weight: 600; }
.p small { color: var(--ink-3); font-weight: 500; margin-left: 3px; }
.tog { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; color: var(--ink-2); }
.tog i { width: 30px; height: 17px; border-radius: 9px; background: var(--accent); position: relative; display: inline-block; }
.tog.off i { background: #C9CED8; } .tog.off i::after { right: auto; left: 2px; }
.tog i::after { content: ''; position: absolute; right: 2px; top: 2px; width: 13px; height: 13px; border-radius: 50%; background: #fff; }
.filt { border: 1px solid var(--line); border-radius: 8px; padding: 6px 12px; font-size: 13px; color: var(--ink-2); }
.mcard { background: #fff; border: 1px solid var(--line); border-radius: 8px; padding: 14px 16px 6px; margin-top: 14px; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.ph { border-bottom: 1px dotted #8A93A3; }
.mk { font-size: 11.5px; color: var(--ink-3); display: inline-flex; gap: 6px; align-items: center; white-space: nowrap; }
.rgm { display: inline-block; position: relative; width: 44px; height: 4px; border-radius: 2px; background: linear-gradient(90deg, #F2D4D0, #E6E9EE 50%, #CBEAD9); vertical-align: middle; }
.rgm i { position: absolute; top: -3px; width: 3px; height: 10px; margin-left: -1.5px; border-radius: 2px; background: var(--ink); }
.qm { display: inline-flex; width: 15px; height: 15px; border-radius: 50%; background: var(--warn-tint); color: var(--warn-ink); font-size: 10px; font-weight: 700; align-items: center; justify-content: center; margin-left: 6px; cursor: help; }
.hl { margin: 0; font-size: 13.5px; color: var(--ink-2); line-height: 1.45; }
.idea > summary { padding: 14px 4px; }
.idea .co2 { font-size: 11.5px; color: var(--ink-3); display: flex; gap: 6px; align-items: center; }
.idea-chips .chip.ev { background: #fff; border: 1px solid var(--line); color: var(--ink-3); }
.note { font-size: 12.5px; color: var(--ink-3); margin: 8px 2px 12px; }
.tbl td.wrapc { white-space: normal; max-width: 250px; line-height: 1.35; } .tbl td { height: 58px; } .tbl td.co { max-width: 340px; min-width: 300px; }
.tbl .sub.mk { margin-top: 2px; }
.tg-b { font-weight: 700; }
.leg { display: flex; gap: 16px; flex-wrap: wrap; font-size: 12px; color: var(--ink-3); margin: 10px 2px 0; }
.ratios { display: grid; grid-template-columns: repeat(6, 1fr); border: 1px solid var(--line); border-radius: 8px; margin-top: 10px; }
.ratios > div { padding: 12px 16px; border-right: 1px solid #EDEFF3; display: grid; gap: 4px; align-content: start; }
.ratios > div:last-child { border-right: 0; }
.ratios .k { font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: var(--ink-3); font-weight: 600; }
.ratios .v { font-size: 20px; font-weight: 600; letter-spacing: -.01em; font-variant-numeric: tabular-nums; }
.ratios .s { font-size: 12px; color: var(--ink-3); }
.flow { display: grid; gap: 12px; padding: 4px 0 12px; }
.flow .r { display: grid; grid-template-columns: 170px 1fr 96px; gap: 12px; align-items: center; font-size: 13.5px; }
.flow .t { height: 10px; background: var(--subtle); border-radius: 5px; position: relative; }
.flow .t i { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 5px; }
.flow .t i.b { background: var(--buy); } .flow .t i.s { background: var(--sell); }
.flow .a { text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; }
.phone { width: 390px; }
.phone .wrap { padding: 0 12px 24px; }
.phone .grid2 { grid-template-columns: 1fr; }
.phone .tiles { grid-template-columns: 1fr 1fr; }
.phone .mtop { gap: 10px; padding: 0 12px; }
.phone .mtop nav, .phone .mtop .search { display: none; }
.phone .idea > summary { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.phone .idea-co { grid-column: 1 / -1; } .phone .idea .kv { text-align: left; }
"""

BANNER = ('<div class="banner"><b>Layout mock.</b> Every row is a real NSE filing from the repo\'s test fixtures. '
          'Figures with a <span class="ph">dotted underline</span> (market cap, price, 52-week range, paid vs now) are '
          'placeholders: market data is not reachable from this session. The live site fills them from the price layer.</div>')

# Placeholders for market data (sym -> size, market cap Cr, price, position in 52-week range 0-100)
PH = {'HCLTECH': ('Large', 410000, 1510, 58), 'ZEEL': ('Mid', 11800, 118, 44), 'ADANIENT': ('Large', 285000, 2480, 71),
      'EPL': ('Small', 9200, 292, 35), 'SPECTRUM': ('Small', 2400, 2050, 82), 'BHARATFORG': ('Mid', 62000, 1330, 30),
      'MARINE': ('Micro', 480, 118, 22), 'FERMENTA': ('Micro', 620, 255, 18), 'KAPSTON': ('Small', 1650, 142, 64),
      'AXISCADES': ('Small', 3100, 690, 77), 'TREJHARA': ('Micro', 520, 224, 52), 'KRSNAA': ('Small', 2150, 604, 49),
      'UNIHEALTH': ('Small', 1350, 541, 61), 'KMEW': ('Small', 2450, 1760, 27), 'AGARALTUF': ('Micro', 410, 118, 55),
      'VISASTEEL': ('Small', 980, 36, 20), 'AMBEY': ('Micro', 150, 52, 40), 'ICEMAKE': ('Micro', 380, 0, 50),
      'SBIN': ('Large', 760000, 880, 80), 'ICICIBANK': ('Large', 980000, 1380, 66), 'LT': ('Large', 520000, 3720, 70),
      'HDFCBANK': ('Large', 1450000, 1880, 60), 'ITC': ('Large', 540000, 430, 33), 'MOTILALOFS': ('Mid', 52000, 870, 74),
      'TDPOWERSYS': ('Small', 21000, 690, 83), 'INOXGREEN': ('Small', 6200, 142, 29), 'LLOYDSME': ('Mid', 80000, 1480, 55)}


def cr(v):
    return kit.rupees(v)


def ph(t):
    return f'<span class="ph" title="Placeholder: filled from the price layer in the live site">{esc(str(t))}</span>'


def mc_text(cr_value):
    return f'₹{cr_value / 1e5:.1f} L Cr' if cr_value >= 1e5 else f'₹{cr_value:,.0f} Cr'


def mkt(sym, size=True):
    s = PH.get(sym)
    if not s:
        return ''
    sz, mc, px, pos = s
    bits = [ph(sz)] if size else []
    bits.append(ph(mc_text(mc)))
    if px:
        bits.append(ph(f'₹{px:,}'))
    bits.append(f'<span class="rgm ph"><i style="left:{pos}%"></i></span>')
    return '<span class="mk">' + ' · '.join(bits[:-1]) + ' ' + bits[-1] + '</span>'


def co(name, sym, extra=''):
    return (f'<a href="#">{esc(name)}</a><div class="sub"><span class="sym">{esc(sym)}</span>'
            f'{mkt(sym)}{extra}</div>')


def vs_now(paid, sym, side='BUY'):
    s = PH.get(sym)
    if not s or not s[2] or not paid:
        return '<span class="na">—</span>'
    m = (s[2] / paid - 1) * 100
    tone = ('up' if m >= 0 else 'down') if side == 'BUY' else ''     # after a sale the sign says nothing good or bad: no colour
    return f'<span class="{tone} num ph">{m:+.1f}%</span>'


def page(active, body, title, width=None, phone=False, banner=True):
    nav = ''.join(f'<a class="{"on" if n == active else ""}" href="#">{n}</a>' for n in ('Today', 'Companies', 'Filings', 'Evidence'))
    top = f'<div class="mtop"><span class="brand">Insiders</span><nav>{nav}</nav><span class="search">Search a company</span></div>'
    return (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=Geist+Mono:wght@400;500&display=swap" rel="stylesheet">'
            f'<title>{esc(title)}</title><style>{CSS}{MOCK_CSS}</style></head><body class="{"phone" if phone else ""}">'
            f'{BANNER if banner else ""}{top}<div class="wrap">{body}</div></body></html>')


def head(t, s):
    return f'<div class="head"><h1>{esc(t)}</h1><p>{esc(s)}</p></div>'


def pills(label, items, on):
    items = [i.split('|')[0] if i.split('|')[0] != on else i for i in items]   # a count only where it is the page's own
    return ('<div class="pills">' + (f'<span class="lbl">{label}</span>' if label else '') +
            ''.join(f'<span class="p{" on" if i == on else ""}">{esc(i.split("|")[0])}' +
                    (f'<small>{i.split("|")[1]}</small>' if '|' in i else '') + '</span>' for i in items) + '</div>')


def tiles(items):
    return '<section class="tiles">' + ''.join(
        f'<div class="tile"><span class="k">{esc(k)}</span><span class="v num {tone}">{esc(v)}</span><span class="s">{esc(s)}</span></div>'
        for k, v, s, tone in items) + '</section>'


def chip(t, tone='mute'):
    return f'<span class="chip {tone}">{esc(t)}</span>'


def idea(name, sym, sentence, chips, kvs, size=True):
    kv = ''.join(f'<div class="kv"><span>{esc(k)}</span><b class="{c}">{v}</b></div>' for k, v, c in kvs)
    return (f'<details class="idea"><summary><div class="idea-co"><a href="#">{esc(name)}</a>'
            f'<div class="co2"><span class="sym">{esc(sym)}</span>{mkt(sym, size)}</div>'
            f'<p class="hl">{sentence}</p><div class="idea-chips">{"".join(chips)}</div></div>{kv}</summary></details>')


def card(title, aside, inner):
    return f'<div class="mcard"><div class="card-h"><h2>{esc(title)}</h2><span>{esc(aside)}</span></div>{inner}</div>'


def table(head_cells, rows, wrap_style='max-height:none'):
    th = ''.join(f'<th class="{"r" if r else ""}">{esc(h)}</th>' for h, r in head_cells)
    return (f'<div class="tbl-wrap" style="{wrap_style}"><table class="tbl"><thead><tr>{th}</tr></thead><tbody>' +
            ''.join('<tr>' + ''.join(f'<td class="{c}">{v}</td>' for v, c in r) + '</tr>' for r in rows) + '</tbody></table></div>')


T = md.trades
HB = [t for t in T if t['sym'] == 'HCLTECH' and t['side'] == 'BUY']
HS = [t for t in T if t['sym'] == 'HCLTECH' and t['side'] == 'SELL']
hb_val, hb_qty = sum(t['value'] for t in HB), sum(t['qty'] for t in HB)
hs_val = sum(t['value'] for t in HS)
zee = next(t for t in T if t['sym'] == 'ZEEL')
S_ = {(s['sym'], s['who']): s for s in md.sast}


def sast_sentence(s, verb):
    return (f'{esc(s["who"])} {verb} <b>{s["pct"]:.2f}%</b> of the company ({kit.shares(s["shares"])} shares) '
            f'in the open market; its stake is now <b>{s["after"]:.2f}%</b>.')


# =====================================================================================================
# 1. TODAY: the money board
# =====================================================================================================
def titled(n):
    return n.title() if n.isupper() or n.startswith('MR. ') else n


def today(phone=False):
    adani = next(s for s in md.sast if s['sym'] == 'ADANIENT')
    epl = next(s for s in md.sast if s['sym'] == 'EPL')
    marine = next(s for s in md.sast if s['sym'] == 'MARINE')
    ferm = next(s for s in md.sast if s['sym'] == 'FERMENTA')
    kap = next(s for s in md.sast if s['sym'] == 'KAPSTON')
    axis = next(s for s in md.sast if s['sym'] == 'AXISCADES')
    spec_ls, spec_ip = md.ls['SPECTRUM'][0], md.ip['SPECTRUM']
    kr = md.ip['KRSNAA']
    bf = next(q for q in md.qips if q['sym'] == 'BHARATFORG')
    cash = spec_ls['raised'] + bf['amount'] + kr['approved']
    tl = tiles([
        ('Insiders buying', '1 company', f'{cr(zee["value"])} bought in the open market', 'up'),
        ('Promoters selling', '3 companies', 'Stake sales of 3-4% of the company, filed under Reg 29', 'down'),
        ('Cash into companies', '3 issues', f'{cr(cash)} from funds, institutions and promoters (one approved, two raised)', ''),
        ('Big holders and funds', '2 in · 1 out', 'Reg 29 filings: the stake after is on each row', ''),
        ('Pledges', '0 up', '2 released: Vintage Coffee and Lloyds Engineering', ''),
    ])
    bar = ('<div class="bar">' + pills('Period', ['Today', '7 days', '30 days', '90 days', '6 months'], '6 months') + TOG_ON +
           pills('', ['All|7', 'Insiders', 'Promoter and fund cash', 'Big holders', 'Raises', 'Pledges', 'Buybacks'], 'All') +
           '<span class="filt">Size ▾</span><span class="filt">Sector ▾</span></div>')
    ev = lambda t: chip(t, 'ev')  # noqa: E731
    ins = [
        idea('Zee Entertainment Enterprises', 'ZEEL',
             f'<b>Shreyasi Goenka</b>, a promoter\'s relative, bought <b>{cr(zee["value"])}</b> ({kit.shares(zee["qty"])} shares) at '
             f'<b>₹{zee["price"]:,.2f}</b>, adding <b>{zee["hold_pct"]:.1f}%</b> to her own holding.',
             [chip('Promoter group', 'acc'), chip('Open market', 'buy'), ev('Early read: ahead')],
             [('Value', cr(zee['value']), ''), ('Own holding', f'+{zee["hold_pct"]:.1f}%', 'up'), ('Paid vs now', vs_now(zee['price'], 'ZEEL'), '')]),
        idea('Krsnaa Diagnostics', 'KRSNAA',
             f'<b>Promoters</b> will pay <b>{cr(kr["approved"])}</b> in cash for {kit.shares(kr["proposed"])} warrants, '
             f'at the ICDR minimum <b>₹{kr["icdr"]:,.2f}</b> (<b>Krsna Diagnostics (Mumbai)</b> takes 15,46,000 of them).',
             [chip('Preferential · approved', 'acc'), chip('Promoters pay cash', 'buy'), ev('Early read: ahead')],
             [('Amount', cr(kr['approved']), ''), ('ICDR minimum', f'₹{kr["icdr"]:,.2f}', ''), ('Minimum vs now', vs_now(kr['icdr'], 'KRSNAA'), '')]),
        idea('Adani Enterprises', 'ADANIENT',
             f'Emerging Market Investment FZCO, a promoter-group holder, bought <b>{adani["pct"]:.2f}%</b> of the company '
             f'({kit.shares(adani["shares"])} shares) in the open market; its stake is now <b>{adani["after"]:.2f}%</b>.',
             [chip('Stake change · Reg 29(2)', 'acc'), chip('Promoter group', 'acc'), chip('Room to the 75% cap: 3.0 pts', 'mute')],
             [('Of company', '+1.46%', 'up'), ('Stake after', f'{adani["after"]:.2f}%', ''), ('Value', '≈ ' + ph('₹3,500 Cr'), '')]),
        idea('EPL', 'EPL', sast_sentence(epl, 'bought'),
             [chip('Fund', 'acc'), chip('Stake change · Reg 29(2)', 'acc')],
             [('Of company', f'+{epl["pct"]:.2f}%', 'up'), ('Stake after', f'{epl["after"]:.2f}%', ''), ('Value', '≈ ' + ph('₹17 Cr'), '')]),
        idea('Spectrum Electrical Industries', 'SPECTRUM',
             f'Preferential issue: <b>HDFC Mutual Fund schemes</b>, a Category III AIF and others took '
             f'<b>{kit.shares(spec_ls["shares"])} shares at ₹{spec_ls["price"]:,.0f}</b>, against the ICDR minimum '
             f'₹{spec_ip["icdr"]:,.2f}; <b>{cr(spec_ls["raised"])}</b> raised.',
             [chip('Preferential', 'acc'), chip('Funds named', 'buy'), chip('At the minimum price', 'mute')],
             [('Raised', cr(spec_ls['raised']), ''), ('Offer vs minimum', f'+{(spec_ls["price"] / spec_ip["icdr"] - 1) * 100:.2f}%', ''), ('Offer vs now', vs_now(spec_ls['price'], 'SPECTRUM'), '')]),
        idea('Bharat Forge', 'BHARATFORG',
             f'QIP: <b>{bf["allottees"]} institutions</b> took <b>{kit.shares(bf["shares"])} shares at ₹{bf["price"]:,.0f}</b>; '
             f'<b>{cr(bf["amount"])}</b> raised.',
             [chip('QIP', 'acc'), chip(f'{bf["allottees"]} allottees', 'mute')],
             [('Raised', cr(bf['amount']), ''), ('Issue price', f'₹{bf["price"]:,.0f}', ''), ('Issue vs now', vs_now(bf['price'], 'BHARATFORG'), '')]),
    ]
    outs = [
        idea('Marine Electricals (India)', 'MARINE', sast_sentence(marine, 'sold').replace('KDU Enterprises Private Limited', 'KDU Enterprises, a promoter-group holder,'),
             [chip('Promoter group sale', 'sell'), chip('Stake change · Reg 29(2)', 'acc')],
             [('Of company', f'−{marine["pct"]:.2f}%', 'down'), ('Stake after', f'{marine["after"]:.2f}%', ''), ('Value', '≈ ' + ph('₹14 Cr'), '')]),
        idea('Fermenta Biotech', 'FERMENTA', sast_sentence(ferm, 'sold'),
             [chip('Promoter group sale', 'sell'), chip('Stake change · Reg 29(2)', 'acc')],
             [('Of company', f'−{ferm["pct"]:.2f}%', 'down'), ('Stake after', f'{ferm["after"]:.2f}%', ''), ('Value', '≈ ' + ph('₹30 Cr'), '')]),
        idea('Kapston Services', 'KAPSTON', sast_sentence(dict(kap, who=titled(kap['who'])), 'sold'),
             [chip('Promoter group sale', 'sell'), chip('Stake change · Reg 29(2)', 'acc')],
             [('Of company', f'−{kap["pct"]:.2f}%', 'down'), ('Stake after', f'{kap["after"]:.2f}%', ''), ('Value', '≈ ' + ph('₹58 Cr'), '')]),
        idea('Axiscades Technologies', 'AXISCADES', sast_sentence(axis, 'sold') + ' It is not a promoter.',
             [chip('Big holder out', 'sell'), chip('Not a promoter', 'mute')],
             [('Of company', f'−{axis["pct"]:.2f}%', 'down'), ('Stake after', f'{axis["after"]:.2f}%', ''), ('Value', '≈ ' + ph('₹340 Cr'), '')]),
    ]
    out_note = ('<p class="note">Left out with "Real money only" on: 21 HCL Technologies employees selling ₹16.7 Cr in all, because '
                'no one of them reaches 0.05% of the company. They stay in Filings.</p>')
    coming = card('Coming up: money events', 'fund raising, buybacks, tenders, lock-ins · next 10 days', table(
        [('Date', False), ('Company', False), ('What', False), ('Detail', False)],
        [(('9 Oct 2026', 'd'), (co('CP Capital', 'CPCAP'), 'co'), ('Board meets: fund raising', ''), ('As intimated to NSE', 'd')),
         (('10 Oct 2026', 'd'), (co('Akme Fintrade (India)', 'AFIL'), 'co'), ('Board meets: fund raising', ''), ('As intimated to NSE', 'd')),
         (('10 Oct 2026', 'd'), (co('Trejhara Solutions', 'TREJHARA'), 'co'), ('Lock-in ends: equity allottees', ''), ('6 months from trading approval on 10 Apr (the rule; filing lines not read yet)', 'd')),
         (('13 Oct 2026', 'd'), (co('Hitech Corporation', 'HITECHCORP'), 'co'), ('Delisting tender closes', ''), ('Reverse book building, floor ₹252, opened 7 Oct', 'd'))],
        'max-height:none'))
    body = (head('Today', 'Where real money moved: insiders buying and selling, cash into companies, funds and big holders in and out.')
            + '<div class="strip"><span><b>8 Oct 2026</b></span></div>' + bar + tl +
            '<div class="grid2">' + card('Money in', 'largest share of the company first', ''.join(ins)) +
            card('Money out', 'largest share of the company first', ''.join(outs) + out_note) + '</div>' + coming)
    return page('Today', body, 'Today: money board', phone=phone)


# =====================================================================================================
# 2. FILINGS: preferential issues, the deal ticket
# =====================================================================================================
def filings_pref():
    def amt(v, bad=False, note=''):
        if bad:
            return f'<span class="na">—</span><span class="qm" title="{esc(note, quote=True)}">?</span>'
        return cr(v)

    def posted(day, stage):
        return (f'{day}<div class="sub">{stage}</div>', 'd')

    DASH = ('<span class="na">—</span>', 'r')
    rows = []
    spec_l, spec_i = md.ls['SPECTRUM'][0], md.ip['SPECTRUM']
    rows.append((posted('6 Oct 2026', 'Listed · allotted 7 Oct'), (co('Spectrum Electrical Industries', 'SPECTRUM'), 'co'),
                 ('Promoters and others<div class="sub">HDFC MF ×3, Valuequest AIF, +2 · equity; warrants</div>', 'wrapc'),
                 (amt(spec_l['raised']) + f'<div class="sub">approved {cr(spec_i["approved"])}</div>', 'r num'),
                 (f'₹{spec_l["price"]:,.0f}', 'r num'), (f'₹{spec_i["icdr"]:,.2f}', 'r num'),
                 (f'<b>+{(spec_l["price"] / spec_i["icdr"] - 1) * 100:.2f}%</b>', 'r num'), (vs_now(spec_l['price'], 'SPECTRUM'), 'r'),
                 ('7 Apr 2027 · 7 Apr 2028<div class="sub">rule: others 6 mo · promoters 18 mo</div>', 'd wrapc')))
    kr = md.ip['KRSNAA']
    rows.append((posted('18 Aug 2026', 'Approved in principle'), (co('Krsnaa Diagnostics', 'KRSNAA'), 'co'),
                 ('<b>Promoters</b><div class="sub">Krsna Diagnostics (Mumbai) Pvt Ltd, +1 · warrants</div>', 'wrapc'),
                 (amt(kr['approved']) + '<div class="sub">cash</div>', 'r num'), ('—', 'r na'), (f'₹{kr["icdr"]:,.2f}', 'r num'), DASH, DASH, ('<span class="na">—</span>', 'd wrapc')))
    tr_l, tr_i = md.ls['TREJHARA'][0], md.ip['TREJHARA']
    rows.append((posted('9 Apr 2026', 'Listed · allotted 10 Feb'), (co('Trejhara Solutions', 'TREJHARA'), 'co'),
                 ('Promoters and others<div class="sub">Prakash Shah, +16 · equity; warrants</div>', 'wrapc'),
                 (amt(tr_l['raised']) + f'<div class="sub">approved {cr(tr_i["approved"])}</div>', 'r num'), (f'₹{tr_l["price"]:,.0f}', 'r num'),
                 (f'₹{tr_i["icdr"]:,.2f}', 'r num'), (f'<b>+{(tr_l["price"] / tr_i["icdr"] - 1) * 100:.2f}%</b>', 'r num'), (vs_now(tr_l['price'], 'TREJHARA'), 'r'),
                 ('10 Oct 2026 · 10 Apr 2027<div class="sub">rule: others 6 mo · promoters 18 mo</div>', 'd wrapc')))
    un_i = md.ip['UNIHEALTH']
    implied = un_i['proposed'] * un_i['icdr']
    rows.append((posted('25 Aug 2026', 'Approved in principle'), (co('Unihealth Hospitals', 'UNIHEALTH'), 'co'),
                 ('Non-promoters<div class="sub">Chirag Kotecha, Bhasker Kotecha · swap of shares</div>', 'wrapc'),
                 (amt(0, True, f'Filed amount {cr(65038750000000)} is above the ₹1 lakh Cr ceiling and 1 lakh times shares × ICDR minimum ({cr(implied)}); held back, not shown.') +
                  f'<div class="sub">shares × minimum {cr(implied)}</div>', 'r num'), ('—', 'r na'), (f'₹{un_i["icdr"]:,.2f}', 'r num'), DASH, DASH, ('<span class="na">—</span>', 'd wrapc')))
    kmew = md.ls['KMEW'][0]
    rows.append((posted('11 Dec 2025', 'Listed · allotted 30 Oct'), (co('Knowledeg Marine & Engineering Works', 'KMEW'), 'co'),
                 ('<span class="na">not matched to its approval</span>', 'wrapc'), (amt(kmew['raised']), 'r num'),
                 (f'₹{kmew["price"]:,.0f}', 'r num'), ('—', 'r na'), DASH, (vs_now(kmew['price'], 'KMEW'), 'r'),
                 ('Ended 12 Jun 2026<div class="sub">filed: equity shares for 6 months</div>', 'd wrapc')))
    ag = md.ls['AGARALTUF'][0]
    rows.append((posted('11 Sep 2026', 'Listed · allotted 11 Sep'), (co('Agarwal Toughened Glass India', 'AGARALTUF'), 'co'),
                 ('<span class="na">not matched to its approval</span>', 'wrapc'),
                 (amt(0, True, f'Filed amount {cr(ag["raised"])} is 1 lakh times shares × price ({cr(ag["shares"] * ag["price"])}); held back, not shown.') +
                  f'<div class="sub">shares × price {cr(ag["shares"] * ag["price"])}</div>', 'r num'), (f'₹{ag["price"]:,.0f}', 'r num'), ('—', 'r na'), DASH,
                 (vs_now(ag['price'], 'AGARALTUF'), 'r'), ('<span class="na">—</span>', 'd wrapc')))
    rows.append((posted('28 Sep 2026', 'Listed'), ('<a href="#">ICE Make Refrigeration</a><div class="sub"><span class="sym">ICEMAKE</span></div>', 'co'),
                 ('<span class="na">not matched to its approval</span>', 'wrapc'),
                 (amt(0, True, 'Filed amount fails the unit check (shown as ₹1,90,00,010 Cr on the old Capital raises page); held back, not shown.') +
                  '<div class="sub">shares allotted 23,67,573</div>', 'r num'), ('—', 'r na'), ('—', 'r na'), DASH, DASH, ('—', 'd wrapc')))
    th = [('Posted', False), ('Company', False), ('Shares go to', False), ('Amount', True), ('Offer price', True), ('ICDR minimum', True),
          ('Offer vs minimum', True), ('Offer vs now', True), ('Lock-in ends', False)]
    body = (head('Filings', 'Every filing and deal, one kind at a time.') +
            '<div class="bar">' + pills('', ['All', 'Insider trades', 'Deals', 'Stake changes', 'Preferential|7', 'Rights', 'QIPs', 'Buybacks', 'Pledges', 'Upcoming'], 'Preferential') +
            '</div><div class="bar"><span class="filt" style="width:240px;color:#8a93a3">Company, symbol or name</span>' +
            pills('', ['30 days', '90 days', '1 year'], '1 year') + '<span class="filt">Filters &amp; sort ▾</span>' + TOG_ON + '</div>' + table(th, rows) +
            '<div class="leg"><span><span class="qm" style="margin:0">?</span> Amount held back: the filed figure fails the unit check; shares × price shown instead</span>'
            '<span><b>Bold</b> offer vs minimum: priced within 1% of the ICDR floor</span><span>Click a row for allottees, terms, lock-in lines and the filing</span></div>')
    return page('Filings', body, 'Filings: preferential issues')


# =====================================================================================================
# 3. FILINGS: insider trades
# =====================================================================================================
def filings_insider():
    rows = []
    shown = [t for t in T if t['sym'] == 'ZEEL' or (t['sym'] == 'HCLTECH' and (t['side'] == 'BUY' or t['value'] >= 3.0e6))]
    shown.sort(key=lambda t: (t['public'], t['value']), reverse=True)
    shown = shown[:13]
    names = {'ZEEL': 'Zee Entertainment Enterprises', 'HCLTECH': 'HCL Technologies'}
    for t in shown:
        lag = (t['public'] - t['traded']).days
        role = {'Designated Person': 'Designated person', 'Promoter': 'Promoter group', 'Immediate Relative': "Promoter's relative"}.get(t['role'], t['role'])
        tags = ''
        if lag > 14:
            tags += kit.tag(f'Filed {lag} days late', 'warn')
        if t['role'] == 'Promoter':
            tags += kit.tag('Promoter', 'warn')
        lag_txt = 'same day' if lag == 0 else f'{lag} day' + ('' if lag == 1 else 's')
        rows.append(((t['public'].strftime('%-d %b %Y'), 'd'), (co(names[t['sym']], t['sym']), 'co'),
                     (f'{esc(titled(t["who"]))}<div class="sub">{role}</div>', 'who'), (kit.side_tag(t['side']), ''), (cr(t['value']), 'r num'),
                     (f'₹{t["price"]:,.2f}', 'r num'), (vs_now(t['price'], t['sym'], t['side']), 'r'),
                     (f'<span class="{"up" if t["hold_pct"] >= 0 else "down"} num">{t["hold_pct"]:+.2f}%</span>' if abs(t['hold_pct']) >= 0.01 else
                      f'<span class="num">{t["hold_pct"]:+.3f}%</span>', 'r'),
                     (f'{t["traded"].strftime("%-d %b")} → {t["public"].strftime("%-d %b")}<div class="sub">{lag_txt}</div>', 'd'), (tags, 'tags')))
    th = [('Made public', False), ('Company', False), ('Who', False), ('Side', False), ('Value', True), ('Price paid or got', True),
          ('Price now vs trade', True), ('Own holding Δ', True), ('Traded → public', False), ('Flags', False)]
    ex_h = {}
    for t in md.pit:
        if t['symbol'] == 'HCLTECH':
            ex_h[t['modeOfAcquisition']] = ex_h.get(t['modeOfAcquisition'], 0) + 1
    body = (head('Filings', 'Every filing and deal, one kind at a time.') +
            '<div class="bar">' + pills('', ['All', 'Insider trades', 'Deals', 'Stake changes', 'Preferential', 'Rights', 'QIPs', 'Buybacks', 'Pledges', 'Upcoming'], 'Insider trades') +
            '</div><div class="bar"><span class="filt" style="width:240px;color:#8a93a3">Company, symbol or name</span>' +
            pills('', ['7 days', '30 days', '90 days', '1 year'], '1 year') + pills('Side', ['Buy and sell', 'Buy', 'Sell'], 'Buy and sell') +
            '<span class="filt">Filters &amp; sort ▾</span>' + TOG_OFF + '</div>' + table(th, rows) +
            f'<div class="leg"><span>Real money only is off here. With it on, HCL Technologies drops out: even ₹81.9 Cr by its promoter group is about '
            f'0.02% of the company (at the placeholder market cap), under the 0.05% floor.</span>'
            f'<span>Open-market trades only; at HCL in this sample {ex_h.get("ESOS", 0)} ESOS exercises, {ex_h.get("Gift", 0)} gifts and '
            f'{ex_h.get("ESOP", 0) + ex_h.get("Preferential Offer", 0) + ex_h.get("Off Market", 0)} other non-market filings stay under "All".</span>'
            f'<span>Colour on "price now vs trade" only for buys: after a sale a rise is neither good nor bad news.</span></div>')
    return page('Filings', body, 'Filings: insider trades')


# =====================================================================================================
# 4. COMPANIES: screener-style list
# =====================================================================================================
def companies():
    H = md.holders
    nets = {}
    for t in T:
        nets.setdefault(t['sym'], 0)
        nets[t['sym']] += t['value'] if t['side'] == 'BUY' else -t['value']
    order = ['HCLTECH', 'ZEEL', 'TDPOWERSYS', 'MOTILALOFS', 'SBIN', 'ICICIBANK', 'HDFCBANK', 'LT', 'ITC']
    names = {'HCLTECH': 'HCL Technologies', 'ZEEL': 'Zee Entertainment Enterprises', 'TDPOWERSYS': 'TD Power Systems', 'MOTILALOFS': 'Motilal Oswal Financial Services',
             'SBIN': 'State Bank of India', 'ICICIBANK': 'ICICI Bank', 'HDFCBANK': 'HDFC Bank', 'LT': 'Larsen & Toubro', 'ITC': 'ITC'}
    rows = []
    P = lambda x: f'{x:.1f}%' if x is not None else '<span class="na">—</span>'  # noqa: E731
    for s in order:
        h = H.get(s)
        pr = h.get('promoter_pct') if h else None
        net = nets.get(s)
        sig = ''
        if s == 'HCLTECH':
            sig = kit.tag('Promoter buying', 'buy')
        if s == 'ZEEL':
            sig = kit.tag('Promoter group buying', 'buy')
        if h and h.get('promoter_pct') == 0:
            sig += kit.tag('No promoter group', 'mute')
        rows.append(((co(names[s], s), 'co'),
                     (f'{pr:.1f}%' if pr else ('<span class="na">—</span>' if not h else '<span class="na">0</span>'), 'r num'),
                     (P(h.get('mf_pct')) if h else P(None), 'r num'), (P(h.get('fpi_pct')) if h else P(None), 'r num'),
                     (P(h.get('insurance_pct')) if h else P(None), 'r num'), (P(h.get('retail_pct')) if h else P(None), 'r num'),
                     (f'<span class="{"up" if net > 0 else "down"} num">{cr(net).replace("₹", "+₹") if net > 0 else cr(net)}</span>' if net is not None else '<span class="na">—</span>', 'r'),
                     (sig or '<span class="na">—</span>', 'tags'), (h['q'] if h else '—', 'd')))
    th = [('Company', False), ('Promoters', True), ('Mutual funds', True), ('FPIs', True), ('Insurers', True), ('Retail', True),
          ('Insiders, net', True), ('Signals', False), ('Filed quarter', False)]
    body = (head('Companies', 'Who owns them, who is buying and selling, in one sortable list. Click a company for its page.') +
            '<div class="bar"><span class="filt" style="width:240px;color:#8a93a3">Company, symbol or name</span>' +
            pills('Size', ['All', 'Large', 'Mid', 'Small', 'Micro'], 'All') + '<span class="filt">Sector ▾</span><span class="filt">Filters &amp; sort ▾</span></div>' +
            table(th, rows) +
            '<div class="leg"><span>Ownership by investor type is read from each company\'s own shareholding XBRL (real, from the fixtures). '
            '"Insiders, net": open-market buys minus sells in the sample window. Columns for quarter-on-quarter change, pledge, dilution and 52-week range '
            'fill from tables the live site holds.</span></div>')
    return page('Companies', body, 'Companies list')


# =====================================================================================================
# 5. COMPANY page (HCL Technologies)
# =====================================================================================================
def company():
    px = PH['HCLTECH']
    ratios = ('<div class="ratios">'
              f'<div><span class="k">Market cap</span><span class="v">{ph(kit.rupees(px[1] * 1e7))}</span><span class="s">{ph(px[0] + " cap")}</span></div>'
              f'<div><span class="k">Price</span><span class="v">{ph("₹%s" % f"{px[2]:,}")}</span><span class="s">52-week range <span class="rgm ph" style="width:70px"><i style="left:{px[3]}%"></i></span></span></div>'
              f'<div><span class="k">Promoter group</span><span class="v up">+{cr(hb_val)}</span><span class="s">{len(HB)} open-market filings</span></div>'
              f'<div><span class="k">Designated persons</span><span class="v down">−{cr(hs_val)}</span><span class="s">{len(HS)} filings · {len({t["who"] for t in HS})} people</span></div>'
              f'<div><span class="k">Promoters hold</span><span class="v"><span class="na">—</span></span><span class="s">from shareholding (not in the fixtures)</span></div>'
              f'<div><span class="k">Pledged</span><span class="v"><span class="na">—</span></span><span class="s">from shareholding and Reg 31</span></div></div>')
    mx = max(hb_val, hs_val)
    flow = card('Money in and out', '6 months, open market, each rupee once', (
        '<div class="flow">'
        f'<div class="r"><span>Promoter group<div class="sub">Vama Sundari Investments</div></span><span class="t"><i class="b" style="width:{hb_val / mx * 100:.0f}%"></i></span><span class="a up">+{cr(hb_val)}</span></div>'
        f'<div class="r"><span>Designated persons<div class="sub">{len({t["who"] for t in HS})} people</div></span><span class="t"><i class="s" style="width:{hs_val / mx * 100:.0f}%"></i></span><span class="a down">−{cr(hs_val)}</span></div>'
        f'<div class="r"><span><b>Net</b></span><span></span><span class="a up">+{cr(hb_val - hs_val)}</span></div></div>'))
    # decision dots by date
    from datetime import date as D
    t0, t1 = D(2026, 4, 20), D(2026, 10, 1)
    w, h = 640, 120
    x = lambda dt: 20 + (dt - t0).days / (t1 - t0).days * (w - 40)  # noqa: E731
    vmax = max(t['value'] for t in HB + HS)
    dots = ''
    for t in HB + HS:
        r = 4 + (t['value'] / vmax) ** .5 * 12
        dots += f'<circle cx="{x(t["public"]):.1f}" cy="{h / 2 + (-18 if t["side"] == "BUY" else 18)}" r="{r:.1f}" fill="{"#0F7B4F" if t["side"] == "BUY" else "#B42318"}" fill-opacity=".75"><title>{esc(t["who"])} {t["side"]} {cr(t["value"])}</title></circle>'
    months = ''.join(f'<text x="{x(D(2026, m, 1)):.0f}" y="{h - 4}" font-size="10" fill="#5E6878">{n}</text><line x1="{x(D(2026, m, 1)):.0f}" x2="{x(D(2026, m, 1)):.0f}" y1="6" y2="{h - 16}" stroke="#EEF0F4"/>'
                     for m, n in ((5, 'May'), (6, 'Jun'), (7, 'Jul'), (8, 'Aug'), (9, 'Sep')))
    svg = (f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}">{months}<line x1="20" x2="{w - 20}" y1="{h / 2}" y2="{h / 2}" stroke="#DCE0E6"/>{dots}</svg>')
    chart = card('Decisions on a timeline', '▲ bought above, sold below, sized by value · the price line draws here from the price layer', svg)
    rows = []
    feed = sorted(HB + HS, key=lambda t: t['value'], reverse=True)[:11]
    for t in feed:
        lag = (t['public'] - t['traded']).days
        rows.append(((t['public'].strftime('%-d %b %Y'), 'd'), (kit.side_tag(t['side']) + ' insider', ''),
                     (f'{esc(titled(t["who"]))}<div class="sub">{"Promoter group" if t["role"] == "Promoter" else "Designated person"}</div>', 'who'),
                     (f'{"bought" if t["side"] == "BUY" else "sold"} {kit.shares(t["qty"])} shares at ₹{t["price"]:,.2f}', ''), (cr(t['value']), 'r num'),
                     (f'<span class="{"up" if t["hold_pct"] >= 0 else "down"} num">{t["hold_pct"]:+.2f}%</span>', 'r'),
                     (('same day' if lag == 0 else f'{lag} day' + ('' if lag == 1 else 's') + ' after the trade'), 'd')))
    tl = card('Everything filed', 'largest first (newest first on a tap) · a row opens to its facts and the filing link', table(
        [('Made public', False), ('Filing', False), ('Who', False), ('What', False), ('Value', True), ('Own holding Δ', True), ('Lag', False)], rows))
    hd = ('<div class="head"><h1>HCL Technologies <span class="sym" style="font-size:14px;font-weight:500">HCLTECH</span> '
          '<span class="ex ex-nse">NSE</span></h1><p>Money story of one stock: who put money in or took it out, at what price, and what is ahead.</p></div>')
    body = hd + ratios + f'<div class="grid2">{flow}{chart}</div>' + tl
    return page('Companies', body, 'Company: HCL Technologies')


pages = {'01_today_money_board': today(), '02_filings_preferential': filings_pref(), '03_filings_insider_trades': filings_insider(),
         '04_companies_list': companies(), '05_company_page': company(), '06_today_phone': today(phone=True)}
for k, v in pages.items():
    (OUT / f'{k}.html').write_text(v)
print('built', list(pages))
