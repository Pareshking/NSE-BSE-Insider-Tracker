"""Fund houses and where each publishes its month-end portfolio (pages from AMFI's Portfolio Disclosure list,
www.amfiindia.com/online-center/portfolio-disclosure, read 19 Nov 2026). Checked one by one against the October and
September 2026 files; a house not here is not collected, and the Funds page says how much of the industry is covered."""
from __future__ import annotations

import calendar
from datetime import date

from collectors.mf_portfolios import apis, apis2
from collectors.mf_portfolios.find import UA, House

_YEAR = date.today().year
_FY = _YEAR if date.today().month >= 4 else _YEAR - 1     # Indian financial year (April to March) it starts in


def _trust(month: str) -> list[tuple[str, str]]:
    """TRUST MF lists its disclosures from a JSON query (the page draws them from it): every monthly portfolio filed."""
    import requests
    r = requests.post('https://www.trustmf.com/api/api/Trust/GetData', timeout=60, headers={'User-Agent': UA},
                      json={'systemQueryFileName': 'disclosuresweb.xml', 'tagName': 'GetDisclosureByType', 'searchField': '',
                            'searchValue': '', 'sortField': 'uploaddate', 'sortDirection': 'DESC', 'replaceField': '_slug_',
                            'replaceValue': 'portfolio-monthly-disclosure'})
    r.raise_for_status()
    return [(d.get('title') or '', d.get('fileurl') or '') for d in r.json().get('resultSetArray') or []]


def _choice(month: str) -> list[tuple[str, str]]:
    """Choice MF draws its list from a JSON endpoint; the files sit on doc.choicemf.com (the page's own script joins them)."""
    import requests
    r = requests.post('https://choicemf.com/api/monthly-portfolio-report/portfolio-website-list', json={}, timeout=60,
                      headers={'User-Agent': UA})
    r.raise_for_status()
    return [(f"{s.get('scheme_name')} monthly portfolio {d.get('report_date')}",
             'https://doc.choicemf.com/' + str(d.get('file_path')).lstrip('/'))
            for s in (r.json().get('body') or {}).get('data') or [] for d in s.get('reports') or [] if d.get('file_path')]


def _wealthco(month: str) -> list[tuple[str, str]]:
    """The Wealth Company: the page's script data holds each file's name (scheme and date) and its upload address,
    newest first (the first 25, about two months); the visible links are buttons without addresses."""
    import re
    import requests
    page = 'https://www.wealthcompanyamc.in/literature-forms/portfolio-documents/monthly/'
    r = requests.get(page, timeout=60, headers={'User-Agent': UA})
    r.raise_for_status()
    t = r.text.replace('\\"', '"')
    return [(name, 'https://www.wealthcompanyamc.in' + url) for name, url in
            re.findall(r'"name":"([^"]+)","download_category[^{}]*?"attachment":\{[^{}]*?"url":"(/uploads/[^"]+)"', t)]


def _zerodha(month: str) -> list[tuple[str, str]]:
    """Zerodha (now zerodhacasefunds.com): one workbook per scheme, named and addressed in the page's script data
    (names with spaces, which the plain reader's quoted-address scan does not take)."""
    import re
    import requests
    r = requests.get('https://www.zerodhacasefunds.com/resources/disclosures/portfolio-disclosures', timeout=60,
                     headers={'User-Agent': UA})
    r.raise_for_status()
    t = r.text.replace('\\"', '"')
    return re.findall(r'"name":"([^"]+)","url":"(https://[^"]+/portfolio-disclosures/[^"]+)"', t)


