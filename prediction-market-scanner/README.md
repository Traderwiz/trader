# Prediction Market Scanner

This scanner retrieves live open-market data from Kalshi's public REST API and creates a timestamped technical shortlist for later research and Wealthsimple verification.

It is intentionally conservative:

- uses live market fields rather than search-engine snippets;
- records the retrieval timestamp and exact ticker;
- uses executable ask estimates, not headline probability alone;
- rejects wide spreads, low volume, insufficient depth, extreme prices, and distant expiries;
- estimates a conservative Wealthsimple break-even for a small test order;
- never claims that a technically attractive market has a true forecasting edge.

## Important limitation

Kalshi contains more contracts than Wealthsimple Predict. A listed candidate may not be available in Wealthsimple. Every finalist must be independently researched and verified with a live Wealthsimple order preview before any trade.

## Files

- `scanner.py` — live data retrieval, filtering, scoring, and report generation.
- `config/scanner.yml` — editable filters and conservative fee assumptions.
- `reports/latest.md` — human-readable latest report after a successful run.
- `reports/scan-*.json` — timestamped machine-readable snapshots.
- `reports/scan-*.csv` — timestamped spreadsheet-friendly snapshots.
- `tests/test_scanner.py` — conversion and fee helper tests.

## Run manually in GitHub

The workflow becomes available after the branch is merged into the repository's default branch.

1. Open the repository on GitHub.
2. Open **Actions**.
3. Choose **Live Prediction Market Scan**.
4. Choose **Run workflow**.
5. Open `prediction-market-scanner/reports/latest.md` after the run completes.

The workflow also runs at 12:15 and 18:15 UTC each day. GitHub schedules can be delayed during periods of high load.

## Run locally

```bash
cd prediction-market-scanner
python -m pip install -r requirements.txt
pytest -q
python scanner.py --config config/scanner.yml --output reports
```

## How prices are interpreted

The scanner prefers direct dollar ask fields returned by the market endpoint. When a direct ask is absent, it derives the ask from the opposite-side bid:

- `YES ask = 100 - best NO bid`
- `NO ask = 100 - best YES bid`

The report labels these as live asks and records the retrieval time. The scanner does not use web-search snippets or cached page summaries.

## Technical score

The score is only a research-priority score. It rewards:

- higher volume;
- narrower spread;
- greater displayed ask depth when available;
- nearer closing date;
- prices that are not extremely close to 0 or 100.

It does **not** estimate the true event probability. Independent research is required before trading.

## Wealthsimple fee estimate

The configured fee is a conservative placeholder inferred from the small previews observed in Wealthsimple Predict. Wealthsimple's final preview is authoritative. Adjust `config/scanner.yml` when a more accurate fee formula is established.

## Safety

The scanner:

- uses no Wealthsimple credentials;
- uses no Kalshi trading credentials;
- cannot place orders;
- writes reports only;
- times out after ten minutes in GitHub Actions.
