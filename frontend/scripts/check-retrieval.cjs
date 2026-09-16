const {createServer}=require('node:http');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root=path.resolve(__dirname,'../dist'),out=path.resolve(__dirname,'../../artifacts/frontend');
let mode='hits', saved, tests=0;
let doc={id:'d1',kb_id:'k2',filename:'SAR-Receiver.md',unit_count:8,retrievable_count:6,keyword_count:2,keywords:[{keyword:'SAR',weight:0,source:'manual'},{keyword:'ADC',weight:1,source:'extracted'}],metadata:{title:'SAR 接收机设计',year:2025,authors:['A','B'],details:{rate:10}},status:'review',enabled:true};
const server=createServer(async(req,res)=>{
 const url=new URL(req.url,'http://localhost');
 if(url.pathname.startsWith('/api/')){
  let body='';for await(const part of req)body+=part;
  let data=[];
  if(url.pathname==='/api/knowledge-bases')data=[{id:'k1',name:'通用知识库'},{id:'k2',name:'芯片设计知识库'}];
  if(url.pathname==='/api/retrieval/planners')data=[{id:'p',query_type:'comparison',steps:[{type:'hybrid_search'},{type:'rerank'}],completeness_threshold:.8,secondary_retrieval:true}];
  if(url.pathname==='/api/retrieval/test'){
   tests++;const payload=JSON.parse(body);
   if(mode==='error'){res.writeHead(503,{'Content-Type':'application/json'});res.end('{"detail":"测试服务暂不可用"}');return;}
   data={query:payload.query,kb_id:payload.kb_id,kb_name:'芯片设计知识库',elapsed_ms:1250,total:mode==='empty'?0:1,hits:mode==='empty'?[]:[{id:'u1',document_id:'d1',filename:'SAR-Receiver.md',document_title:'SAR 接收机设计',title:'SAR ADC 的功耗优化',content:'**逐次逼近 ADC** 的设计资料。\n\n- 核对采样速率\n- 查看电路实现与约束\n\n此处是测试用知识片段。',semantic_role:'principle',source_page:2,source_chapter:'II',score:.8,via:'rerank'}],stages:[{key:'understand',label:'理解问题',elapsed_ms:100},{key:'plan',label:'确定检索范围',elapsed_ms:200},{key:'retrieve',label:'召回、重排与关联展开',elapsed_ms:950}],understanding:{intent:'solution',topics:['SAR','ADC']},retrieval:{vector:4,keyword:3,exact:0,graph:0,fused:5,reranked:1,expanded:1},services:{vector:false,keyword:false,graph:false,model:false}};
  }
  if(url.pathname==='/api/retrieval/indexes')data=[doc];
  if(url.pathname==='/api/retrieval/indexes/d1'){
   if(req.method==='PUT'){saved=JSON.parse(body);doc={...doc,...saved,keyword_count:saved.keywords.length};}
   data=doc;
  }
  res.setHeader('Content-Type','application/json');res.end(JSON.stringify(data));return;
 }
 let file=path.join(root,url.pathname);if(!fs.existsSync(file)||fs.statSync(file).isDirectory())file=path.join(root,'index.html');
 res.setHeader('Content-Type',({'.js':'text/javascript','.css':'text/css','.html':'text/html','.woff2':'font/woff2'})[path.extname(file)]||'application/octet-stream');res.end(fs.readFileSync(file));
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1600,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`http://127.0.0.1:${server.address().port}/retrieval`);
  assert.equal(tests,0);
  await page.getByRole('combobox',{name:'检索知识库'}).click();await page.getByText('芯片设计知识库',{exact:true}).click();
  await page.getByRole('textbox',{name:'检索问题'}).fill('SAR ADC 如何降低功耗？');await page.getByRole('button',{name:'开始检索验证'}).click();
  await page.locator('.hit-card').waitFor();assert.equal(await page.locator('.hit-excerpt strong').innerText(),'逐次逼近 ADC');
  fs.mkdirSync(out,{recursive:true});await page.screenshot({path:path.join(out,'retrieval-desktop.png'),fullPage:true});
  await page.getByRole('button',{name:'查看完整片段',exact:true}).click();await page.locator('.source-layout').waitFor();await page.locator('.ant-modal-close').click();await page.locator('.source-layout').waitFor({state:'hidden'});
  await page.getByRole('button',{name:'检查文档标签'}).click();await page.locator('.maintenance-editor h3').waitFor();
  await page.getByPlaceholder('例如：SAR ADC、逐次逼近、接收判决链').fill('逐次逼近');await page.getByRole('button',{name:'添加标签'}).click();
  await page.getByRole('button',{name:'保存修改',exact:true}).click();await page.getByText('标签已保存，可重新验证检索结果').waitFor();
  assert.equal(saved.metadata.year,2025);assert.deepEqual(saved.metadata.authors,['A','B']);assert.deepEqual(saved.metadata.details,{rate:10});assert.equal(saved.keywords[0].weight,0);
  await page.getByRole('button',{name:'返回检索验证'}).click();await page.getByRole('button',{name:'用这个问题继续问答'}).click();await page.waitForURL('**/chat?**');assert.equal(await page.locator('.input-box textarea').inputValue(),'SAR ADC 如何降低功耗？');assert.equal(await page.locator('.settings .ant-select').innerText(),'芯片设计知识库');
  await page.goto(`http://127.0.0.1:${server.address().port}/retrieval`);await page.getByRole('textbox',{name:'检索问题'}).fill('缺失资料');mode='empty';await page.getByRole('button',{name:'开始检索验证'}).click();await page.getByText('没有找到可展示的知识片段').waitFor();
  mode='error';await page.getByRole('button',{name:'开始检索验证'}).click();await page.locator('.test-error').waitFor();
  mode='hits';await page.getByRole('button',{name:'开始检索验证'}).click();await page.locator('.hit-card').waitFor();
  await page.getByRole('tab',{name:'工作原理与排查'}).click();await page.getByText('检索中心负责什么？').waitFor();
  await page.getByRole('tab',{name:'检索验证',exact:true}).click();
  await page.locator('.ant-message-notice').last().waitFor({state:'hidden'});
  for(const width of [1280,768,390]){await page.setViewportSize({width,height:1000});await page.waitForTimeout(300);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`overflow ${width}`);await page.screenshot({path:path.join(out,`retrieval-${width}.png`),fullPage:true});}
  assert.deepEqual(errors,[]);console.log('PASS: retrieval, source preview, document labels, typed metadata/zero weight preservation, handoff to chat, empty/error recovery, guidance, responsive layout.');
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
