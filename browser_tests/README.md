# Browser tests

Browser tests are separate from the ordinary pytest suite and use Playwright
with Chromium only.

Install development dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Install the Chromium browser once:

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
```

Run the Feedback browser regression test:

```powershell
.\.venv\Scripts\python.exe -m pytest browser_tests -m browser
```

The ordinary non-browser suite remains:

```powershell
.\.venv\Scripts\python.exe -m pytest
```
