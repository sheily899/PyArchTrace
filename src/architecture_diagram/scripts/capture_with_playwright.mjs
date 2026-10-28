import { pathToFileURL } from 'node:url';

const [htmlPath, pngPath, executable, widthText, heightText, scaleText, modulePath, omitDrillIconsText] = process.argv.slice(2);
if (!htmlPath || !pngPath || !modulePath) throw new Error('Usage: capture_with_playwright.mjs html png browser width height scale playwright-module');
const { chromium } = await import(pathToFileURL(modulePath).href);
const browser = await chromium.launch({
  headless: true,
  ...(executable ? { executablePath: executable } : {}),
});
const errors = [];
const page = await browser.newPage({
  viewport: { width: Number(widthText), height: Number(heightText) },
  deviceScaleFactor: Number(scaleText),
});
page.on('pageerror', error => errors.push(String(error)));
page.on('console', message => { if (message.type() === 'error') errors.push(`console:${message.text()}`); });
const response = await page.goto(pathToFileURL(htmlPath).href, { waitUntil: 'load', timeout: 30000 });
await page.evaluate(() => document.fonts.ready);
const svg = page.locator('#canvas svg');
await page.addStyleTag({ content: `html, body { height:auto!important; min-height:0!important; overflow:visible!important; }
  .workspace { height:auto!important; min-height:0!important; flex:0 0 auto!important; overflow:visible!important; }
  #canvas { min-height:0!important; }
  #layout-meta,#layout-notice,#module-details { visibility:hidden!important; }` });
if (omitDrillIconsText === '1') await page.evaluate(() => {
  const svg = document.querySelector('#canvas svg');
  if (svg?.classList.contains('architecture-diagram')) svg.querySelectorAll('.drill-icon').forEach(icon => icon.remove());
});
await svg.screenshot({ path: pngPath, animations: 'disabled', scale: 'device' });
const dom = await page.evaluate(() => {
  const svg = document.querySelector('#canvas svg');
  if (!svg) return { svg: false, nodeCount: 0, textOverflow: [], viewBox: null };
  const overflow = [];
  for (const node of svg.querySelectorAll('.node')) {
    const card = node.querySelector('.node-card');
    if (!card) continue;
    const width = Number(card.getAttribute('width'));
    const height = Number(card.getAttribute('height'));
    for (const label of node.querySelectorAll('text')) {
      const box = label.getBBox();
      if (box.x < 0 || box.x + box.width > width || box.y < 0 || box.y > height) overflow.push(node.dataset.node);
    }
  }
  const rect=svg.getBoundingClientRect(),workspace=document.querySelector('.workspace');
  return { svg: true, nodeCount: svg.querySelectorAll('.node').length, drillIconCount: svg.querySelectorAll('.drill-icon').length, textOverflow: [...new Set(overflow)],
    viewBox: svg.getAttribute('viewBox'), svgClientRect:{x:rect.x,y:rect.y,width:rect.width,height:rect.height},
    viewport:{width:innerWidth,height:innerHeight,documentWidth:document.documentElement.scrollWidth,
      workspaceWidth:workspace.clientWidth,workspaceScrollWidth:workspace.scrollWidth}, title: document.title };
});
await browser.close();
process.stdout.write(JSON.stringify({ httpStatus: response?.status() ?? null, errors, dom }));