HOUSES = [
    House('sbi', 'SBI Mutual Fund', 'https://www.sbimf.com/portfolios', render=True, must=r'all[ -]schemes'),
    House('nippon', 'Nippon India Mutual Fund',
          'https://mf.nipponindiaim.com/investor-service/downloads/factsheet-portfolio-and-other-disclosures',
          must=r'monthly-portfolio'),
    House('absl', 'Aditya Birla Sun Life Mutual Fund', 'https://mutualfund.adityabirlacapital.com/forms-and-downloads/portfolio',
          render=True, must=r'monthly'),
    House('dsp', 'DSP Mutual Fund', 'https://www.dspim.com/mandatory-disclosures/portfolio-disclosures', must=r'month[_ -]?end'),
    House('ppfas', 'PPFAS Mutual Fund', 'https://amc.ppfas.com/downloads/portfolio-disclosure/', must=r'monthly'),
    House('barodabnp', 'Baroda BNP Paribas Mutual Fund', 'https://www.barodabnpparibasmf.in/downloads/monthly-portfolio-scheme',
          must=r'monthly'),
    House('hdfc', 'HDFC Mutual Fund', 'https://www.hdfcfund.com/statutory-disclosure/portfolio/monthly-portfolio',
          api=apis.hdfc, mode='all', must=r'^monthly ', base_exclude=False),
    House('axis', 'Axis Mutual Fund', 'https://www.axismf.com/statutory-disclosures', api=apis.axis,
          must=r'monthly portfolio'),
    House('uti', 'UTI Mutual Fund', 'https://www.utimf.com/downloads/consolidate-all-portfolio-disclosure', api=apis.uti,
          must=r'consolidated portfolio'),
    House('mirae', 'Mirae Asset Mutual Fund', 'https://www.miraeassetmf.co.in/downloads/portfolio', api=apis.mirae,
          mode='all', must=r'^portfolio details as on', base_exclude=False),
    House('motilal', 'Motilal Oswal Mutual Fund', 'https://www.motilaloswalmf.com/downloads/scheme-portfolio-details',
          render=True, must=r'scheme[ -_]portfolio[ -_]details?'),
    House('tata', 'Tata Mutual Fund', 'https://www.tatamutualfund.com/schemes-related/portfolio', render=True,
          must=r'monthly[ -_]portfolio'),
    House('groww', 'Groww Mutual Fund', 'https://growwmf.in/statutory-disclosure/portfolio', must=r'monthly'),
    House('quantum', 'Quantum Mutual Fund', 'https://www.quantumamc.com/portfolio/combined/-1/1/0/0', must=r'all funds'),
    House('shriram', 'Shriram Mutual Fund', 'https://www.shriramamc.in/investor-statutory-disclosures', must=r'monthly-portfolio'),
    House('nj', 'NJ Mutual Fund', 'https://downloads.njmutualfund.com/njmf_download.php?nme=127', mode='all',
          must=r'monthly[_ -]portfolio'),
    House('capitalmind', 'Capitalmind Mutual Fund', 'https://capitalmindmf.com/statutory-disclosures.html', mode='all',
          must=r'monthly_portfolio_disclosure'),
    House('oldbridge', 'Old Bridge Mutual Fund', 'https://oldbridgemf.com/statutory-disclosures.html', mode='all',
          must=r'_portfolio_', exclude=r'notice|overlap'),
    House('angelone', 'Angel One Mutual Fund', 'https://www.angelonemf.com/downloads', mode='all', must=r'monthly-portfolio'),
    House('abakkus', 'Abakkus Mutual Fund', 'https://www.abakkusmf.com/statutory-disclosures.html',
          must=r'/uploads/(?:\S*monthly_port|abakkus_mf_[a-z]+_\d\d_20\d\d)'),   # links in script data, names vary month to month
    House('jmf', 'JM Financial Mutual Fund', 'https://www.jmfinancialmf.com/downloads/Portfolio-Disclosure', render=True,
          mode='all', must=r'monthly portfolio',
          click=['select:1:Monthly Portfolio of Schemes'] + ['css=li.ant-pagination-next button'] * 12),   # 5 files a page
    House('boi', 'Bank of India Mutual Fund', 'https://www.boimf.in/investor-corner', render=True, must=r'monthly-portfolio',
          click=['MONTHLY PORTFOLIO']),
    House('iti', 'ITI Mutual Fund', 'https://www.itiamc.com/statuory-disclosure', render=True, must=r'/admin/pdf/\S*monthly_portfolio',
          click=['Portfolio Disclosures'] + [f"css=a[aria-label^='Download Monthly Portfolio'] >> nth={i}" for i in range(3)]),
          # the file's address is only fetched on a click (the links are javascript:void)
    # One month at a time on the page (the current financial year's): open the month list and pick each month in turn.
    House('jioblackrock', 'Jio BlackRock Mutual Fund',
          'https://www.jioblackrockamc.com/statutory-disclosure/disclosures/monthly-portfolio-disclosure', render=True,
          must=r'jioblackrock mutual fund-monthly-portfolio',
          click=[c for m in calendar.month_name[1:] for c in
                 ('css=span.ant-select-selection-item >> nth=1', f"css=div.ant-select-item-option[title='{m}']")]),
    House('trust', 'TRUST Mutual Fund', 'https://www.trustmf.com/disclosures?activeTab=portfolio-disclosures',
          must=r'monthly portfolio', api=_trust),
    # A year and a month at a time: this year's and last year's, each month in turn.
    House('taurus', 'Taurus Mutual Fund', 'https://taurusmutualfund.com/monthly-portfolio', render=True, mode='all',
          must=r'monthly_portfolio',
          click=[c for y in (_YEAR, _YEAR - 1) for c in [f'select:0:{y}'] + [f'select:1:{m}' for m in calendar.month_name[1:]]]),
    House('choice', 'Choice Mutual Fund', 'https://choicemf.com/disclosures/monthly-portfolio', mode='all', api=_choice),
    House('wealthco', 'The Wealth Company Mutual Fund', 'https://www.wealthcompanyamc.in/literature-forms/portfolio-documents/monthly/',
          mode='all', must=r'^monthly - ', api=_wealthco),
    House('samco', 'Samco Mutual Fund', 'https://www.samcomf.com/StatutoryDisclosure', mode='all',
          must=r'media\.samcomf\.com/\S*in_mf_monthly_portfolio'),   # each file is also linked via a redirect; keep one
    House('unifi', 'Unifi Mutual Fund', 'https://unifimf.com/statutorydocuments/', mode='all',
          must=r'/mp-unifi-|-monthly(?:-\d)?\.xlsx?'),
    House('zerodha', 'Zerodha Mutual Fund', 'https://www.zerodhacasefunds.com/resources/disclosures/portfolio-disclosures',
          mode='all', must=r'monthly portfolio', api=_zerodha),
    # Portfolio tab, then the Monthly Portfolio year and month lists (the 28th and 29th <select> on the page): this
    # financial year's and last year's, each month in turn; each pick draws that month's one file.
    House('bajaj', 'Bajaj Finserv Mutual Fund', 'https://www.bajajamc.com/downloads', render=True, must=r'monthly-portfolio',
          click=["css=a:text-is('Portfolio')"] + [c for fy in (_FY, _FY - 1) for c in
                 [f'select:27:{fy}-{(fy + 1) % 100:02d}'] + [f'select:28:{calendar.month_name[(i + 3) % 12 + 1]}' for i in range(12)]]),
    # Houses whose page draws its list from a service (collectors/mf_portfolios/apis2.py); `page` is where a person looks.
    House('franklin', 'Franklin Templeton Mutual Fund', 'https://www.franklintempletonindia.com/reports',
          must=r'monthly-portfolio', api=apis2.franklin),
    House('hsbc', 'HSBC Mutual Fund', apis2.HSBC, mode='all', exclude=r'additional-information', api=apis2.hsbc),
    House('canara', 'Canara Robeco Mutual Fund', apis2.CANARA, mode='all', api=apis2.canara),
    House('invesco', 'Invesco Mutual Fund', 'https://www.invescomutualfund.com/literature-forms/monthly-holdings/equity',
          mode='all', api=apis2.invesco),
    House('quant', 'quant Mutual Fund', 'https://quantmutual.com/statutory-disclosures', must=r'monthly_portfolio',
          api=apis2.quant),
    House('edelweiss', 'Edelweiss Mutual Fund', apis2.EDELWEISS, must=r'monthly', api=apis2.edelweiss),
    House('sundaram', 'Sundaram Mutual Fund', apis2.SUNDARAM, mode='all', must=r'monthly portfolio disclosure',
          exclude=r'fixed income', api=apis2.sundaram),
    House('lic', 'LIC Mutual Fund', 'https://www.licmf.com/downloads/monthly-portfolio', mode='all', must=r'monthly',
          api=apis2.lic),
    House('pgim', 'PGIM India Mutual Fund', 'https://www.pgimindia.com/mutual-funds/disclosures/Portfolios/Monthly-Portfolio',
          mode='all', api=apis2.pgim),
    House('whiteoak', 'WhiteOak Capital Mutual Fund', 'https://mf.whiteoakamc.com/regulatory-disclosures/scheme-portfolios',
          mode='all', must=r'monthly portfolio', api=apis2.whiteoak),
    House('bandhan', 'Bandhan Mutual Fund', apis2.BANDHAN, mode='all', api=apis2.bandhan),
    House('one360', '360 ONE Mutual Fund', apis2.ONE360, must=r'monthly_portfolio', exclude=r'overlap', api=apis2.one360),
    # The downloads list shows only after the visitor declares "I am NOT a US person / resident of Canada"; the owner
    # authorised that declaration for this collector (19 Nov 2026). One workbook for all schemes.
    House('mahindra', 'Mahindra Manulife Mutual Fund', apis2.MAHINDRA, must=r'monthly portfolio disclosure',
          api=apis2.mahindra),
    # One zip a month (a workbook per scheme); the list service answers a GitHub runner, not a machine outside India.
    House('icici', 'ICICI Prudential Mutual Fund', apis2.ICICI, must=r'monthly portfolio', api=apis2.icici),
    House('helios', 'Helios Mutual Fund', 'https://www.heliosmf.in/portfolio-disclosure', mode='all',
          must=r'month?t?ly[ -_]portfolio'),   # a workbook per scheme; some names are misspelt 'Monthtly'
]


