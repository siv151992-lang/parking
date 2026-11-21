// Office parking workflows in a real browser (needs demo data: python -m app.seed).
const { chromium } = require('playwright');
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8000';
const EMP_PW = 'Employee@123';
const results = [];
const errors = [];
const step = async (name, fn) => {
  try { await fn(); results.push(`PASS  ${name}`); }
  catch (e) { results.push(`FAIL  ${name}: ${String(e.message).split('\n')[0].slice(0, 240)}`); }
};
const watch = (p, label) => {
  p.on('pageerror', (e) => errors.push(`[${label}] pageerror ${e.message}`));
  p.on('console', (m) => m.type() === 'error' && !m.text().includes('ERR_TUNNEL_CONNECTION_FAILED') && errors.push(`[${label}] console ${m.text().slice(0, 200)}`));
};
async function login(ctx, user, pw, label) {
  const p = await ctx.newPage(); watch(p, label);
  await p.goto(BASE + '/login');
  await p.fill('input[autocomplete=username]', user); await p.fill('input[type=password]', pw);
  await p.keyboard.press('Enter');
  await p.waitForLoadState('networkidle').catch(() => {});
  return p;
}
const toast = (p, text) => p.waitForSelector(`text=${text}`, { timeout: 10000 });
const tomorrow = () => { const d = new Date(Date.now() + 86400000); return d.toISOString().slice(0, 10); };

(async () => {
  const b = await chromium.launch();
  const emp = await b.newContext({ viewport: { width: 390, height: 844 }, timezoneId: 'Asia/Kolkata' });   // employees on their phone
  let p;
  let visitorBookingUrl = '';

  await step('employee lands on "Book a parking slot" with offices and free counts', async () => {
    p = await login(emp, 'asha', EMP_PW, 'asha');
    await p.waitForSelector('text=Book a parking slot');
    await p.waitForSelector('text=Head Office');
    const free = await p.locator('li:has-text("Head Office") span.text-2xl').innerText();
    if (!(Number(free) >= 0)) throw new Error('no free count');
  });

  await step('employee cannot open the staff console', async () => {
    await p.goto(BASE + '/live');
    await p.waitForURL(/\/park$/);
  });

  await step('my bookings shows the upcoming booking with a QR code', async () => {
    await p.goto(BASE + '/park/bookings');
    await p.click('ul li a >> nth=0');
    await p.waitForSelector('img[alt^="Booking QR code"]', { timeout: 10000 });
  });

  await step('daily limit: a second own booking for tomorrow is refused', async () => {
    await p.goto(`${BASE}/park/office/1?day=${tomorrow()}&from=09:00&to=18:00`);
    await p.waitForSelector('text=free slot');
    await p.click('button:has-text("Book a free slot")');
    await toast(p, 'the limit is 1 per day');
  });

  await step('book a slot for a visitor', async () => {
    await p.click('button[role=tab]:has-text("A visitor")');
    const inputs = p.locator('aside input');
    await inputs.nth(0).fill('Mr Rao');
    await inputs.nth(1).fill('TN09XY1234');
    await p.click('button:has-text("Book a free slot")');
    await p.waitForURL(/\/park\/bookings\/\d+/);
    await p.waitForSelector('text=visitor', { timeout: 10000 }).catch(() => {});
    await p.waitForSelector('text=Mr Rao');
    visitorBookingUrl = p.url();
  });

  await step('change the visitor booking time', async () => {
    await p.click('button:has-text("Change time")');
    const t = p.locator('[role=dialog] input[type=time]');
    await t.nth(0).fill('10:00'); await t.nth(1).fill('12:00');
    await p.click('[role=dialog] button:has-text("Save")');
    await toast(p, 'Booking updated');
    await p.waitForSelector('text=10:00–12:00');
  });

  await step('cancel the visitor booking', async () => {
    await p.click('button:has-text("Cancel booking")');
    await p.click('[role=dialog] button:has-text("Cancel booking")');
    await toast(p, 'Booking cancelled');
    await p.waitForSelector('text=Cancelled');
  });

  await step('vehicles: add, edit and remove a vehicle', async () => {
    await p.goto(BASE + '/park/vehicles');
    await p.click('button:has-text("Add vehicle")');
    const plate = `KA${String(Date.now()).slice(-2)}ZZ${String(Date.now()).slice(-4)}`;
    await p.fill('[role=dialog] input >> nth=0', plate);
    await p.selectOption('[role=dialog] select', 'TWO_WHEELER');
    await p.click('[role=dialog] button:has-text("Save")');
    await toast(p, 'Vehicle added');
    await p.click(`button[aria-label="Edit ${plate}"]`);
    await p.fill('[role=dialog] input >> nth=1', 'Blue scooter');
    await p.click('[role=dialog] button:has-text("Save")');
    await toast(p, 'Vehicle updated');
    await p.click(`button[aria-label="Remove ${plate}"]`);
    await p.click('[role=dialog] button:has-text("Remove")');
    await toast(p, 'Vehicle removed');
  });

  await step('profile: save department', async () => {
    await p.goto(BASE + '/park/profile');
    await p.fill('label:has-text("Department") input', 'Platform Engineering');
    await p.click('button:has-text("Save") >> nth=0');
    await toast(p, 'Profile saved');
  });

  let arjunCode = '';
  await step('another employee picks a specific slot on the slot map', async () => {
    const ctx = await b.newContext({ viewport: { width: 1280, height: 900 }, timezoneId: 'Asia/Kolkata' });
    const q = await login(ctx, 'arjun', EMP_PW, 'arjun');
    await q.goto(`${BASE}/park/office/1?day=${tomorrow()}&from=09:00&to=18:00`);
    await q.waitForSelector('text=free slot');
    const slot = q.locator('button[aria-pressed=false]:not([disabled]):has-text("A-1")').first();
    const code = (await slot.locator('span').first().innerText()).trim();
    await slot.click();
    await q.click(`button:has-text("Book slot ${code}")`);
    await q.waitForURL(/\/park\/bookings\/\d+/);
    await q.waitForSelector(`text=slot ${code}`);
    arjunCode = (await q.locator('p.font-mono').innerText()).trim();
    await ctx.close();
  });

  await step('security desk: future booking is "too early"; today\'s booking checks in and out', async () => {
    const ctx = await b.newContext({ viewport: { width: 820, height: 1180 }, timezoneId: 'Asia/Kolkata' });   // tablet at the gate
    const g = await login(ctx, 'operator', 'Operator@123', 'operator');
    await g.goto(BASE + '/security');
    await g.fill('input[aria-label="Booking code or vehicle number"]', arjunCode);
    await g.getByRole('button', { name: 'Check', exact: true }).click();
    await g.waitForSelector('text=Too early');
    await g.fill('input[aria-label="Booking code or vehicle number"]', 'KA01MJ4521');   // asha's car, booked today 09-18
    await g.getByRole('button', { name: 'Check', exact: true }).click();
    await g.waitForSelector('[aria-live=polite]:has-text("KA01MJ4521")');   // the new result, not the previous one
    const msg = await g.waitForSelector('[aria-live=polite] p.font-semibold');
    const text = await msg.innerText();
    if (/Valid booking/.test(text)) {
      await g.click('[aria-live=polite] button:has-text("Check in")');
      await toast(g, 'checked in');
      await g.click('[aria-live=polite] button:has-text("Check out")');
      await toast(g, 'checked out');
    } else if (/Parked/.test(text)) {
      await g.click('[aria-live=polite] button:has-text("Check out")');
      await toast(g, 'checked out');
    } else throw new Error(`unexpected verdict: ${text}`);
    await ctx.close();
  });

  await step('admin: add an office with a floor, zone and 5 slots; assign and delete a slot', async () => {
    const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, timezoneId: 'Asia/Kolkata' });
    const a = await login(ctx, 'manager', 'Manager@123', 'manager');
    await a.goto(BASE + '/offices');
    await a.waitForSelector('h1:has-text("Offices & Slots")');
    const name = `Branch ${Date.now().toString(36).slice(-4)}`;
    await a.click('button:has-text("Add office")');
    await a.fill('label:has-text("Office name") input', name);
    await a.fill('label:has-text("City") input', 'Pune');
    await a.click('[role=dialog] button:has-text("Save")');
    await toast(a, 'Office added');
    await a.click('button:has-text("Add floor")');
    await a.fill('[role=dialog] input >> nth=0', 'Ground');
    await a.click('[role=dialog] button:has-text("Save")');
    await toast(a, 'Floor saved');
    await a.getByRole('button', { name: 'Zone', exact: true }).first().click();
    await a.fill('[role=dialog] input', 'P');
    await a.click('[role=dialog] button:has-text("Save")');
    await toast(a, 'Zone saved');
    await a.getByRole('button', { name: 'Slots', exact: true }).first().click();
    await a.fill('label:has-text("How many") input', '5');
    await a.click('[role=dialog] button:has-text("Add 5 slots")');
    await toast(a, '5 slots added');
    await a.click('button[title="Edit P-03"]');
    await a.fill('[role=dialog] input[placeholder^="Search a person"]', 'Vikram');
    await a.click('[role=dialog] li button >> nth=0');
    await a.click('[role=dialog] button:has-text("Save")');
    await toast(a, 'Slot saved');
    await a.waitForSelector('button[title="Edit P-03"]:has-text("Vikram")');
    await a.click('button[title="Edit P-05"]');
    await a.click('[role=dialog] button:has-text("Delete")');
    await a.click('[role=dialog] >> nth=-1 >> button:has-text("Delete")');
    await toast(a, 'Slot deleted');
    await ctx.close();
  });

  await step('slot bookings page lists today and filters by status', async () => {
    const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, timezoneId: 'Asia/Kolkata' });
    const a = await login(ctx, 'manager', 'Manager@123', 'manager2');
    await a.goto(BASE + '/bookings');
    await a.waitForSelector('table tbody tr');
    await a.click('button[aria-pressed]:has-text("Confirmed")');
    await a.waitForTimeout(800);
    const statuses = await a.locator('table tbody td:nth-child(5)').allInnerTexts();
    if (statuses.some((s) => s && !/Confirmed/.test(s))) throw new Error(`filter shows ${statuses.join(',')}`);
    await ctx.close();
  });

  console.log(results.join('\n'));
  console.log(errors.length ? 'BROWSER ERRORS:\n' + [...new Set(errors)].join('\n') : 'browser errors: none');
  await b.close();
})();
