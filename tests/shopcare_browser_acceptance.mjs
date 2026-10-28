import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { pathToFileURL } from 'node:url';

const [htmlPath, browserPath, playwrightModule, screenshotPath] = process.argv.slice(2);
assert.ok(htmlPath && playwrightModule, 'Usage: shopcare_browser_acceptance.mjs html [browser] playwright-module [screenshot]');
const { chromium } = await import(pathToFileURL(playwrightModule).href);
const downloadsPath = join(dirname(htmlPath), 'browser-downloads');
await mkdir(downloadsPath, { recursive: true });
const browser = await chromium.launch({ headless: true, downloadsPath, ...(browserPath ? { executablePath: browserPath } : {}) });
const context = await browser.newContext({ acceptDownloads: 'accept', viewport: { width: 2200, height: 1500 } });
const page = await context.newPage();
const errors = [];
page.on('pageerror', error => errors.push(String(error)));

async function inspectGeometry() {
  return page.locator('#canvas svg').evaluate(svg => {
    const routeMode=svg.dataset.routeMode,direction=svg.dataset.direction;
    const nodes = [...svg.querySelectorAll('.node')].map(el => {
      const m = el.transform.baseVal.consolidate()?.matrix;
      const card = el.querySelector('.node-card');
      return {id:el.dataset.node,layer:el.dataset.layer,x:Number(m?.e||0),y:Number(m?.f||0),
        w:Number(card.getAttribute('width')),h:Number(card.getAttribute('height'))};
    });
    const laneById=new Map([...svg.querySelectorAll('.layer')].map(layer=>{
      const rect=layer.querySelector('rect');return [layer.dataset.layer,{x:Number(rect.getAttribute('x')),y:Number(rect.getAttribute('y')),w:Number(rect.getAttribute('width')),h:Number(rect.getAttribute('height'))}];
    }));
    const header=routeMode==='hardcoded-detail'?56:58;
    const outOfLayer=nodes.filter(node=>{const lane=laneById.get(node.layer);return !lane||node.x<lane.x||node.y<lane.y+header||node.x+node.w>lane.x+lane.w||node.y+node.h>lane.y+lane.h}).map(node=>node.id);
    const byId = new Map(nodes.map(node => [node.id,node]));
    const edges = [...svg.querySelectorAll('.edge')];
    const routes = edges.map(edge => {
      const path = edge.querySelector('.edge-line').getAttribute('d');
      const shaftPoints = path.replace(/^M\s*/,'').split(/\s+L\s+/).map(pair => pair.trim().split(/[ ,]+/).map(Number));
      const points=shaftPoints.map(point=>[...point]);
      if(edge.dataset.showMarker!=='false')points.push([Number(edge.dataset.arrowTipX),Number(edge.dataset.arrowTipY)]);
      return {id:edge.dataset.edge,from:edge.dataset.from,to:edge.dataset.to,kind:edge.dataset.kind,
        groupId:edge.dataset.groupId,groupPattern:edge.dataset.groupPattern,showMarker:edge.dataset.showMarker!=='false',points,shaftPoints};
    });
    const badAngles = routes.filter(route => route.points.some((p,i) => i>0 && p[0]!==route.points[i-1][0] && p[1]!==route.points[i-1][1])).map(route=>route.id);
    const tooManyBends=routes.filter(route=>route.points.length-(route.showMarker?3:2)>2).map(route=>route.id);
    const badAnchors=[];
    const badPortAxes=[],badStubLengths=[];
    const onCenterEdge=(point,node)=>[
      [node.x+node.w/2,node.y],[node.x+node.w/2,node.y+node.h],[node.x,node.y+node.h/2],[node.x+node.w,node.y+node.h/2]
    ].some(([x,y])=>Math.abs(point[0]-x)<.2&&Math.abs(point[1]-y)<.2);
    for(const route of routes){const a=byId.get(route.from),b=byId.get(route.to);if(!a||!b)continue;
      const groupBus=route.groupId?svg.querySelector(`[data-edge-group="${CSS.escape(route.groupId)}"]`):null;
      const busPoints=groupBus?.getAttribute('d')?.replace(/^M\s*/,'').split(/\s+L\s+/).map(pair=>pair.trim().split(/[ ,]+/).map(Number))||[];
      const onBus=point=>busPoints.slice(1).some((last,index)=>{const first=busPoints[index];
        return first[1]===last[1]?point[1]===first[1]&&point[0]>=Math.min(first[0],last[0])&&point[0]<=Math.max(first[0],last[0]):
          first[0]===last[0]&&point[0]===first[0]&&point[1]>=Math.min(first[1],last[1])&&point[1]<=Math.max(first[1],last[1])});
      if(route.groupPattern==='fan_in'){
        if(!onCenterEdge(route.points[0],a)||!onBus(route.points.at(-1)))badAnchors.push(route.id);
      }else if(route.groupPattern==='fan_out'){
        if(!onCenterEdge(route.points.at(-1),b)||!onBus(route.points[0]))badAnchors.push(route.id);
      }else if(!onCenterEdge(route.points[0],a)||!onCenterEdge(route.points.at(-1),b))badAnchors.push(route.id);
      if(route.groupPattern==='fan_in'||route.groupPattern==='fan_out')continue;
      const acx=a.x+a.w/2,acy=a.y+a.h/2,bcx=b.x+b.w/2,bcy=b.y+b.h/2;
      const horizontal=routeMode==='architecture'?a.layer===b.layer:(Math.abs(bcx-acx)===Math.abs(bcy-acy)?direction==='LR':Math.abs(bcx-acx)>Math.abs(bcy-acy));
      const start=route.points[0],end=route.points.at(-1);
      const expectedStart=horizontal?[acx+(bcx>=acx?a.w/2:-a.w/2),acy]:[acx,acy+(bcy>=acy?a.h/2:-a.h/2)];
      const expectedEnd=horizontal?[bcx+(bcx>=acx?-b.w/2:b.w/2),bcy]:[bcx,bcy+(bcy>=acy?-b.h/2:b.h/2)];
      if(Math.abs(start[0]-expectedStart[0])>.2||Math.abs(start[1]-expectedStart[1])>.2||Math.abs(end[0]-expectedEnd[0])>.2||Math.abs(end[1]-expectedEnd[1])>.2)badPortAxes.push(route.id);
      if(route.shaftPoints.length>2){const first=route.shaftPoints[1],last=route.shaftPoints.at(-2),startOut=horizontal?Math.abs(first[0]-start[0]):Math.abs(first[1]-start[1]),endOut=horizontal?Math.abs(end[0]-last[0]):Math.abs(end[1]-last[1]);
        const firstParallel=horizontal?first[1]!==start[1]:first[0]!==start[0],lastParallel=horizontal?last[1]!==end[1]:last[0]!==end[0];
        if(firstParallel||lastParallel||startOut<16||endOut<16)badStubLengths.push(route.id)}
    }
    const markerIdFor=edge=>{
      const line=edge.querySelector('.edge-line'),main=edge.dataset.layerFlow==='true';
      const color=line.getAttribute('stroke').replace(/[^0-9a-f]/gi,'').toUpperCase();
      return `${main?'arrow-main-':'arrow-'}${color}`;
    };
    const missingArrowheads=edges.filter(edge=>edge.dataset.showMarker!=='false'&&edge.querySelector('.edge-line').getAttribute('marker-end')!==`url(#${markerIdFor(edge)})`).map(edge=>edge.dataset.edge);
    const badArrowheadDefinition=edges.some(edge=>{
      const main=edge.dataset.layerFlow==='true',marker=svg.querySelector(`#${markerIdFor(edge)}`);
      const expected=main?['0 0 18 14','18','14','0','M 0 0 L 18 7 L 0 14 Z']:['0 0 12 10','12','10','0','M 0 0 L 12 5 L 0 10 Z'];
      return !marker||marker.getAttribute('orient')!=='auto'||marker.getAttribute('markerUnits')!=='userSpaceOnUse'||
        marker.getAttribute('viewBox')!==expected[0]||marker.getAttribute('markerWidth')!==expected[1]||
        marker.getAttribute('markerHeight')!==expected[2]||marker.getAttribute('refX')!==expected[3]||
        edge.querySelector('.edge-line').getAttribute('stroke-linecap')!=='butt'||marker.querySelector('path')?.getAttribute('d')!==expected[4];
    });
    const badArrowShaftBase=edges.filter(edge=>edge.dataset.showMarker!=='false').some(edge=>{
      const line=edge.querySelector('.edge-line'),numbers=(line.getAttribute('d').match(/-?\d+(?:\.\d+)?/g)||[]).map(Number),main=edge.dataset.layerFlow==='true',length=main?18:12;
      if(numbers.length<4)return true;
      const baseX=Number(line.dataset.arrowShaftX),baseY=Number(line.dataset.arrowShaftY),tipX=Number(line.dataset.arrowTipX),tipY=Number(line.dataset.arrowTipY);
      const shaftX=baseX-numbers.at(-4),shaftY=baseY-numbers.at(-3),headX=tipX-baseX,headY=tipY-baseY;
      return Math.abs(numbers.at(-2)-baseX)>.11||Math.abs(numbers.at(-1)-baseY)>.11||Math.abs(Math.hypot(headX,headY)-length)>.11||Math.abs(shaftX*headY-shaftY*headX)>.11||shaftX*headX+shaftY*headY<=0;
    });
    const pathNodeCrossings=[];
    for(const route of routes)for(let i=1;i<route.points.length;i++){
      const [x1,y1]=route.points[i-1],[x2,y2]=route.points[i];
      for(const node of nodes){if(node.id===route.from||node.id===route.to)continue;
        const hit=y1===y2?y1>node.y+2&&y1<node.y+node.h-2&&Math.max(Math.min(x1,x2),node.x+2)<Math.min(Math.max(x1,x2),node.x+node.w-2):
          x1===x2?x1>node.x+2&&x1<node.x+node.w-2&&Math.max(Math.min(y1,y2),node.y+2)<Math.min(Math.max(y1,y2),node.y+node.h-2):true;
        if(hit)pathNodeCrossings.push(`${route.id}:${node.id}`);
      }
    }
    const edgeCrossings=[],overlappingRoutes=[];
    for(let i=0;i<routes.length;i++)for(let j=i+1;j<routes.length;j++){
      const left=routes[i],right=routes[j];if([left.from,left.to].some(id=>id===right.from||id===right.to))continue;
      for(let a=1;a<left.points.length;a++)for(let b=1;b<right.points.length;b++){
        const p=left.points[a-1],q=left.points[a],r=right.points[b-1],s=right.points[b];
        const ph=p[1]===q[1],rh=r[1]===s[1];
        if(ph!==rh){const h=ph?[p,q]:[r,s],v=ph?[r,s]:[p,q];if(Math.min(h[0][0],h[1][0])<v[0][0]&&v[0][0]<Math.max(h[0][0],h[1][0])&&Math.min(v[0][1],v[1][1])<h[0][1]&&h[0][1]<Math.max(v[0][1],v[1][1]))edgeCrossings.push(`${left.id}:${right.id}`)}
        else if(ph&&p[1]===r[1]){const overlap=Math.min(Math.max(p[0],q[0]),Math.max(r[0],s[0]))-Math.max(Math.min(p[0],q[0]),Math.min(r[0],s[0]));if(overlap>6)overlappingRoutes.push(`${left.id}:${right.id}`)}
        else if(!ph&&p[0]===r[0]){const overlap=Math.min(Math.max(p[1],q[1]),Math.max(r[1],s[1]))-Math.max(Math.min(p[1],q[1]),Math.min(r[1],s[1]));if(overlap>6)overlappingRoutes.push(`${left.id}:${right.id}`)}
      }
    }
    const overlaps=[];
    for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++){
      const a=nodes[i],b=nodes[j];if(a.x<b.x+b.w&&a.x+a.w>b.x&&a.y<b.y+b.h&&a.y+a.h>b.y)overlaps.push([a.id,b.id]);
    }
    const labels=[...svg.querySelectorAll('.edge-label rect')].map(rect=>({x:Number(rect.getAttribute('x')),y:Number(rect.getAttribute('y')),w:Number(rect.getAttribute('width')),h:Number(rect.getAttribute('height'))}));
    const badgeOverlaps=[...svg.querySelectorAll('.node')].flatMap(node=>{const badge=node.querySelector('.drill-icon');if(!badge)return[];const b=badge.getBoundingClientRect();return [...node.querySelectorAll('.node-title')].flatMap(title=>{const t=title.getBoundingClientRect(),vertical=t.top<b.bottom&&t.bottom>b.top;const horizontalGap=t.right<=b.left?b.left-t.right:t.left>=b.right?t.left-b.right:0;return vertical&&horizontalGap<12?[node.dataset.node]:[]})});
    const labelNodeOverlaps=labels.flatMap((label,index)=>nodes.filter(node=>label.x<node.x+node.w&&label.x+label.w>node.x&&label.y<node.y+node.h&&label.y+label.h>node.y).map(node=>`${index}:${node.id}`));
    const labelOverlaps=[];for(let i=0;i<labels.length;i++)for(let j=i+1;j<labels.length;j++){const a=labels[i],b=labels[j];if(a.x<b.x+b.w&&a.x+a.w>b.x&&a.y<b.y+b.h&&a.y+a.h>b.y)labelOverlaps.push([i,j])}
    const labelPathGaps=[...svg.querySelectorAll('.edge')].filter(edge=>edge.dataset.kind!=='governance'&&edge.querySelector('.edge-label rect')).map(edge=>{
      const rect=edge.querySelector('.edge-label rect');
      const box={x:Number(rect.getAttribute('x')),y:Number(rect.getAttribute('y')),w:Number(rect.getAttribute('width')),h:Number(rect.getAttribute('height'))};
      const points=edge.querySelector('.edge-line').getAttribute('d').replace(/^M\s*/,'').split(/\s+L\s+/).map(pair=>pair.trim().split(/[ ,]+/).map(Number));
      const gaps=points.slice(1).flatMap((p,i)=>{const q=points[i];
        if(p[1]===q[1]&&Math.max(Math.min(p[0],q[0]),box.x)<Math.min(Math.max(p[0],q[0]),box.x+box.w))return [p[1]<box.y?box.y-p[1]:p[1]>box.y+box.h?p[1]-(box.y+box.h):0];
        if(p[0]===q[0]&&Math.max(Math.min(p[1],q[1]),box.y)<Math.min(Math.max(p[1],q[1]),box.y+box.h))return [p[0]<box.x?box.x-p[0]:p[0]>box.x+box.w?p[0]-(box.x+box.w):0];
        return [];
      });
      return {id:edge.dataset.edge,gap:gaps.length?Math.min(...gaps):Infinity};
    });
    return {nodes,routes,badAngles,tooManyBends,badAnchors,badPortAxes,badStubLengths,missingArrowheads,badArrowheadDefinition,badArrowShaftBase,pathNodeCrossings,edgeCrossings,overlappingRoutes,overlaps,outOfLayer,labelNodeOverlaps,labelOverlaps,badgeOverlaps,
      routeMode,direction,labelPathGaps,cardHeights:nodes.map(node=>node.h),text:[...svg.querySelectorAll('text')].map(node=>node.textContent).join(' ')};
  });
}

