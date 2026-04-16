# Screenshots

Documentation screenshots for the IBKR Cash Inflow Tracker.

## Files

- `dashboard.png` - Full-page capture of the consolidated dashboard rendered with **synthetic demo data** (no real account data).

## Regenerating the dashboard screenshot

The screenshot is produced reproducibly from fabricated data so it is safe for a
public repo:

```powershell
# From the project root, with the project venv active:
python scripts/build_demo_dashboard.py     # writes screenshots/_dashboard_demo.html
python scripts/screenshot_dashboard.py     # writes screenshots/dashboard.png
Remove-Item screenshots/_dashboard_demo.html
```

`scripts/screenshot_dashboard.py` uses Playwright + Chromium; install once with:

```powershell
uv pip install --python .\.venv\Scripts\python.exe playwright
python -m playwright install chromium
```

## Privacy note

Do NOT commit screenshots captured from real IBKR data. The demo script seeds
its random generator so the numbers in `dashboard.png` are deterministic and
clearly fabricated (the dashboard title says "IBKR Cash Inflows (demo)").
