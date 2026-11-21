// Visit every page at several screen sizes; collect console/page errors, failed requests,
// CSP violations and horizontal overflow. Screenshots go to ./shots.
const { chromium } = require('playwright');
const fs = require('fs');
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8000';
const NEW_PW = process.env.ADMIN_PW || 'E2e-Admin-pw1';
const PAGES = ['/', '/live', '/entries', '/entries?tab=exit', '/history', '/alerts', '/reports', '/occupancy', '/cameras', '/users', '/settings'];
const SIZES = { phone: { width: 390, height: 844 }, tablet: { width: 820, height: 1180 }, desktop: { width: 1440, height: 900 } };
fs.mkdirSync('shots', { recursive: true });

(async () => {
  const b = await chromium.launch();
  const issues = [];
  const watch = (p, where) => {
    p.on('pageerror', (e) => issues.push(`[${where()}] pageerror: ${e.message}`));
    p.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') issues.push(`[${where()}] console.${m.type()}: ${m.text().slice(0, 200)}`); });
    p.on('response', (r) => { if (r.status() >= 400 && !r.url().includes('/snapshot')) issues.push(`[${where()}] HTTP ${r.status()} ${r.request().method()} ${r.url().replace(BASE, '')}`); });
    p.on('requestfailed', (r) => { const f = r.failure()?.errorText || ''; if (!f.includes('ERR_ABORTED')) issues.push(`[${where()}] request failed ${r.url().replace(BASE, '')} ${f}`); });
  };

  // 1. first login with the default password -> forced change
  const ctx = await b.newContext({ viewport: SIZES.desktop });
  const p = await ctx.newPage();
  let here = 'login';
  watch(p, () => here);
  await p.goto(BASE + '/');
  await p.fill('input[autocomplete=username]', 'admin');
  await p.fill('input[type=password]', NEW_PW);
  await p.keyboard.press('Enter');
  await p.waitForSelector('text=Parking now', { timeout: 10000 });

  // 2. every page at every size
  for (const [size, vp] of Object.entries(SIZES)) {
    await p.setViewportSize(vp);
    for (const path of PAGES) {
      here = `${size} ${path}`;
      await p.goto(BASE + path);
      await p.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => {});
      await p.waitForTimeout(800);
      const o = await p.evaluate(() => ({ sw: document.documentElement.scrollWidth, w: window.innerWidth, h1: document.querySelector('h1')?.textContent }));
      if (o.sw > o.w + 1) issues.push(`[${here}] horizontal overflow: page ${o.sw}px wide in a ${o.w}px window`);
      const bad = await p.evaluate(() => [...document.querySelectorAll('body *')].filter((el) => {
        const r = el.getBoundingClientRect(); return r.width > 0 && r.right > window.innerWidth + 2 && getComputedStyle(el).position !== 'fixed'
          && !el.closest('[class*="overflow-x-auto"],[class*="overflow-auto"],table,.recharts-wrapper,[class*="-translate-x-full"]');
      }).slice(0, 3).map((el) => `${el.tagName.toLowerCase()}.${String(el.className).slice(0, 60)}`));
      if (bad.length) issues.push(`[${here}] elements wider than the screen: ${bad.join(' | ')}`);
      await p.screenshot({ path: `shots/${size}${path.replace(/[/?=]/g, '_') || '_home'}.png`, fullPage: false });
    }
  }
  fs.writeFileSync('issues.txt', [...new Set(issues)].join('\n'));
  console.log(`pages visited: ${PAGES.length * Object.keys(SIZES).length}, distinct issues: ${new Set(issues).size}`);
  await b.close();
})();
