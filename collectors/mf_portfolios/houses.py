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
    # Houses whose page draws its list from a service (collectors/mf_portfolios/apis.py); `page` is where a person looks.
    House('franklin', 'Franklin Templeton Mutual Fund', 'https://www.franklintempletonindia.com/reports',
          must=r'monthly-portfolio', api=apis.franklin),
    House('hsbc', 'HSBC Mutual Fund', apis.HSBC, mode='all', exclude=r'additional-information', api=apis.hsbc),
    House('canara', 'Canara Robeco Mutual Fund', apis.CANARA, mode='all', api=apis.canara),
    House('invesco', 'Invesco Mutual Fund', 'https://www.invescomutualfund.com/literature-forms/monthly-holdings/equity',
          mode='all', api=apis.invesco),
    House('quant', 'quant Mutual Fund', 'https://quantmutual.com/statutory-disclosures', must=r'monthly_portfolio',
          api=apis.quant),
    House('edelweiss', 'Edelweiss Mutual Fund', apis.EDELWEISS, must=r'monthly', api=apis.edelweiss),
    House('sundaram', 'Sundaram Mutual Fund', apis.SUNDARAM, mode='all', must=r'monthly portfolio disclosure',
          exclude=r'fixed income', api=apis.sundaram),
    House('lic', 'LIC Mutual Fund', 'https://www.licmf.com/downloads/monthly-portfolio', mode='all', must=r'monthly',
          api=apis.lic),
    House('pgim', 'PGIM India Mutual Fund', 'https://www.pgimindia.com/mutual-funds/disclosures/Portfolios/Monthly-Portfolio',
          mode='all', api=apis.pgim),
    House('whiteoak', 'WhiteOak Capital Mutual Fund', 'https://mf.whiteoakamc.com/regulatory-disclosures/scheme-portfolios',
          mode='all', must=r'monthly portfolio', api=apis.whiteoak),
    House('bandhan', 'Bandhan Mutual Fund', apis.BANDHAN, mode='all', api=apis.bandhan),
    House('one360', '360 ONE Mutual Fund', apis.ONE360, must=r'monthly_portfolio', exclude=r'overlap', api=apis.one360),
]

BY_KEY = {h.key: h for h in HOUSES}
