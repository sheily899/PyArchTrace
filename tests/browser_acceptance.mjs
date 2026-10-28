import { pathToFileURL } from 'node:url';
import { mkdir, readFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
const [htmlPath, exportPath, browserPath, playwrightModule, childScreenshot] = process.argv.slice(2);
const { chromium } = await import(pathToFileURL(playwrightModule).href);
const downloadsPath = join(dirname(exportPath), 'browser-downloads');
await mkdir(downloadsPath, { recursive: true });
const browser = await chromium.launch({ headless: true, downloadsPath, ...(browserPath ? { executablePath: browserPath } : {}) });
const context = await browser.newContext({ acceptDownloads: 'accept', viewport: { width: 1600, height: 1000 } });
const page = await context.newPage();
const errors = [];
page.on('pageerror', error => errors.push(String(error)));
await page.goto(pathToFileURL(htmlPath).href, { waitUntil: 'load' });
await page.locator('#canvas svg').waitFor();
const initialNodes = await page.locator('#canvas .node').count();
const visibleText = await page.locator('body').innerText();
if (/[A-Za-z]{2,}/.test(visibleText)) throw new Error('图面或工具栏出现英文代码痕迹');
if (await page.locator('#canvas .node .status').count()) throw new Error('模块卡片不应显示状态徽标');
const diagramText = await page.locator('#canvas').innerText();
if (diagramText.includes('已接入') || diagramText.includes('部分接入')) throw new Error('模块卡片出现接入状态标签');

await page.locator('[data-node="intent-recognition"]').click();
if (await page.locator('#detailTitle').textContent() !== '意图识别') throw new Error('模块详情抽屉未展示职责信息');
if (await page.locator('#detailStatus').textContent() !== '已实现') throw new Error('实现情况未在详情中展示');
await page.locator('#openChild').click();
const childTitle = await page.locator('#canvas svg').getAttribute('aria-label');
const childNodes = await page.locator('#canvas .node').count();
if (childTitle !== '意图识别细节' || childNodes !== 5) throw new Error('下钻子图未按预期展示');
if (childScreenshot) await page.locator('#canvas svg').screenshot({ path: childScreenshot });
await page.locator('#crumb').click();
if (await page.locator('#canvas .node').count() !== initialNodes) throw new Error('面包屑未能返回主图');

await page.locator('[data-node="agent-orchestration"]').click();
page.once('dialog', dialog => dialog.accept('intent-detail'));
await page.locator('#setDrilldown').click();
await page.locator('[data-node="agent-orchestration"]').click();
if (await page.locator('#openChild').isHidden()) throw new Error('给模块添加下钻关系失败');
await page.locator('#openChild').click();
if (await page.locator('#canvas svg').getAttribute('aria-label') !== '意图识别细节') throw new Error('新设置的下钻关系不可进入');
await page.locator('#crumb').click();
await page.locator('[data-node="agent-orchestration"]').click();
page.once('dialog', dialog => dialog.accept('0'));
await page.locator('#setDrilldown').click();
await page.locator('[data-node="agent-orchestration"]').click();
if (!(await page.locator('#openChild').isHidden())) throw new Error('移除下钻关系失败');
const childGraph = {schemaVersion:1,id:'browser-child',title:'新增子图',type:'flow',direction:'LR',
  layers:[{id:'start',name:'输入'},{id:'end',name:'输出'}],
  nodes:[{id:'a',layer:'start',title:'请求内容',desc:'用户提交信息',status:'implemented'},
    {id:'b',layer:'end',title:'处理结果',desc:'返回业务结果',status:'implemented'}],
  edges:[{id:'ab',from:'a',to:'b',label:'处理请求',kind:'call'}],subDiagrams:[]};
await page.locator('[data-node="agent-orchestration"]').click();
page.once('dialog', dialog => dialog.accept(JSON.stringify(childGraph)));
await page.locator('#setDrilldown').click();
await page.locator('[data-node="agent-orchestration"]').click();
await page.locator('#openChild').click();
if (await page.locator('#canvas svg').getAttribute('aria-label') !== '新增子图') throw new Error('粘贴 JSON 创建下钻子图失败');
await page.locator('#crumb').click();
await page.locator('[data-node="agent-orchestration"]').click();
page.once('dialog', dialog => dialog.accept('0'));
await page.locator('#setDrilldown').click();

await page.locator('#edit').click();
const movable = page.locator('[data-node="intent-recognition"]');
const before = await movable.getAttribute('transform');
const box = await movable.boundingBox();
await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
await page.mouse.down();
await page.mouse.move(box.x + box.width / 2 + 40, box.y + box.height / 2 + 24, { steps: 4 });
await page.mouse.up();
const after = await page.locator('[data-node="intent-recognition"]').getAttribute('transform');
if (before === after) throw new Error('拖动编辑没有改变模块位置');
const persistence = await page.evaluate(() => { try { const value=localStorage.getItem('architecture-diagram:shopcare-main'); return {length:value?.length||0,keys:Object.keys(localStorage)} } catch(error) { return {error:String(error)} } });
console.log('本地状态检查：' + JSON.stringify(persistence));
await page.reload({ waitUntil: 'load' });
const restoredPosition = await page.locator('[data-node="intent-recognition"]').getAttribute('transform');
if (restoredPosition !== after) throw new Error('重新打开页面没有恢复本地编辑状态');
await page.locator('#edit').click();

const downloadPromise = page.waitForEvent('download');
await page.locator('#exportJson').click();
const download = await downloadPromise;
const downloadFailure = await download.failure();
if (downloadFailure) throw new Error(`JSON导出下载被浏览器取消：${downloadFailure}`);
await download.saveAs(exportPath);
await page.locator('#importJson').setInputFiles(exportPath);
await page.waitForTimeout(250);
const imported = await page.locator('[data-node="intent-recognition"]').getAttribute('transform');
if (imported !== after) throw new Error('导出再导入没有恢复固定位置');

const promptValues = ['临时模块', '1', '用于验证新增能力'];
page.on('dialog', async dialog => dialog.accept(promptValues.shift() ?? ''));
await page.locator('#addNode').click();
await page.locator('[data-title="临时模块"]').waitFor();
if (await page.locator('#canvas .node').count() !== initialNodes + 1) throw new Error('新增模块未出现在图上');

const edgeValues = ['1', '2', '临时关系'];
page.removeAllListeners('dialog');
page.on('dialog', async dialog => dialog.accept(edgeValues.shift() ?? ''));
await page.locator('#addEdge').click();
await page.locator('[data-edge^="new-edge-"]').waitFor();
const addedEdge = page.locator('[data-edge^="new-edge-"]').first();
await addedEdge.click();
await page.locator('#deleteNode').click();
if (await page.locator('[data-edge^="new-edge-"]').count() !== 0) throw new Error('删除选中连线失败');

await page.locator('[data-node^="new-node-"]').click();
await page.locator('#deleteNode').click();
if (await page.locator('#canvas .node').count() !== initialNodes) throw new Error('删除选中模块失败');
const textValues = ['临时标题', '临时说明'];
page.removeAllListeners('dialog');
page.on('dialog', async dialog => dialog.accept(textValues.shift() ?? ''));
await page.locator('[data-node="intent-recognition"]').dblclick();
await page.locator('[data-title="临时标题"]').waitFor();
const svgPath = join(dirname(exportPath), 'browser-export.svg');
const svgDownloadPromise = page.waitForEvent('download');
await page.locator('#exportSvg').click();
await (await svgDownloadPromise).saveAs(svgPath);
if (!(await readFile(svgPath, 'utf8')).includes('<svg')) throw new Error('SVG 导出内容无效');
const pngPath = join(dirname(exportPath), 'browser-export.png');
const pngDownloadPromise = page.waitForEvent('download');
await page.locator('#exportPng').click();
await (await pngDownloadPromise).saveAs(pngPath);
const pngHeader = await readFile(pngPath);
if (pngHeader.subarray(0, 8).toString('hex') !== '89504e470d0a1a0a') throw new Error('PNG 导出内容无效');
await page.locator('#reset').click();
if (await page.locator('#canvas .node').count() !== initialNodes) throw new Error('一键重置失败');
if (errors.length) throw new Error(`浏览器页面错误：${errors.join('; ')}`);
console.log(JSON.stringify({ ok: true, initialNodes, childNodes, dragChanged: before !== after, addDeleteNodeEdge: true,
  importExportPosition: true, svgPngExport: true, localStorageRestore: true,
  drilldownAddRemoveCreate: true, textEdit: true,
  visibleEnglish: false, pageErrors: errors }, null, 2));
await browser.close();
