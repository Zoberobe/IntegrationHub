// Captures the local API and operations panel for portfolio material.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const [name, base = 'http://127.0.0.1:54321'] = process.argv.slice(2);
  if (!['api', 'retry', 'success'].includes(name)) throw Error('Use api|retry|success');
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXE });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  await page.goto(base + (name === 'api' ? '/docs' : '/dashboard'), { waitUntil: 'networkidle' });
  await page.screenshot({ path: `media/${name}.png` });
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });
