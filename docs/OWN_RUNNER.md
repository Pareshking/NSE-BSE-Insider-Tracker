# Own runner for the fund houses GitHub's runners cannot reach

Angel One, WhiteOak, Edelweiss and Bajaj refuse GitHub's hosted runners by address (20 Nov 2026), while the same
requests are answered from other machines. Union refuses any machine outside India. `.github/workflows/mf-portfolios-own.yml`
collects them on a self-hosted runner labelled `mf`, with the same script, raw store and archive as the hosted run.

Set up once (about 10 minutes, on a computer or small VM that stays on around the 11th to 16th of each month; in India
for Union):

1. GitHub: repository Settings > Actions > Runners > New self-hosted runner. Pick the machine's OS and follow the
   commands shown (download, `./config.sh --url ... --token ...`). When asked for labels, add `mf`.
2. Install it as a service so it survives restarts: `sudo ./svc.sh install && sudo ./svc.sh start` (Linux/macOS), or
   the service option on Windows.
3. The machine needs Python 3.12 (the workflow installs the packages and Chromium itself).
4. Test it: Actions > "Mutual fund portfolios (own runner)" > Run workflow, months `2026-10`.

The R2 secrets stay in GitHub and are handed to the job at run time; nothing is stored on the machine beyond the run.
