const {createServer}=require('node:http');
const fs=require('node:fs'), path=require('node:path'), assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root=path.resolve(__dirname,'../dist'), out=path.resolve(__dirname,'../../artifacts/frontend');
const answer='## 工作原理\n\n**ADC** 将模拟信号转换为数字信号。\n\n- 保留信号信息\n- 降低处理复杂度\n\n| 模块 | 作用 |\n| --- | --- |\n| ADC | 采样 |\n\n公式：\\(V_t = \\alpha V_{t-1}\\)\n\n<script>window.injected=true</script>';
const cite={title:'接收机结构图',document_id:'doc',image_key:'test.svg',page:2};
let calls=[];
const server=createServer(async(req,res)=>{
 const url=new URL(req.url,'http://localhost');
 if(url.pathname==='/api/chat/stream'){
  let body=''; for await(const part of req) body+=part;
  calls.push(JSON.parse(body));
  res.writeHead(200,{'Content-Type':'text/event-stream'});
  const event=(name,data)=>res.write(`event: ${name}\r\ndata: ${JSON.stringify(data)}\r\n\r\n`);
  event('session',{session_id:'s1'});event('status',{stage:'answer'});event('citations',{citations:[cite]});event('delta',{text:'## 工作原理\n\n**ADC**'});
  setTimeout(()=>{if(res.destroyed)return;event('done',{answer,citations:[cite],understanding:{intent:'definition'},retrieval:{vector:3,keyword:2,reranked:2},elapsed_ms:1200});res.end();},1200);return;
 }
 if(url.pathname.startsWith('/api/documents/') && url.pathname.endsWith('/assets')){res.writeHead(200,{'Content-Type':'image/svg+xml'});res.end('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="150"><rect width="400" height="150" fill="#eef3ff"/><text x="40" y="80" font-size="24">RX → ADC → DSP</text></svg>');return;}
 if(url.pathname.startsWith('/api/')){
  let data=[];
  if(url.pathname==='/api/knowledge-bases')data=[{id:'kb',name:'芯片设计知识库'}];
  if(url.pathname==='/api/chat/sessions')data=[{id:'s1',title:'RX 为什么使用 ADC',time:'14:12'}];
  if(url.pathname==='/api/chat/sessions/s1')data={turns:[{query:'RX 为什么使用 ADC',answer,citations:[cite]}]};
  res.setHeader('Content-Type','application/json');res.end(JSON.stringify(data));return;
 }
 let file=path.join(root,url.pathname);if(!fs.existsSync(file)||fs.statSync(file).isDirectory())file=path.join(root,'index.html');
 res.setHeader('Content-Type',({'.js':'text/javascript','.css':'text/css','.html':'text/html','.woff2':'font/woff2'})[path.extname(file)]||'application/octet-stream');res.end(fs.readFileSync(file));
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}), errors=[];page.on('pageerror',e=>{errors.push(e.message);console.error(e.message)});
  await page.goto(`http://127.0.0.1:${server.address().port}/chat`);
  page.on('console',m=>{if(m.type()==='error')console.error(m.text())});

  await page.locator('.input-box textarea').fill('RX 为什么使用 ADC');await page.locator('.input-box textarea').press('Enter');
  await page.getByRole('button',{name:'停止生成'}).waitFor();
  await page.locator('.answer strong').waitFor();assert.equal(await page.locator('.answer strong').innerText(),'ADC');
  await page.getByRole('button',{name:'复制回答'}).waitFor();
  assert.equal(await page.locator('.answer table').count(),1);assert.equal(await page.locator('.answer .katex').count(),1);assert.equal(await page.evaluate(()=>window.injected),undefined);
  await page.locator('.figure-grid img').waitFor();await page.waitForFunction(()=>document.querySelector('.figure-grid img').naturalWidth>0);
  await page.locator('.figure-grid .ant-image-mask').click();await page.locator('.ant-image-preview-img').waitFor();await page.locator('.ant-image-preview-operations-operation').first().click(); await page.locator('.ant-image-preview-img').waitFor({state:'hidden'}); await page.locator('.conversation').evaluate(el=>el.scrollTop=0);
  fs.mkdirSync(out,{recursive:true});await page.screenshot({path:path.join(out,'chat-desktop.png'),fullPage:true});
  await page.locator('.input-box textarea').fill('请继续解释');await page.locator('.input-box textarea').press('Enter');await page.locator('.turn').nth(1).getByRole('button',{name:'复制回答'}).waitFor();assert.equal(calls[1].session_id,'s1');
  await page.getByRole('button',{name:'＋ 新建会话'}).click();assert.equal(await page.locator('.turn').count(),0);
  await page.locator('.history-item').click();await page.locator('.answer strong').waitFor();assert.equal(await page.locator('.figure-grid img').count(),1);
  for(const width of [1280,768,390]){await page.setViewportSize({width,height:900});await page.screenshot({path:path.join(out,`chat-${width}.png`),fullPage:true});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`overflow ${width}`);}
  assert.deepEqual(errors,[]);console.log('PASS: live SSE, Markdown, math, safe HTML, image preview, followup session, history, responsive layouts');
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});





