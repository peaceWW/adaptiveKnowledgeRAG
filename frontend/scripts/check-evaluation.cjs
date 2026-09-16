const {createServer}=require('node:http');
const fs=require('node:fs'), path=require('node:path'), assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root=path.resolve(__dirname,'../dist'), out=path.resolve(__dirname,'../../artifacts/frontend');
const golden=[{id:'c0',dataset_name:'receiver-v1',question:'混合接收机架构是怎样的？',kb_id:'kb',question_type:'定义类',required_knowledge:['id:u1'],optional_knowledge:[],forbidden_knowledge:[],expected_roles:['principle'],evaluation_config:{reference_answer:'RF 经混频、ADC 后进入 DSP。',answer_points:['解释信号流向'],expected_kinds:['figure','equation']}},{id:'c1',dataset_name:'receiver-v1',question:'如何选择采样率？',kb_id:'kb',question_type:'解决方案类',required_knowledge:['id:u2'],optional_knowledge:[],forbidden_knowledge:[],expected_roles:[],evaluation_config:{}}];
let runs=[],startPayload, savedPayload, fail=true;
const answer='## 工程结论\n\nRF 信号经混频、ADC 后进入 DSP。\n\n## 架构图\n\n[[figure:u1]]\n\n## 关键公式\n\n$$F_s \\ge 2B$$';
const cite={knowledge_id:'u1',kind:'figure',document_id:'doc',image_key:'images/doc/test.svg',title:'接收机架构',page:4,content:'RF → ADC → DSP'};
function overview(id){let latest=runs.find(r=>r.id===id)||runs.at(-1);return {datasets:['receiver-v1'],latest,runs:[...runs].reverse(),strategy_compare:latest?.status==='completed'?[latest]:[],trend:latest?.status==='completed'?[{id:latest.id,date:'09-16 10:00',recall:100,precision:10,coverage:100}]:[],question_types:[{label:'定义类',percent:50,color:'#1d4ed8'},{label:'解决方案类',percent:50,color:'#22c55e'}],total_questions:2};}
function stats(run){let done=run.details.filter(d=>d.status==='completed');run.metrics={cases:2,completed:done.length,errors:run.details.filter(d=>d.status==='error').length,scored_cases:done.length,judged:done.length,recall:done.length?1:null,precision:done.length?.1:null,mrr:done.length?1:null,coverage:done.length?1:null,pass_rate:done.length?1:null,correctness:done.length?.9:null,groundedness:done.length?.8:null,completeness:done.length?1:null};}
const server=createServer(async(req,res)=>{const url=new URL(req.url,'http://localhost');const send=data=>{res.setHeader('Content-Type','application/json');res.end(JSON.stringify(data));};
 if(url.pathname==='/api/documents/doc/assets'){res.setHeader('Content-Type','image/svg+xml');res.end('<svg xmlns="http://www.w3.org/2000/svg" width="440" height="140"><rect width="440" height="140" fill="#edf3ff"/><text x="45" y="80" font-size="25">RF → ADC → DSP</text></svg>');return;}
 if(url.pathname.startsWith('/api/')){
  let body='';for await(const chunk of req)body+=chunk;const payload=body?JSON.parse(body):{};
  if(url.pathname==='/api/strategies')return send([{id:'s',name:'芯片设计策略',version:'V2'}]);
  if(url.pathname==='/api/knowledge-bases')return send([{id:'kb',name:'接收机知识库'}]);
  if(url.pathname==='/api/units')return send([{id:'u1',title:'接收机架构'}]);
  if(url.pathname==='/api/evaluation/overview')return send(overview(url.searchParams.get('run_id')));
  if(url.pathname==='/api/evaluation/golden'&&req.method==='GET')return send(golden);
  if(url.pathname.startsWith('/api/evaluation/golden')&&['POST','PUT'].includes(req.method)){savedPayload=payload;return send({...payload,id:'saved'});}
  if(url.pathname==='/api/evaluation/run') {startPayload=payload;const run={id:`r${runs.length}`,dataset_name:'receiver-v1',strategy_name:'知识库默认策略',status:'queued',created_at:'2026-09-16T10:00:00',config:{dataset_hash:'snapshot123',scoring_version:'evidence-v2'},details:golden.map(c=>({case_id:c.id,question:c.question,question_type:c.question_type,status:'pending'}))};stats(run);runs.push(run);return send(run);}
  const match=/\/api\/evaluation\/runs\/([^/]+)(?:\/(step|cancel|retry))?$/.exec(url.pathname);
  if(match){const run=runs.find(r=>r.id===match[1]);
   if(match[2]==='step'){let row=run.details.find(d=>d.case_id===payload.case_id);row.status='running';run.status='running';setTimeout(()=>{if(row.case_id==='c1'&&fail){row.status='error';row.error='模拟单题超时，可重试';}else{Object.assign(row,{status:'completed',recall:1,precision:.1,mrr:1,coverage:1,pass:true,matched:['id:u1'],missing:[],forbidden:[],answer,citations:[cite],hits:[{id:'u1',title:'架构图',content:'RF 经混频后进行 ADC 采样'}],presentation:{images:[{id:'u1',resolved:true,available:true}],has_math:true,missing:[],scope:'验证图片引用与公式标记'},judge:{status:'scored',correctness:.9,groundedness:.8,completeness:1,reason:'回答覆盖了信号流程，需补充混频条件。'},expected:golden[0],elapsed_ms:1500});}stats(run);if(run.status!=='cancelled')run.status=run.details.some(d=>d.status==='pending')?'queued':run.metrics.errors?'completed_with_errors':'completed';send(run);},400);return;}
   if(match[2]==='cancel'){run.status='cancelled';return send(run);}
   if(match[2]==='retry'){fail=false;const retry=JSON.parse(JSON.stringify(run));retry.id=`r${runs.length}`;retry.status='queued';retry.details=retry.details.map(d=>d.status==='completed'?d:{...d,status:'pending',error:undefined});stats(retry);runs.push(retry);return send(retry);}
   return send(run);
  }
  return send([]);
 }
 let file=path.join(root,url.pathname);if(!fs.existsSync(file)||fs.statSync(file).isDirectory())file=path.join(root,'index.html');res.setHeader('Content-Type',({'.js':'text/javascript','.css':'text/css','.html':'text/html','.woff2':'font/woff2'})[path.extname(file)]||'application/octet-stream');res.end(fs.readFileSync(file));
});
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({channel:'msedge',headless:true});
 try{const page=await browser.newPage({viewport:{width:1440,height:1050}}),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto(`http://127.0.0.1:${server.address().port}/evaluation`);
  await page.getByText('尚未评估，指标显示为 —，不代表得分为 0。').waitFor();assert.deepEqual(await page.locator('.kpi b').allTextContents(),['—','—','—','—']);
  await page.getByRole('button',{name:'开始评估',exact:true}).click();await page.getByRole('button',{name:'重试失败／未完成题'}).waitFor();assert.equal(startPayload.dataset_name,'receiver-v1');assert.equal(await page.locator('.kpi b').first().innerText(),'100%');
  await page.getByRole('button',{name:'查看详情'}).first().click();await page.locator('.ant-drawer .answer img').waitFor();await page.waitForFunction(()=>document.querySelector('.ant-drawer .answer img').naturalWidth>0);assert.ok((await page.locator('.ant-drawer').innerText()).includes('RF 信号经混频'));
  await page.locator('.ant-drawer-content-wrapper').evaluate(el=>Promise.all(el.getAnimations({subtree:true}).map(a=>a.finished)));fs.mkdirSync(out,{recursive:true});await page.screenshot({path:path.join(out,'evaluation-detail.png'),fullPage:true});await page.locator('.ant-drawer-close').click();await page.locator('.ant-drawer-open').waitFor({state:'hidden'});
  await page.getByRole('button',{name:'重试失败／未完成题'}).click();await page.waitForFunction(()=>document.querySelector('.run-heading b')?.textContent.includes('已完成'));
  await page.getByRole('tab',{name:'答案评估',exact:true}).click();assert.equal(await page.locator('.kpi b').first().innerText(),'90%');
  await page.getByRole('tab',{name:'策略对比',exact:true}).click();await page.getByRole('cell',{name:'知识库默认策略',exact:true}).waitFor();
  await page.getByRole('tab',{name:'实验管理',exact:true}).click();await page.getByRole('button',{name:'编辑',exact:true}).first().click();await page.locator('.ant-modal textarea').first().fill('新的评估问题');await page.locator('.ant-modal-footer .ant-btn-primary').click();await page.locator('.ant-modal').waitFor({state:'hidden'});assert.equal(savedPayload.question,'新的评估问题');assert.deepEqual(savedPayload.evaluation_config.expected_kinds,['figure','equation']);
  await page.getByRole('tab',{name:'检索评估',exact:true}).click();await page.locator('.ant-message-notice').first().waitFor({state:'hidden'}).catch(()=>{});await page.screenshot({path:path.join(out,'evaluation-desktop.png'),fullPage:true});
  await page.getByRole('button',{name:'导出报告'}).hover();const downloadPromise=page.waitForEvent('download');await page.getByText('逐题结果 CSV',{exact:true}).click();const download=await downloadPromise;const csv=fs.readFileSync(await download.path(),'utf8');assert.ok(csv.includes('"实际回答"'));assert.ok(csv.includes('RF 信号经混频'));
  for(const width of [768,390]){await page.setViewportSize({width,height:1000});await page.screenshot({path:path.join(out,`evaluation-${width}.png`),fullPage:true});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`overflow ${width}`);}
  await page.setViewportSize({width:1440,height:1050});await page.getByRole('button',{name:'开始评估',exact:true}).click();await page.getByRole('button',{name:'停止后续题目'}).click();await page.waitForFunction(()=>document.querySelector('.run-heading b')?.textContent.includes('已停止'));await page.reload();await page.getByRole('button',{name:'重试失败／未完成题'}).waitFor();await page.getByRole('button',{name:'重试失败／未完成题'}).click();await page.waitForFunction(()=>document.querySelector('.run-heading b')?.textContent.includes('已完成'));
  assert.deepEqual(errors,[]);console.log('PASS: empty state, durable step progress, failure/retry, answer evidence preview, strategy results, case editing, CSV export, cancellation/reload recovery, responsive layouts');
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