def _lic_pages(month: str) -> list[str]:
    """LIC Pension Fund lists one month at a time (year and month in the address), ten files a page."""
    y, m = (int(x) for x in month.split('-'))
    base = 'https://www.licpensionfund.in/index.php/public-disclosures/portfolio-disclosures'
    return [f'{base}?year={y}&month={m}&page={p}' for p in (1, 2, 3)]


# NPS pension fund managers (PFRDA): each files every scheme's portfolio as on the month end (Scheme E, C, G in Tier I
# and II, central and state government, corporate CG, NPS Lite, APY ...), in the PFRDA form: Particulars, ISIN No.,
# Industry, Quantity, Market Value (in rupees), % of Portfolio. Pages from NPS Trust's list
# (npstrust.org.in/scheme-portfolio, read 19 Nov 2026), checked one by one against the October and September 2026 files.
PENSION = [
    House('nps_sbi', 'SBI Pension Funds', 'https://www.sbipensionfunds.co.in/disclosures/portfolio-details/',
          api=apis.nps_sbi, must=r'portfolio details', kind='pension', value_unit='rupee'),
    # The site sends an incomplete certificate chain that Python's TLS does not complete; the browser does.
    House('nps_lic', 'LIC Pension Fund', 'https://www.licpensionfund.in/index.php/public-disclosures/portfolio-disclosures',
          render=True, mode='all', must=r'/PageContentPdf/', pages=_lic_pages, browser_fetch=True, kind='pension',
          value_unit='rupee'),
    House('nps_icici', 'ICICI Pension Fund', 'https://www.icicipension.in/public_disclosure/portfolio_details',
          api=apis.nps_icici, must=r'monthly report', kind='pension', value_unit='rupee'),
    House('nps_absl', 'Aditya Birla Sun Life Pension Fund', 'https://pensionfund.adityabirlacapital.com/public-disclosure',
          must=r'portfolio_abslpm', kind='pension', value_unit='rupee'),
    House('nps_axis', 'Axis Pension Fund', 'https://www.axispensionfund.com/public-disclosures/portfolio-details',
          api=apis.nps_axis, kind='pension', value_unit='rupee'),
]
# Not collected (19 Nov 2026), none worked around:
#   UTI Retirement Solutions (utirsl.com) and Max Life Pension Fund (maxlifepensionfund.com): the sites' certificates
#     have expired (a browser refuses them too: ERR_CERT_DATE_INVALID).
#   HDFC Pension (hdfcpension.com/public-disclosures): the page lists 'Monthly Update: Oct 2026' workbooks, but the
#     site's edge (Akamai) answers 403 Access Denied to any request that is not a full browser visit.
#   Kotak Mahindra Pension Fund (kotakpensionfund.com/Kotak/Portfolio): the file list call is sent to a bot check
#     (Radware, validate.perfdrive.com).
#   Tata Pension (now tatapensionfund.com/public-disclosure-and-nav): the Portfolio tab's list never loads in a headless
#     browser ('Loading documents...'; the list calls are encrypted) and its Download buttons carry no addresses.

# Mutual fund houses on AMFI's list (www.amfiindia.com/online-center/portfolio-disclosure, read 19 Nov 2026) that are
# not collected, with the reason, for the Funds page's "is this complete?" line. Each was tried on 19 Nov 2026 from a
# cloud machine; none is worked around (no CAPTCHA or bot check is solved). .github/workflows/mf-probe.yml asks the
# blocked ones again from a GitHub runner.
NOT_COLLECTED = [
    ('Kotak Mahindra Mutual Fund', 'its file list is behind a CAPTCHA (Radware bot check)'),
    ('Navi Mutual Fund', 'its site answers a Cloudflare bot check'),
    ('Union Mutual Fund', 'its site refuses connections from outside India'),
    ('ASK Mutual Fund', 'a liquid fund only so far: no equity'),
    ('AlphaGrep Mutual Fund', "its site's firewall blocks the request"),
    ('Monarch Mutual Fund', 'an overnight fund only: no equity'),
    ('Carnelian Mutual Fund', 'a liquid fund only so far: no equity'),
    ('IL&FS Mutual Fund (IDF)', 'an infrastructure debt fund: no equity'),
]

HOUSES = HOUSES + PENSION
BY_KEY = {h.key: h for h in HOUSES}
