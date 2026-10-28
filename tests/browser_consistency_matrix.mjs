import { createServer } from 'node:http';
import { readFile, writeFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';

const [configPath, playwrightModule, reportPath] = process.argv.slice(2);
if (!configPath || !playwrightModule || !reportPath) {
  throw new Error('用法：browser_consistency_matrix.mjs config.json playwright-module report.json');
}
const config = JSON.parse(await readFile(configPath, 'utf8'));
const htmlBytes = await readFile(config.htmlPath);
const html = htmlBytes.toString('utf8');
const payloadMatch = html.match(/<script id="payload" type="application\/json">([\s\S]*?)<\/script>/);
if (!payloadMatch) throw new Error('交互页没有内嵌图数据');
const payload = JSON.parse(payloadMatch[1]);
const rootGraph = payload.views[payload.root]?.graph;
const crossCuttingIds = new Set((rootGraph?.layers || []).filter(layer => layer.crossCutting).map(layer => layer.id));
const drillNode = rootGraph?.nodes?.find(node => crossCuttingIds.has(node.layer) &&
  node.drilldown && payload.views[node.drilldown]);
if (!drillNode) throw new Error('回归图没有可下钻节点');

const { chromium } = await import(pathToFileURL(playwrightModule).href);
const server = createServer((request, response) => {
  response.writeHead(200, { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' });
  response.end(htmlBytes);
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const httpUrl = `http://127.0.0.1:${server.address().port}/architecture-diagram.html`;

const results = [];
const screenshots = [];
const browserAvailability = [];
let referenceGeometry = null;
const viewportWidths = [1280, 1440, 1920];

async function geometry(page) {
  return page.evaluate(() => {
    const svg = document.querySelector('#canvas svg');
    const inverse = svg.getScreenCTM().inverse();
    const viewBox = svg.viewBox.baseVal;
    const nodes = [...svg.querySelectorAll('.node')].map(node => {
      const rect = node.querySelector('.node-card').getBBox();
      const matrix = node.getScreenCTM();
      const corners = [
        new DOMPoint(rect.x, rect.y), new DOMPoint(rect.x + rect.width, rect.y),
        new DOMPoint(rect.x, rect.y + rect.height), new DOMPoint(rect.x + rect.width, rect.y + rect.height),
      ].map(point => point.matrixTransform(matrix).matrixTransform(inverse));
      const xs = corners.map(point => point.x), ys = corners.map(point => point.y);
      const box = { x: Math.min(...xs), y: Math.min(...ys), right: Math.max(...xs), bottom: Math.max(...ys) };
      return { id: node.dataset.node, x: box.x, y: box.y,
        width: box.right - box.x, height: box.bottom - box.y };
    }).sort((a, b) => a.id.localeCompare(b.id));
    const workspace = document.querySelector('.workspace');
    return { viewBox: { x: viewBox.x, y: viewBox.y, width: viewBox.width, height: viewBox.height }, nodes,
      viewport: { innerWidth, documentWidth: document.documentElement.scrollWidth,
        workspaceWidth: workspace.clientWidth, workspaceScrollWidth: workspace.scrollWidth,
        scrollTop: workspace.scrollTop },
      svgRect: (() => { const r = svg.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height }; })() };
  });
}

function maxGeometryDelta(expected, actual) {
  if (!expected || expected.nodes.length !== actual.nodes.length) return Infinity;
  const actualById = new Map(actual.nodes.map(node => [node.id, node]));
  let max = 0;
  for (const node of expected.nodes) {
    const other = actualById.get(node.id);
    if (!other) return Infinity;
    for (const key of ['x', 'y', 'width', 'height']) max = Math.max(max, Math.abs(node[key] - other[key]));
  }
  return max;
}

async function screenshotCanvas(page, path) {
  const workspace = page.locator('.workspace');
  const scrollTop = await workspace.evaluate(element => element.scrollTop);
  const expanded = await page.addStyleTag({ content: `
    html, body { height: auto !important; min-height: 0 !important; overflow: visible !important; }
    .workspace { height: auto !important; min-height: 0 !important; flex: 0 0 auto !important; overflow: visible !important; }
    #canvas { min-height: 0 !important; }
    #layout-meta, #layout-notice, #module-details { visibility: hidden !important; }
  ` });
  try {
    await page.locator('#canvas svg').screenshot({ path, animations: 'disabled', scale: 'device' });
  } finally {
    await expanded.evaluate(element => element.remove());
    await workspace.evaluate((element, top) => { element.scrollTop = top; }, scrollTop);
  }
}

try {
  for (const browserSpec of config.browsers) {
    let browser;
    try {
      browser = await chromium.launch({ headless: true,
        ...(browserSpec.executable ? { executablePath: browserSpec.executable } : {}) });
      browserAvailability.push({ name: browserSpec.name, available: true, version: browser.version() });
    } catch (error) {
      browserAvailability.push({ name: browserSpec.name, available: false, error: String(error) });
      continue;
    }
    for (const protocol of (config.protocols || ['file', 'http'])) {
      for (const state of ['fresh', 'stale', 'invalid']) {
        const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 2 });
        const staleKeys = [
          `architecture-diagram-layout:v2:${payload.root}:${payload.root}`,
          `architecture-diagram-layout:${payload.root}:${payload.root}:stale-hash`,
        ];
        const currentLayoutHash = payload.views[payload.root].layoutHash;
        const invalidKey = `architecture-diagram-layout:${payload.root}:${payload.root}:${currentLayoutHash}`;
        staleKeys.push(invalidKey);
        if (state === 'stale' || state === 'invalid') {
          await context.addInitScript(({ keys, invalid, layoutHash, mode, nodeId }) => {
            try {
              if (mode === 'stale') for (const key of keys) localStorage.setItem(key, JSON.stringify({
                layoutHash: 'stale-hash', positions: {} }));
              if (mode === 'invalid') localStorage.setItem(invalid, JSON.stringify({ layoutHash,
                positions: { [nodeId]: { dx: -10000, dy: 0 } } }));
            }
            catch (_) { window.__staleSeedBlocked = true; }
          }, { keys: staleKeys, invalid: invalidKey, layoutHash: currentLayoutHash, mode: state,
            nodeId: drillNode.id });
        }
        const page = await context.newPage();
        const pageErrors = [];
        page.on('pageerror', error => pageErrors.push(String(error)));
        page.on('console', message => { if (message.type() === 'error') pageErrors.push(message.text()); });
        await page.goto(protocol === 'file' ? pathToFileURL(config.htmlPath).href : httpUrl,
          { waitUntil: 'load', timeout: 30000 });
        await page.locator('#canvas svg').waitFor();
        const hash = await page.locator('#layout-hash').textContent();
        if (!hash || hash.trim().length !== 6) throw new Error(`${browserSpec.name}/${protocol}/${state}: layout hash missing`);
        const hashInToolbar = await page.locator('#layout-meta').evaluate(element => element.parentElement?.classList.contains('toolbar'));
        if (!hashInToolbar) throw new Error(`${browserSpec.name}/${protocol}/${state}: layout hash is not in the toolbar`);
        const storageCheck = await page.evaluate(keys => {
          try { return { available: true, remainingStaleKeys: keys.filter(key => localStorage.getItem(key) !== null),
            keys: Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index)) }; }
          catch (error) { return { available: false, error: String(error) }; }
        }, staleKeys);
        if (state === 'fresh' && storageCheck.available && storageCheck.keys.length) {
          throw new Error(`${browserSpec.name}/${protocol}: fresh context has localStorage entries`);
        }
        if ((state === 'stale' || state === 'invalid') && storageCheck.available && storageCheck.remainingStaleKeys.length) {
          throw new Error(`${browserSpec.name}/${protocol}/${state}: stale or invalid layout keys were not discarded`);
        }
        const notice = (await page.locator('#layout-notice').textContent())?.trim() || '';
        if ((state === 'stale' || state === 'invalid') && storageCheck.available && notice !== '布局已更新，已恢复自动布局') {
          throw new Error(`${browserSpec.name}/${protocol}: stale-state notice mismatch: ${notice}`);
        }
        const widthResults = [];
      for (const width of viewportWidths) {
          await page.setViewportSize({ width, height: 900 });
          await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
          const snapshot = await geometry(page);
          if (snapshot.viewport.documentWidth > width || snapshot.viewport.workspaceScrollWidth > snapshot.viewport.workspaceWidth) {
            throw new Error(`${browserSpec.name}/${protocol}/${state}/${width}: horizontal overflow`);
          }
          const rounded = JSON.parse(JSON.stringify(snapshot.nodes.map(node => Object.fromEntries(
            Object.entries(node).map(([key, value]) => [key, key === 'id' ? value : Number(value.toFixed(3))])))));
          const localDelta = referenceGeometry ? maxGeometryDelta(referenceGeometry, { nodes: rounded }) : 0;
          if (referenceGeometry && localDelta > 0.001) {
            throw new Error(`${browserSpec.name}/${protocol}/${state}/${width}: SVG bbox changed by ${localDelta}px`);
          }
          if (!referenceGeometry) referenceGeometry = { nodes: rounded };
          widthResults.push({ width, localGeometryMaxDeltaPx: localDelta, svgRect: snapshot.svgRect,
            documentWidth: snapshot.viewport.documentWidth, workspaceWidth: snapshot.viewport.workspaceWidth,
            workspaceScrollWidth: snapshot.viewport.workspaceScrollWidth });
        }

        // Compare images only after responsive geometry checks, at one canonical viewport.
        // This avoids treating browser font/line rasterization at different CSS scales as layout drift.
        await page.setViewportSize({ width: 1600, height: 900 });
        await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
        const canonicalSvgRect = await page.locator('#canvas svg').evaluate(element => {
          const rect = element.getBoundingClientRect();
          return { width: rect.width, height: rect.height };
        });
        const file = `${browserSpec.name}-${protocol}-${state}-canonical-1600.png`;
        const path = `${config.screenshotDir}/${file}`;
        await screenshotCanvas(page, path);
        screenshots.push({ browser: browserSpec.name, protocol, state, width: 1600,
          normalized: true, svgRect: canonicalSvgRect, path });

        let dragPersistence = null;
        if (browserSpec.name === 'Chromium' && protocol === 'file' && state === 'fresh') {
          await page.setViewportSize({ width: 1280, height: 900 });
          const horizontalNode = rootGraph.nodes.find(node => !crossCuttingIds.has(node.layer) &&
            node.drilldown && payload.views[node.drilldown]);
          const horizontal = page.locator(`[data-node="${horizontalNode.id}"]`);
          const beforeHorizontal = await horizontal.evaluate(element => {
            const matrix = element.transform.baseVal.consolidate()?.matrix;
            return { x: matrix?.e || 0, y: matrix?.f || 0 };
          });
          const box = await horizontal.boundingBox();
          await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
          await page.mouse.down();
          await page.mouse.move(box.x + box.width / 2 + 4, box.y + box.height / 2, { steps: 2 });
          await page.mouse.up();
          const afterHorizontal = await horizontal.evaluate(element => {
            const matrix = element.transform.baseVal.consolidate()?.matrix;
            return { x: matrix?.e || 0, y: matrix?.f || 0 };
          });
          const scale = (await page.locator('#canvas svg').evaluate(element =>
            element.getBoundingClientRect().width / element.viewBox.baseVal.width));
          const horizontalSaved = await page.evaluate(key => JSON.parse(localStorage.getItem(key) || 'null'),
            `architecture-diagram-layout:${payload.root}:${payload.root}:${currentLayoutHash}`);
          const horizontalOffset = horizontalSaved?.positions?.[horizontalNode.id];
          const horizontalXError = Math.abs((afterHorizontal.x - beforeHorizontal.x) - 4 / scale);
          const horizontalYError = Math.abs(afterHorizontal.y - beforeHorizontal.y);
          if (!horizontalOffset || !Number.isFinite(horizontalOffset.dx) || !Number.isFinite(horizontalOffset.dy) ||
              Object.hasOwn(horizontalOffset, 'x') || Object.hasOwn(horizontalOffset, 'y') ||
              horizontalXError > 0.75 || horizontalYError > 0.75) {
            throw new Error(`${browserSpec.name}/${protocol}: drag coordinate conversion or relative persistence failed: ` +
              JSON.stringify({ beforeHorizontal, afterHorizontal, horizontalOffset, scale,
                horizontalXError, horizontalYError, storageKeys:
                await page.evaluate(() => Object.keys(localStorage)) }));
          }
          await page.locator('#reset').click();
          const resetHorizontal = await horizontal.evaluate(element => {
            const matrix = element.transform.baseVal.consolidate()?.matrix;
            return { x: matrix?.e || 0, y: matrix?.f || 0 };
          });
          const horizontalResetStorage = await page.evaluate(key => localStorage.getItem(key),
            `architecture-diagram-layout:${payload.root}:${payload.root}:${currentLayoutHash}`);
          if (Math.abs(resetHorizontal.x - beforeHorizontal.x) >= 0.001 ||
              Math.abs(resetHorizontal.y - beforeHorizontal.y) >= 0.001 || horizontalResetStorage !== null) {
            throw new Error(`${browserSpec.name}/${protocol}: reset did not restore automatic layout`);
          }

          const vertical = page.locator(`[data-node="${drillNode.id}"]`);
          const beforeVertical = await vertical.evaluate(element => {
            const matrix = element.transform.baseVal.consolidate()?.matrix;
            return { x: matrix?.e || 0, y: matrix?.f || 0 };
          });
          const verticalBox = await vertical.boundingBox();
          await page.mouse.move(verticalBox.x + verticalBox.width / 2, verticalBox.y + verticalBox.height / 2);
          await page.mouse.down();
          await page.mouse.move(verticalBox.x + verticalBox.width / 2, verticalBox.y + verticalBox.height / 2 + 3, { steps: 2 });
          await page.mouse.up();
          const afterVertical = await vertical.evaluate(element => {
            const matrix = element.transform.baseVal.consolidate()?.matrix;
            return { x: matrix?.e || 0, y: matrix?.f || 0 };
          });
          const verticalSaved = await page.evaluate(key => JSON.parse(localStorage.getItem(key) || 'null'),
            `architecture-diagram-layout:${payload.root}:${payload.root}:${currentLayoutHash}`);
          const verticalOffset = verticalSaved?.positions?.[drillNode.id];
          const verticalXError = Math.abs(afterVertical.x - beforeVertical.x);
          const verticalYError = Math.abs((afterVertical.y - beforeVertical.y) - 3 / scale);
          if (!verticalOffset || verticalXError > 0.75 || verticalYError > 0.75 ||
              !Number.isFinite(verticalOffset.dy) || Object.hasOwn(verticalOffset, 'y')) {
            throw new Error(`${browserSpec.name}/${protocol}: vertical drag coordinate conversion failed: ` +
              JSON.stringify({ beforeVertical, afterVertical, verticalOffset, scale, verticalXError, verticalYError }));
          }
          await page.locator('#reset').click();
          const resetVertical = await vertical.evaluate(element => {
            const matrix = element.transform.baseVal.consolidate()?.matrix;
            return { x: matrix?.e || 0, y: matrix?.f || 0 };
          });
          const verticalResetStorage = await page.evaluate(key => localStorage.getItem(key),
            `architecture-diagram-layout:${payload.root}:${payload.root}:${currentLayoutHash}`);
          const resetWorks = Math.abs(resetVertical.x - beforeVertical.x) < 0.001 &&
            Math.abs(resetVertical.y - beforeVertical.y) < 0.001 && verticalResetStorage === null;
          if (!resetWorks) throw new Error(`${browserSpec.name}/${protocol}: reset after vertical drag failed`);
          dragPersistence = { horizontal: { before: beforeHorizontal, after: afterHorizontal,
            offset: horizontalOffset, deltaXError: horizontalXError },
            vertical: { before: beforeVertical, after: afterVertical,
              offset: verticalOffset, deltaYError: verticalYError }, expectedScale: scale, resetWorks };
        }

        await page.setViewportSize({ width: 1440, height: 580 });
        const workspace = page.locator('.workspace');
        await workspace.evaluate(element => { element.scrollTop = element.scrollHeight; });
        const beforeDrillScroll = await workspace.evaluate(element => element.scrollTop);
        if (beforeDrillScroll <= 0) throw new Error(`${browserSpec.name}/${protocol}/${state}: could not establish drilldown scroll state`);
        await page.locator(`[data-node="${drillNode.id}"] .drill-icon`).click();
        const childId = await page.locator('#canvas svg').getAttribute('aria-label');
        const afterDrillScroll = await workspace.evaluate(element => element.scrollTop);
        if (childId !== payload.views[drillNode.drilldown].graph.title || afterDrillScroll !== 0) {
          throw new Error(`${browserSpec.name}/${protocol}/${state}: drilldown did not reset scroll to top`);
        }
        const childHash = (await page.locator('#layout-hash').textContent())?.trim();
        await page.setViewportSize({ width: 1600, height: 900 });
        let childScreenshot = null;
        if (browserSpec.name === 'Chromium' && protocol === 'file' && state === 'fresh') {
          childScreenshot = `${config.screenshotDir}/drilldown-chromium-file-fresh-1440.png`;
          await screenshotCanvas(page, childScreenshot);
          screenshots.push({ browser: browserSpec.name, protocol, state, width: 1440, view: 'drilldown', path: childScreenshot });
        }
        await page.locator('#back').click();
        const afterBackScroll = await workspace.evaluate(element => element.scrollTop);
        if (afterBackScroll !== 0 || await page.locator('#canvas svg').getAttribute('aria-label') !== rootGraph.title) {
          throw new Error(`${browserSpec.name}/${protocol}/${state}: returning to main view failed`);
        }
        if (pageErrors.length) throw new Error(`${browserSpec.name}/${protocol}/${state}: page errors: ${pageErrors.join('; ')}`);
        results.push({ browser: browserSpec.name, protocol, state,
          storageAvailable: storageCheck.available, notice, layoutHash: hash.trim(), hashInToolbar, childLayoutHash: childHash,
          widths: widthResults, drilldown: { nodeId: drillNode.id, childId: drillNode.drilldown,
            scrollBefore: beforeDrillScroll, scrollAfter: afterDrillScroll, scrollAfterBack: afterBackScroll,
            screenshot: childScreenshot }, dragPersistence, pageErrors });
        await context.close();
      }
    }
    await browser.close();
  }
} finally {
  await new Promise(resolve => server.close(resolve));
}

const report = { browserAvailability, viewportWidths, viewportHeight: 900, deviceScaleFactor: 2,
  protocols: config.protocols || ['file', 'http'], states: ['fresh', 'stale', 'invalid'], screenshotSource: '交互页面的 #canvas svg locator',
  pixelComparisonViewport: { width: 1600, height: 900 },
  geometryCoordinateSystem: 'SVG viewBox 坐标，由节点屏幕边界经 getScreenCTM().inverse() 还原',
  fixture: config.htmlPath, rootId: payload.root, rootTitle: rootGraph.title,
  drilldownNode: drillNode.id, results, screenshots };
await writeFile(reportPath, JSON.stringify(report, null, 2) + '\n', 'utf8');
console.log(JSON.stringify({ browserAvailability, combinations: results.length, screenshots: screenshots.length,
  reportPath }, null, 2));
