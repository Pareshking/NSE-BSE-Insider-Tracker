"""Fund houses and where each publishes its month-end portfolio (pages from AMFI's Portfolio Disclosure list,
www.amfiindia.com/online-center/portfolio-disclosure, read 19 Nov 2026). Checked one by one against the October and
September 2026 files; a house not here is not collected, and the Funds page says how much of the industry is covered."""
from __future__ import annotations

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
]

BY_KEY = {h.key: h for h in HOUSES}
