// Browser checks use an isolated read-only fixture generated from local extracted units.
// Generate artifacts/frontend/design-map-fixture.json with build_design_map before running.
const {createServer}=require('node:http');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root=path.resolve(__dirname,'../dist'),out=path.resolve(__dirname,'../../artifacts/frontend');
const fixture=JSON.parse(fs.readFileSync(process.env.GRAPH_FIXTURE || path.join(out,'design-map-fixture.json'),'utf8'));
const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aChsAAAAASUVORK5CYII=','base64');
let failNext=false, scopes=[];
const server=createServer((req,res)=>{
 const url=new URL(req.url,'http://localhost');
 if(url.pathname==='/api/graph/design-map'){
  scopes.push(url.searchParams.get('kb_id'));
  if(failNext){failNext=false;res.writeHead(503,{'Content-Type':'application/json'});res.end('{"detail":"fixture failure"}');return;}
  res.setHeader('Content-Type','application/json');res.end(JSON.stringify(fixture));return;
 }
 if(url.pathname.startsWith('/api/')){
  if(url.pathname.includes('/pages/') || url.pathname.endsWith('/assets')){res.setHeader('Content-Type','image/png');res.end(png);return;}
  res.setHeader('Content-Type','application/json');res.end(JSON.stringify({page_count:10,pages:[]}));return;
 }
 let file=path.join(root,url.pathname);if(!fs.existsSync(file)||fs.statSync(file).isDirectory())file=path.join(root,'index.html');
 res.setHeader('Content-Type',({'.js':'text/javascript','.css':'text/css','.html':'text/html','.woff2':'font/woff2'})[path.extname(file)]||'application/octet-stream');res.end(fs.readFileSync(file));
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1720,height:1080}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`http://127.0.0.1:${server.address().port}/graph`);
  await page.locator('.mm-node[data-id="module:equalization"]').waitFor();
  await page.locator('.mm-node[data-id="module:equalization"]').click();
  await page.locator('.detail-panel h3').filter({hasText:'均衡与反馈'}).waitFor();
  const candidates=page.locator('.candidate-row');assert.ok(await candidates.count()>=2);
  await candidates.nth(0).locator('input').check();await candidates.nth(1).locator('input').check();
  await page.getByRole('button',{name:'对比 2',exact:true}).click();
  await page.locator('.comparison-table').waitFor();assert.ok(await page.locator('.comparison-table').innerText().then(t=>t.includes('替换结论')&&t.includes('候选技术')));
  await page.locator('.ant-modal-close').click();await page.locator('.comparison-table').waitFor({state:'hidden'});
  await page.getByRole('button',{name:'聚焦所选',exact:true}).click();
  await page.locator('.mm-node.root[data-id="module:equalization"]').waitFor();
  fs.mkdirSync(out,{recursive:true});await page.screenshot({path:path.join(out,'design-map-desktop.png'),fullPage:true});
  await page.getByRole('searchbox',{name:'搜索知识体系'}).count().then(async count=>{ if(count)await page.getByRole('searchbox',{name:'搜索知识体系'}).fill('SAR');else await page.getByPlaceholder('搜索模块、技术或文档').fill('SAR');});
  const search=page.getByPlaceholder('搜索模块、技术或文档');await search.press('Enter');await page.locator('.detail-panel h3').filter({hasText:'SAR'}).waitFor();
  assert.equal(await page.locator('.candidate-row input:checked').count(),0,'Comparison selection resets between modules');
  await page.locator('.source-link').first().click();await page.locator('.source-content').waitFor();assert.ok((await page.locator('.source-content').innerText()).length>20);
  await page.locator('.ant-modal-close').last().click();await page.locator('.source-content').waitFor({state:'hidden'});
  await search.fill('no-such-node-999');await page.getByText('没有匹配结果，请尝试模块名称或缩写').waitFor();await search.fill('');
  const download=page.waitForEvent('download');await page.getByRole('button',{name:'导出大纲'}).click();assert.ok((await download).suggestedFilename().endsWith('.md'));
  failNext=true;await page.getByRole('button',{name:'刷新知识体系'}).click();await page.locator('.load-error').waitFor();await page.getByRole('button',{name:'刷新知识体系'}).click();await page.locator('.mm-node[data-id="module:equalization"]').waitFor();
  await page.locator('.ant-message-notice').last().waitFor({state:'hidden'});
  for(const width of [1280,768,390]){await page.setViewportSize({width,height:1000});await page.waitForTimeout(300);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`No overflow ${width}`);assert.ok(await page.locator('.mind-canvas').evaluate(el=>{const root=el.querySelector('.mm-node.root').getBoundingClientRect(),box=el.getBoundingClientRect();return root.top>=box.top&&root.bottom<=box.bottom;}),`Root visible ${width}`);await page.screenshot({path:path.join(out,`design-map-${width}.png`),fullPage:true});}
  assert.deepEqual(errors,[]);console.log('PASS: module mind map, compare, source detail, search, empty search, outline export, failure recovery, responsive 1280/768/390.');
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
