# Fund house access requests

Fund houses whose month-end portfolio files the collector cannot read (`collectors/mf_portfolios/houses.py`,
`NOT_COLLECTED`), with an email the owner can send to ask for the files or for access. SEBI requires every house to
publish its full month-end portfolio on its own website, so the files are public; what is asked for is a way to fetch
them that the site's protection does not refuse. Nothing here is worked around in the collector: no CAPTCHA solved, no
stealth browser, no disguised fingerprint.

The addresses below come from public listings (the house's own documents where marked, otherwise third-party
directories) and were not confirmed on the house's own contact page, because several of those pages are behind the
same protection. Check each one on the house's site before sending. Status as of 20 Nov 2026.

## Common text

> Subject: Monthly portfolio disclosure files: programmatic access
>
> Dear Investor Service / Compliance team,
>
> I run a small public research site that tracks Indian mutual fund holdings from the monthly portfolio disclosures
> that SEBI requires each fund house to publish on its website (SEBI Master Circular for Mutual Funds, portfolio
> disclosure). Our collector downloads each month-end file once, from the address your own disclosure page links,
> about once a month, identifying itself with an ordinary browser user agent. For {HOUSE}, {WHAT_HAPPENS}. Could you
> either allow-list automated monthly downloads of the portfolio disclosure files, tell us of an address (an API, a
> file share or a CDN path) where the same files can be fetched without a browser check, or email the monthly
> consolidated portfolio workbook after it is published? We read only the public disclosure files, at most a few
> requests a month, and attribute the data to {HOUSE}.
>
> Thank you,
> {OWNER}

## Per house

| House | Send to | {WHAT_HAPPENS} |
|---|---|---|
| Kotak Mahindra Mutual Fund | mutual@kotak.com (customer care, per directories); escalation: the Investor Relations Officer listed on kotakmf.com | every page of kotakmf.com, including Information > Forms and Downloads, redirects an automated request to a Radware bot check (validate.perfdrive.com), from a cloud machine and from a GitHub Actions runner |
| Navi Mutual Fund | mf@navi.com (per directories and Kuvera) | the downloads page (navi.com/mutual-fund/downloads/portfolio) answers a Cloudflare challenge ("Just a moment...") to automated requests |
| Union Mutual Fund | investorcare@unionmf.com (in the house's own KIM and SAI) | www.unionmf.com refuses connections from outside India, and our collector runs on servers outside India |
| Angel One Mutual Fund | support@angelonemf.com (per directories; AMFI lists the domain @angelonemf.com) | www.angelonemf.com/downloads answers HTTP 403 to requests from GitHub Actions runners, where our collector runs, though it answers the same request from other servers |
| WhiteOak Capital Mutual Fund | clientservice@whiteoakinvestors.com (per directories; AMFI lists the domain @whiteoakinvestors.com) | the list service your Scheme Portfolios page reads (cms.whiteoakamc.com/api/scheme-portfolios) answers HTTP 403 to requests from GitHub Actions runners, where our collector runs, though it answers the same request from other servers |

Bajaj Finserv Mutual Fund (service@bajajamc.com on its own contact page) is not listed while the browser probe on a
runner is read; add it here if the probe shows the downloads page refused there.
