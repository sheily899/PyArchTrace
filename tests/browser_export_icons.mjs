import assert from 'node:assert/strict';
import { mkdir, readFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { pathToFileURL } from 'node:url';

const [htmlPath, svgPath, pngPath, modulePath, executable] = process.argv.slice(2);
if (!htmlPath || !svgPath || !pngPath || !modulePath) {
  throw new Error('Usage: browser_export_icons.mjs html svg png playwright-module [browser]');
}
const { chromium } = await import(pathToFileURL(modulePath).href);
const downloadsPath = join(dirname(svgPath), 'browser-downloads');
await mkdir(downloadsPath, { recursive: true });
const browser = await chromium.launch({ headless: true, downloadsPath, ...(executable ? { executablePath: executable } : {}) });
try {
  const context = await browser.newContext({ acceptDownloads: 'accept' });
  const page = await context.newPage();
  await page.goto(pathToFileURL(htmlPath).href, { waitUntil: 'load' });
  assert.ok(await page.locator('#canvas .drill-icon').count() > 0, '交互页应显示下钻图标');

  const [svgDownload] = await Promise.all([
    page.waitForEvent('download'), page.locator('#exportSvg').click(),
  ]);
  await svgDownload.saveAs(svgPath);
  const exportedSvg = await readFile(svgPath, 'utf8');
  assert.match(exportedSvg, /<svg[\s>]/, 'SVG 下载应有效');
  assert.doesNotMatch(exportedSvg, /class="drill-icon"/, '总架构图 SVG 导出不得包含下钻图标');
  assert.ok(await page.locator('#canvas .drill-icon').count() > 0, '导出不能改变交互页面');

  const [pngDownload] = await Promise.all([
    page.waitForEvent('download'), page.locator('#exportPng').click(),
  ]);
  await pngDownload.saveAs(pngPath);
  const png = await readFile(pngPath);
  assert.equal(png.subarray(0, 8).toString('hex'), '89504e470d0a1a0a', 'PNG 下载应有效');
} finally {
  await browser.close();
}