try {
  await page.goto(pathToFileURL(htmlPath).href, { waitUntil: 'load' });
  await page.locator('#canvas svg').waitFor();
  assert.equal(await page.locator('#canvas .node').count(),25,'总览应展示已确认的 25 个模块');
  assert.equal(await page.locator('#canvas .edge[data-layer-flow="true"]').count(),4,'总览只展示四个相邻层间流向');
  assert.equal(await page.locator('#canvas .edge[data-layer-flow="false"]').count(),0,'总览不得出现模块到模块的关系线');
  assert.equal(await page.locator('.toolbar button').count(),4,'工具栏应包含返回、导出和重置按钮');
  assert.deepEqual(await page.locator('.toolbar button:visible').allTextContents(),['导出矢量图','导出高清图片','重置布局']);
  for(const forbidden of ['addNode','addEdge','deleteNode','setDrilldown','importJson','exportJson','details','zoomIn','zoomOut','openChild','crumb'])
    assert.equal(await page.locator(`#${forbidden}`).count(),0,`不应暴露交互控件 ${forbidden}`);
  assert.ok(await page.locator('.drill-icon').count()>0,'存在子图的模块应显示轻量下钻图标');
  assert.equal(await page.locator('#module-details').isVisible(),false,'详情面板默认隐藏，不干扰图面');

  await page.locator('[data-node="intent"]').click();
  assert.equal(await page.locator('#module-details').isVisible(),true,'点击模块应显示结构化详情面板');
  assert.match(await page.locator('#module-details').innerText(),/职责|输入|输出/);
  await page.locator('[data-node="intent"] .drill-icon').click();
  assert.equal(await page.locator('#canvas svg').getAttribute('aria-label'),'意图识别三路处理细节','点击意图识别应进入其细节图');
  assert.equal(await page.locator('#canvas .node').count(),8,'意图识别细节图应展示三路处理及汇总模块');
  assert.equal(await page.locator('#back').isVisible(),true,'子图中应显示返回上级');
  assert.equal(await page.locator('#back').innerText(),'返回上一级','返回操作应有明确文字');
  assert.match(await page.locator('#canvas').innerText(),/关键词与模式匹配/);
  assert.match(await page.locator('#canvas').innerText(),/语言模型语义分类/);
  assert.match(await page.locator('#canvas').innerText(),/向量样例相似度/);
  const intentGeometry=await inspectGeometry();
  assert.deepEqual(intentGeometry.badAngles,[],'下钻图连线不得出现斜线');
  assert.deepEqual(intentGeometry.badAnchors,[],'下钻图连线端点须吸附模块边缘');
  assert.deepEqual(intentGeometry.badPortAxes,[],'下钻图必须按纵向布局使用上下端口');
  assert.deepEqual(intentGeometry.badStubLengths,[],'下钻图折线路径必须先沿端口法线外引 16px');
  assert.deepEqual(intentGeometry.tooManyBends,[],'下钻图连线折点应受控');
  assert.deepEqual(intentGeometry.overlaps,[],'下钻图模块不得重叠');
  assert.deepEqual(intentGeometry.pathNodeCrossings,[],'下钻图连线不得穿越无关模块');
  assert.deepEqual(intentGeometry.edgeCrossings,[],'下钻图无关连线不得交叉');
  assert.deepEqual(intentGeometry.labelNodeOverlaps,[],'下钻图标签不得压住模块');
  assert.deepEqual(intentGeometry.labelOverlaps,[],'下钻图标签不得互相重叠');
  await page.setViewportSize({width:2200,height:4000});
  if(screenshotPath)await page.locator('#canvas svg').screenshot({path:join(dirname(screenshotPath),'intent-detail-preview.png')});
  await page.locator('[data-node="i-fast"]').click();
  await page.locator('[data-node="i-fast"] .drill-icon').click();
  assert.equal(await page.locator('#canvas svg').getAttribute('aria-label'),'特异规则命中后的快速返回','子图内部仍应支持继续下钻');
  await page.locator('#back').click();
  assert.equal(await page.locator('#canvas svg').getAttribute('aria-label'),'意图识别三路处理细节','返回应回到上一级子图');
  await page.locator('#back').click();
  assert.equal(await page.locator('#canvas svg').getAttribute('aria-label'),'智能客服运行时分层架构','再次返回应回到主图');

  const viewPayload=JSON.parse(await page.locator('#payload').textContent());
  const visitedViews=new Set([viewPayload.root]);
  async function inspectNestedViews(viewId){
    const view=viewPayload.views[viewId],graph=view.graph;
    for(const node of graph.nodes){
      if(!node.drilldown||visitedViews.has(node.drilldown))continue;
      visitedViews.add(node.drilldown);
      await page.locator(`[data-node="${node.id}"] .drill-icon`).click();
      const child=viewPayload.views[node.drilldown];
      assert.equal(await page.locator('#canvas svg').getAttribute('aria-label'),child.graph.title,`下钻节点 ${node.id} 应打开指定视图`);
      assert.equal(await page.locator('#back').isVisible(),true,`视图 ${node.drilldown} 应显示返回上一级`);
      const geometry=await inspectGeometry();
      assert.equal(await page.evaluate(() => hardcodedPorts),true,`视图 ${node.drilldown} 浏览器路由必须启用硬编码端口模式`);
      assert.equal(geometry.routeMode,'hardcoded-detail',`视图 ${node.drilldown} 应启用硬编码端口路由`);
      assert.deepEqual(geometry.badAngles,[],`视图 ${node.drilldown} 不得有斜线`);
      assert.deepEqual(geometry.badAnchors,[],`视图 ${node.drilldown} 端点应吸附边缘中点`);
      assert.deepEqual(geometry.badPortAxes,[],`视图 ${node.drilldown} 端口方向应符合布局方向`);
      assert.deepEqual(geometry.badStubLengths,[],`视图 ${node.drilldown} 外引段应沿端口法线`);
      assert.deepEqual(geometry.missingArrowheads,[],`视图 ${node.drilldown} 每条有向边都要有箭头头部`);
      assert.equal(geometry.badArrowheadDefinition,false,`视图 ${node.drilldown} 的箭头头部应自动定向`);
      assert.deepEqual(geometry.tooManyBends,[],`视图 ${node.drilldown} 折点最多两个`);
      assert.deepEqual(geometry.pathNodeCrossings,[],`视图 ${node.drilldown} 连线不得穿模块`);
      assert.deepEqual(geometry.edgeCrossings,[],`视图 ${node.drilldown} 连线不得交叉`);
      assert.deepEqual(geometry.overlaps,[],`视图 ${node.drilldown} 模块不得重叠`);
      assert.ok(geometry.cardHeights.every(height=>height>=58&&height<=68),`视图 ${node.drilldown} 模块卡片应保持紧凑`);
      assert.deepEqual(geometry.outOfLayer,[],`视图 ${node.drilldown} 模块须留在泳道内`);
      assert.deepEqual(geometry.labelNodeOverlaps,[],`视图 ${node.drilldown} 标签不得压模块`);
      assert.deepEqual(geometry.labelOverlaps,[],`视图 ${node.drilldown} 标签不得互相遮挡`);
      assert.deepEqual(geometry.badgeOverlaps,[],`视图 ${node.drilldown} 下钻提示不得遮挡模块标题`);
      assert.ok(geometry.labelPathGaps.every(item=>item.gap<=8),`视图 ${node.drilldown} 标签应紧贴对应连线`);
      await inspectNestedViews(node.drilldown);
      await page.locator('#back').click();
      assert.equal(await page.locator('#canvas svg').getAttribute('aria-label'),graph.title,`从 ${node.drilldown} 返回应恢复父图`);
    }
  }
  await inspectNestedViews(viewPayload.root);

  const initial=await inspectGeometry();
  assert.ok(initial.cardHeights.every(height=>height>=52&&height<=68),'卡片高度需保持紧凑');
  assert.deepEqual(initial.badAngles,[],'连线不得出现斜线');
  assert.deepEqual(initial.tooManyBends,[],'连线最多两个折点');
  assert.deepEqual(initial.badAnchors,[],'连线两端必须吸附到模块边缘中心');
  assert.deepEqual(initial.badPortAxes,[],'同层边必须使用左右端口，跨层边必须使用上下端口');
  assert.deepEqual(initial.badStubLengths,[],'有折点的连线首末端口必须至少沿法线外引 16px');
  assert.deepEqual(initial.missingArrowheads,[],'每条有向关系都必须引用明确的 SVG 箭头头部');
  assert.equal(initial.badArrowheadDefinition,false,'SVG 箭头头部必须按路径方向自动旋转并指向目标');
  assert.equal(initial.badArrowShaftBase,false,'箭杆必须停在箭头三角底边，尖端由箭头头部单独形成');
  assert.deepEqual(initial.pathNodeCrossings,[],'连线不得穿过无关模块');
  assert.deepEqual(initial.edgeCrossings,[],'无关连线不得相互交叉');
  assert.deepEqual(initial.overlappingRoutes,[],'无关连线不得长距离重叠');
  assert.deepEqual(initial.overlaps,[],'模块不得互相重叠');
  assert.deepEqual(initial.outOfLayer,[],'模块必须位于所属泳道内');
  assert.deepEqual(initial.labelNodeOverlaps,[],'连线标签不得压住模块');
  assert.deepEqual(initial.labelOverlaps,[],'连线标签之间不得重叠');
  assert.deepEqual(initial.badgeOverlaps,[],'主图下钻提示不得遮挡模块标题');
  assert.ok(initial.labelPathGaps.every(item=>item.gap<=8),`箭头标签应紧贴对应线段：${JSON.stringify(initial.labelPathGaps)}`);
  assert.ok(!/[A-Za-z]{2,}/.test(initial.text),'图面不得出现英文代码痕迹');
  if(screenshotPath){
    await page.locator('#canvas svg').screenshot({path:screenshotPath});
    await page.screenshot({path:join(dirname(screenshotPath),'architecture-editor-preview.png'),fullPage:true});
  }

  await page.locator('[data-node="identity-control"] .drill-icon').click();
  assert.equal(await page.locator('#canvas svg').getAttribute('aria-label'),'身份校验、回复守卫与工具保护','治理下钻应打开模块关系图');
  const governanceSource=page.locator('[data-node="chat-api"]');
  const governanceInitial=await governanceSource.getAttribute('transform');
  const governanceEdge=page.locator('[data-edge="auth-chat-api"]');
  const governanceGroup=await governanceEdge.getAttribute('data-group-id');
  const governancePathBefore=await governanceEdge.locator('.edge-line').getAttribute('d');
  const governanceBus=page.locator(`[data-edge-group="${governanceGroup}"]`);
  const governanceBusBefore=await governanceBus.getAttribute('d');
  const governanceBounds=await governanceSource.boundingBox();
  await page.mouse.move(governanceBounds.x+governanceBounds.width/2,governanceBounds.y+governanceBounds.height/2);
  await page.mouse.down();await page.mouse.move(governanceBounds.x+governanceBounds.width/2-12,governanceBounds.y+governanceBounds.height/2+12,{steps:4});await page.mouse.up();
  assert.notEqual(await governanceSource.getAttribute('transform'),governanceInitial,'治理下钻模块应可拖动');
  assert.notEqual(await governanceEdge.locator('.edge-line').getAttribute('d'),governancePathBefore,'拖动后治理关系应重新布线');
  assert.notEqual(await governanceBus.getAttribute('d'),governanceBusBefore,'拖动后扇出总线应同步更新');
  const governanceGeometry=await inspectGeometry();
  assert.deepEqual(governanceGeometry.badAngles,[],'治理扇出拖动后不得出现斜线');
  assert.deepEqual(governanceGeometry.badAnchors,[],'治理扇出端点和总线连接必须准确');
  assert.deepEqual(governanceGeometry.missingArrowheads,[],'治理关系箭头头部必须保留');
  assert.deepEqual(governanceGeometry.pathNodeCrossings,[],'治理关系不得穿过无关模块');
  assert.deepEqual(governanceGeometry.edgeCrossings,[],'治理关系不得交叉');
  await page.locator('#reset').click();
  assert.equal(await governanceSource.getAttribute('transform'),governanceInitial,'重置后治理模块回到初始位置');
  assert.equal(await governanceEdge.locator('.edge-line').getAttribute('d'),governancePathBefore,'重置后治理支线恢复');
  assert.equal(await governanceBus.getAttribute('d'),governanceBusBefore,'重置后治理总线恢复');
  await page.locator('#back').click();

  const rootFlowPaths=Object.fromEntries(await Promise.all((await page.locator('#canvas .edge[data-layer-flow="true"]').evaluateAll(edges=>edges.map(edge=>edge.dataset.edge))).map(async id=>[id,await page.locator(`[data-edge="${id}"] .edge-line`).getAttribute('d')])));
  const rootNode=page.locator('[data-node="agent-routing"]');
  const rootInitialTransform=await rootNode.getAttribute('transform');
  const rootBounds=await rootNode.boundingBox();
  await page.mouse.move(rootBounds.x+rootBounds.width/2,rootBounds.y+rootBounds.height/2);
  await page.mouse.down();await page.mouse.move(rootBounds.x+rootBounds.width/2-18,rootBounds.y+rootBounds.height/2+18,{steps:5});await page.mouse.up();
  assert.notEqual(await rootNode.getAttribute('transform'),rootInitialTransform,'主图模块应可拖动');
  const rootDraggedTransform=await rootNode.getAttribute('transform');
  for(const [id,path] of Object.entries(rootFlowPaths))assert.equal(await page.locator(`[data-edge="${id}"] .edge-line`).getAttribute('d'),path,'层间箭头固定在层边界，不随单卡片拖动');
  const moved=await inspectGeometry();
  assert.deepEqual(moved.badAngles,[],'拖动后不得出现斜线');
  assert.deepEqual(moved.overlaps,[],'拖动后模块不得重叠');
  assert.deepEqual(moved.outOfLayer,[],'拖动后模块不得越出所属泳道');
  if(screenshotPath)await page.locator('#canvas svg').screenshot({path:join(dirname(screenshotPath),'architecture-dragged-preview.png')});

  const downloadSvg=page.waitForEvent('download');
  await page.locator('#exportSvg').click();
  const svgFile=await downloadSvg;const svgPath=join(dirname(htmlPath),'browser-export.svg');await svgFile.saveAs(svgPath);
  const exportedSvg=await readFile(svgPath,'utf8');
  assert.match(exportedSvg,/<svg[\s>]/,'SVG 导出应包含有效矢量图');
  assert.doesNotMatch(exportedSvg,/class="drill-icon"/,'总架构图静态导出不应包含下钻图标');
  assert.ok(await page.locator('#canvas .drill-icon').count()>0,'交互页面仍应保留下钻图标');
  const downloadPng=page.waitForEvent('download');
  await page.locator('#exportPng').click();
  const pngFile=await downloadPng;const pngPath=join(dirname(htmlPath),'browser-export.png');await pngFile.saveAs(pngPath);
  const png=await readFile(pngPath);assert.equal(png.subarray(0,8).toString('hex'),'89504e470d0a1a0a','PNG 导出应为有效图片');
  const svgSize=await page.locator('#canvas svg').evaluate(svg=>[Number(svg.getAttribute('width')),Number(svg.getAttribute('height'))]);
  const pngSize=[png.readUInt32BE(16),png.readUInt32BE(20)];
  assert.deepEqual(pngSize,svgSize.map(value=>value*3),'高清 PNG 应按 3 倍分辨率导出');

  await page.reload({waitUntil:'load'});
  assert.equal(await page.locator('[data-node="agent-routing"]').getAttribute('transform'),rootDraggedTransform,'刷新后应保留拖动位置');
  await page.locator('#reset').click();
  const resetPosition=await page.locator('[data-node="agent-routing"]').evaluate(el=>{const m=el.transform.baseVal.consolidate().matrix;return [m.e,m.f]});
  const rootStart=rootInitialTransform.match(/translate\(([-\d.]+)\s+([-\d.]+)\)/).slice(1).map(Number);
  assert.deepEqual(resetPosition,rootStart,'重置后应恢复初始位置');
  for(const [id,path] of Object.entries(rootFlowPaths))assert.equal(await page.locator(`[data-edge="${id}"] .edge-line`).getAttribute('d'),path,`重置后层间流向 ${id} 应恢复`);
  assert.deepEqual(errors,[],`浏览器页面错误：${errors.join('; ')}`);
  const result={ok:true,nodes:25,layerFlowEdges:4,moduleEdges:0,layerFlowsRemainAnchored:true,drilldownAndNestedReturn:true,nestedViewsChecked:visitedViews.size-1,edgeAnchors:'directional side midpoints',normalOutsetMinPx:16,arrowheads:'marker anchored at the head base; shaft ends at base',badArrowShaftBase,
    noNodeOverlaps:true,staysWithinLayer:true,noPathThroughUnrelatedNodes:true,noEdgeCrossings:true,noRouteOverlaps:true,noLabelOverlaps:true,horizontalLabelsNearEdges:true,drilldownGeometryChecked:true,cleanToolbar:true,detailsPanelOnDemand:true,
    svgExport:true,pngExport:{valid:true,scale:3},persistAndReset:true,screenshot:screenshotPath||null,pageErrors:errors};
  await writeFile(join(dirname(htmlPath),'interaction-report.json'),JSON.stringify(result,null,2)+'\n','utf8');
  console.log(JSON.stringify(result,null,2));
} finally {
  await browser.close();
}
