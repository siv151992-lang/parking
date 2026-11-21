# Browser tests (Playwright)

Two scripts that drive the real app in Chromium. They need a running app with demo data
and an admin whose password is `ADMIN_PW`.

```bash
# 1. a fresh database with demo data, then start the app (it serves the built frontend)
cd backend && python -m app.seed --days 5 && uvicorn app.main:app --port 8000
# 2. log in once as admin / Admin@123 and set the new password to $ADMIN_PW (forced on first login)
# 3. run
npm install --no-save playwright && npx playwright install chromium
ADMIN_PW='E2e-Admin-pw1' node e2e/flows.js   # 21 workflows: entries/exits, cancel, history, exports, rows, cameras, users, RBAC, dialogs, logout
ADMIN_PW='E2e-Admin-pw1' node e2e/crawl.js   # every page at phone / tablet / desktop: console errors, failed requests, overflow
```

`flows.js` prints PASS / FAIL per workflow. `crawl.js` writes `issues.txt` and screenshots to `shots/`.
