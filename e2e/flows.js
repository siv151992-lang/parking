// End-to-end workflows in a real browser against the running app.
const { chromium } = require('playwright');
const fs = require('fs');
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8000';
const ADMIN_PW = process.env.ADMIN_PW || 'E2e-Admin-pw1';
const results = [];
const RUN = Date.now().toString(36).slice(-4).toUpperCase();
const errors = [];

async function step(name, fn) {
  try { await fn(); results.push(`PASS  ${name}`); }
  catch (e) { results.push(`FAIL  ${name}: ${String(e.message).split('\n')[0].slice(0, 220)}`); }
}
const watch = (p, label) => {
  p.on('pageerror', (e) => errors.push(`[${label}] pageerror ${e.message}`));
  p.on('console', (m) => m.type() === 'error' && errors.push(`[${label}] console ${m.text().slice(0, 200)}`));
};
async function login(p, user, pw) {
  await p.goto(BASE + '/');
  await p.fill('input[autocomplete=username]', user);
  await p.fill('input[type=password]', pw);
  await p.keyboard.press('Enter');
}
const toast = (p, text) => p.waitForSelector(`text=${text}`, { timeout: 8000 });

(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
  const p = await ctx.newPage();
  watch(p, 'admin');

  await step('keyboard: login form reachable with Tab, focus is visible', async () => {
    await p.goto(BASE + '/');
    const a = await p.evaluate(() => document.activeElement.getAttribute('autocomplete'));  // username has autofocus
    await p.keyboard.press('Tab'); await p.keyboard.press('Tab');
    const btn = await p.evaluate(() => ({ tag: document.activeElement.tagName, txt: document.activeElement.textContent.trim(),
      outline: getComputedStyle(document.activeElement).outlineStyle }));
    if (!['username', 'current-password'].includes(a) || btn.tag !== 'BUTTON') throw new Error(`focus order ${a} -> ${btn.tag} ${btn.txt}`);
    if (btn.outline === 'none') throw new Error('no visible focus outline on the Sign in button');
  });

  await step('wrong password shows an error message', async () => {
    await login(p, 'admin', 'wrong-password');
    await toast(p, 'Invalid username or password');
  });

  await step('login as admin', async () => { await login(p, 'admin', ADMIN_PW); await p.waitForSelector('text=Parking now'); });

  await step('manual entry recorded and listed', async () => {
    await p.goto(BASE + '/entries');
    await p.click('button:has-text("Manual entry")');
    await p.fill('input[placeholder="MH12AB1234"]', 'TN09ZZ4321');
    await p.click('button:has-text("Record entry")');
    await toast(p, 'Entry recorded for TN09ZZ4321');
    await p.waitForSelector('td >> text=TN09ZZ4321', { timeout: 8000 });
  });

  await step('manual exit closes that vehicle', async () => {
    await p.click('button[role=tab]:has-text("Vehicles out")');
    await p.click('button:has-text("Manual exit")');
    await p.fill('input[placeholder="Registration no."] >> nth=-1', 'TN09ZZ4321');
    await p.click('[role=dialog] button:has-text("Record exit"), .fixed button:has-text("Record exit")');
    await toast(p, 'Exit recorded');
  });

  await step('cancel a false entry (with reason)', async () => {
    await p.goto(BASE + '/entries');
    await p.click('button:has-text("Manual entry")');
    await p.fill('input[placeholder="MH12AB1234"]', 'KA01ZZ0001');
    await p.click('button:has-text("Record entry")');
    await toast(p, 'Entry recorded for KA01ZZ0001');
    const row = p.locator('tr', { hasText: 'KA01ZZ0001' }).first();
    await row.locator('button:has-text("Cancel")').click();
    await p.fill('input[placeholder^="e.g. false detection"]', 'e2e test: false detection');
    await p.click('button:has-text("Cancel transaction")');
    await p.waitForSelector('tr:has-text("KA01ZZ0001") >> text=CANCELLED', { timeout: 8000 });
  });

  await step('vehicle history search finds the plate', async () => {
    await p.goto(BASE + '/history');
    await p.fill('input[placeholder="Registration no."]', 'TN09ZZ4321');
    await p.waitForSelector('td >> text=TN09ZZ4321', { timeout: 8000 });
  });

  await step('captured vehicle images load (media token)', async () => {
    await p.goto(BASE + '/history');
    await p.waitForTimeout(2500);
    const imgs = await p.evaluate(() => [...document.images].filter((i) => i.src.includes('/api/media/'))
      .map((i) => ({ ok: i.complete && i.naturalWidth > 0, src: i.src })));
    if (!imgs.length) throw new Error('no vehicle images on the page');
    if (imgs.some((i) => i.src.includes('token=ey') === false)) throw new Error('image URL without media token');
    const loaded = imgs.filter((i) => i.ok).length;
    if (loaded === 0) throw new Error(`0 of ${imgs.length} images loaded`);
  });

  for (const fmt of ['CSV', 'Excel', 'PDF']) {
    await step(`report export downloads (${fmt})`, async () => {
      await p.goto(BASE + '/reports');
      await p.waitForSelector(`button:has-text("${fmt}")`);
      const [dl] = await Promise.all([p.waitForEvent('download', { timeout: 15000 }), p.click(`button:has-text("${fmt}")`)]);
      const path = await dl.path();
      const size = fs.statSync(path).size;
      const head = fs.readFileSync(path).subarray(0, 4).toString('latin1');
      if (size < 200) throw new Error(`file only ${size} bytes`);
      if (fmt === 'PDF' && head !== '%PDF') throw new Error('not a PDF');
      if (fmt === 'Excel' && head.slice(0, 2) !== 'PK') throw new Error('not an xlsx');
    });
  }

  await step('add a parking row and correct its count', async () => {
    await p.goto(BASE + '/occupancy');
    await p.click('button:has-text("Add row")');
    await p.fill('input[placeholder="Row A"]', `Row ${RUN}`);
    const n = p.locator('[role=dialog] input[type=number], .fixed input[type=number]').first();
    await n.fill('25');
    await p.click('button:has-text("Save") >> nth=-1');
    await p.waitForSelector(`td >> text=Row ${RUN}`, { timeout: 8000 });
    await p.locator('tr', { hasText: `Row ${RUN}` }).locator('button[title="Correct count"]').click();
    await p.locator('input[type=number]').last().fill('5');
    await p.click('button:has-text("Save") >> nth=-1');
    await p.waitForSelector(`tr:has-text("Row ${RUN}") >> td >> text=20`, { timeout: 8000 });
  });

  await step('add a simulated camera from the form', async () => {
    await p.goto(BASE + '/cameras');
    await p.click('button:has-text("Add camera")');
    await p.fill('input[placeholder="Main gate entry"]', `E2E cam ${RUN}`);
    await p.click('text=Advanced settings');
    await p.check('text=Simulated test camera');
    await p.click('button:has-text("Save camera")');
    await p.waitForSelector(`td >> text=E2E cam ${RUN}`, { timeout: 8000 });
  });

  await step('add many cameras (paste)', async () => {
    await p.click('button:has-text("Add many")');
    await p.fill('textarea[aria-label="Camera list"]', `Bulk ${RUN}\tGate in\t10.254.${Date.now() % 250}.1\nRow ${RUN} in\t\t10.254.${Date.now() % 250}.2`);
    await p.uncheck('text=Check each camera answers');
    await p.click('button:has-text("Check 2 cameras")');
    await p.click('button:has-text("Add 2 cameras")');
    await toast(p, 'Added 2 cameras');
  });

  await step('live view: picture tiles and enlarged live video load', async () => {
    await p.goto(BASE + '/live');
    await p.waitForTimeout(3000);
    const tiles = await p.evaluate(() => [...document.images].filter((i) => i.src.startsWith('blob:') && i.naturalWidth > 0).length);
    if (!tiles) throw new Error('no camera picture loaded');
    await p.click('button[title="Open live video"] >> nth=0');
    await p.waitForTimeout(2500);
    const video = await p.evaluate(() => [...document.images].find((i) => i.src.includes('/stream'))?.naturalWidth || 0);
    if (!video) throw new Error('live video did not load');
    await p.keyboard.press('Escape');
  });

  await step('create an operator account', async () => {
    await p.goto(BASE + '/users');
    await p.click('button:has-text("Add user")');
    const dlg = p.locator('[role=dialog]');
    await dlg.locator('input').nth(0).fill(`op${RUN}@site.com`);
    await dlg.locator('input').nth(1).fill('Op Two');
    await dlg.locator('input[type=email]').fill(`op${RUN}@site.com`);
    await dlg.locator('input[type=password]').fill('Operator-pw1');
    await dlg.locator('button:has-text("Save")').click();
    await p.waitForSelector(`text=@op${RUN.toLowerCase()}@site.com`, { timeout: 8000 });
  });

  await step('dialog: focus moves inside, Tab stays inside, Escape closes and focus returns', async () => {
    await p.goto(BASE + '/occupancy');
    const opener = p.locator('button:has-text("Add row")');
    await opener.click();
    const inside = async () => p.evaluate(() => !!document.activeElement.closest('[role=dialog]'));
    if (!(await inside())) throw new Error('focus not in the dialog');
    for (let i = 0; i < 12; i++) await p.keyboard.press('Tab');
    if (!(await inside())) throw new Error('Tab left the dialog');
    await p.keyboard.press('Escape');
    if (await p.locator('[role=dialog]').count()) throw new Error('Escape did not close');
    const back = await p.evaluate(() => document.activeElement.textContent.trim());
    if (!back.includes('Add row')) throw new Error(`focus returned to "${back}"`);
  });

  await step('settings save', async () => {
    await p.goto(BASE + '/settings');
    await p.waitForSelector('text=facility name');
    const name = p.locator('input').first();
    await name.fill(`E2E Parking ${RUN}`);
    await p.click('button:has-text("Save settings")');
    await toast(p, 'Settings saved');
  });

  await step('alerts: mark all read clears the badge', async () => {
    await p.goto(BASE + '/alerts');
    await p.click('button:has-text("Mark all read")');
    await p.waitForTimeout(1000);
    const badge = await p.locator('a[href="/alerts"] span.bg-red-500').count();
    if (badge) throw new Error('unread badge still shown');
  });

  await step('operator: limited menu, no access to users/cameras setup', async () => {
    const c2 = await b.newContext({ viewport: { width: 1280, height: 800 } });
    const q = await c2.newPage(); watch(q, 'operator');
    await login(q, `op${RUN}@site.com`, 'Operator-pw1');
    await q.waitForSelector('text=Parking now');
    const nav = await q.locator('nav a').allInnerTexts();
    if (nav.some((t) => /Users|Settings/.test(t))) throw new Error(`menu shows: ${nav.join(', ')}`);
    await q.goto(BASE + '/users');
    await q.waitForSelector("text=You don't have permission to view this page.");
    await q.goto(BASE + '/cameras');
    if (await q.locator('button:has-text("Add camera")').count()) throw new Error('operator can add cameras');
    await c2.close();
  });

  await step('logout returns to the login page', async () => {
    await p.click('button[aria-label="Sign out"]');
    await p.waitForSelector('text=Sign in');
    await p.goto(BASE + '/entries');
    await p.waitForSelector('text=Sign in');
  });

  console.log(results.join('\n'));
  console.log(errors.length ? 'BROWSER ERRORS:\n' + [...new Set(errors)].join('\n') : 'browser errors: none');
  await b.close();
})();
