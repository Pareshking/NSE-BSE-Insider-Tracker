"""Fund houses and where each publishes its month-end portfolio (pages from AMFI's Portfolio Disclosure list,
www.amfiindia.com/online-center/portfolio-disclosure, read 19 Nov 2026). Checked one by one against the October and
September 2026 files; a house not here is not collected, and the Funds page says how much of the industry is covered."""
from __future__ import annotations

from collectors.mf_portfolios import apis
from collectors.mf_portfolios.find import House

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
]

BY_KEY = {h.key: h for h in HOUSES}
