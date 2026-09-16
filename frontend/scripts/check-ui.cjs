// Isolated browser checks against fixtures; never modifies a real knowledge base.
const { createServer } = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '../dist');
const out = path.resolve(__dirname, '../../artifacts/frontend');
fs.mkdirSync(out, { recursive: true });
const server = createServer((req, res) => {
  let file = path.join(root, new URL(req.url, 'http://localhost').pathname);
  if (!file.startsWith(root)) { res.writeHead(403).end(); return; }
  if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) file = path.join(root, 'index.html');
  res.setHeader('Content-Type', ({ '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html' })[path.extname(file)] || 'application/octet-stream');
  res.end(fs.readFileSync(file));
});
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const docs = Array.from({ length: 13 }, (_, i) => ({ id: `doc-${i}`, kb_id: 'kb-1', filename: i === 0 ? 'A_10_Gb_s_Hybrid_ADC_Based_Receiver_With_Embedded_Analog_and_Digital_Design.pdf' : `设计规范-${i}.md`, status: i === 1 ? 'failed' : i === 2 ? 'review' : 'awaiting_strategy', enabled: false, unit_count: i === 2 ? 12 : 0, size_bytes: 4300000, classification: { confidence: .82, knowledge_type: 'technical_concept', scores: { technical_concept: .82, technical_specification: .12, incident_case: .06 } }, recommended_strategy: 'Technical Knowledge V1', error_message: i === 1 ? '示例解析错误，请重新上传' : '' }));
    await page.route('**/api/**', async route => {
      const url = new URL(route.request().url());
      let data = [];
      if (url.pathname === '/api/knowledge-bases') data = [{ id: 'kb-1', name: '芯片设计知识库', domain: 'semiconductor', document_count: 13, unit_count: 12 }, { id: 'kb-2', name: '接口文档库', domain: 'api', document_count: 0, unit_count: 0 }];
      if (url.pathname === '/api/strategies') data = [{ id: 's-1', name: 'Technical Knowledge V1', knowledge_type: 'technical_concept' }];
      if (url.pathname === '/api/documents') data = url.searchParams.get('kb_id') === 'kb-2' ? [] : docs;
      if (url.pathname.endsWith('/confirm-strategy')) { docs[0].status = 'failed'; docs[0].error_message = '抽取失败测试'; data = docs[0]; }
      await route.fulfill({ json: data });
    });
    const base = `http://127.0.0.1:${server.address().port}`;
    await page.goto(`${base}/documents`);
    await page.locator('.file-row').first().waitFor();
    assert.equal(await page.locator('.file-row').count(), 10);
    const box = await page.locator('.doc-page').boundingBox();
    assert.ok(box.width > 1600, 'Document workspace should fill desktop width');
    await page.screenshot({ path: path.join(out, 'documents-desktop.png'), fullPage: true });
    await page.getByPlaceholder('搜索文档名称').fill('规范-2.');
    assert.equal(await page.locator('.file-row').count(), 1);
    await page.getByPlaceholder('搜索文档名称').fill('');
    await page.locator('.list-tools .ant-select').click();
    await page.locator('.ant-select-item-option').filter({ hasText: '处理失败' }).click();
    assert.equal(await page.locator('.file-row').count(), 1);
    await page.locator('.file-row').click();
    assert.ok(await page.getByText('示例解析错误，请重新上传').isVisible());
    await page.locator('.list-tools .ant-select').click();
    await page.locator('.ant-select-item-option').filter({ hasText: '全部状态' }).click();
    await page.locator('.file-row').first().click();
    await page.getByRole('button', { name: '使用推荐策略', exact: true }).click();
    await page.getByRole('button', { name: '下一步：处理配置' }).click();
    await page.getByRole('button', { name: '下一步：审核设置' }).click();
    await page.getByRole('button', { name: '开始抽取', exact: true }).click();
    await page.locator('.preview').getByText('抽取失败测试').waitFor();
    assert.equal(await page.locator('.finish').isVisible(), false, 'Failed extraction must not display completion');
    for (const width of [1280, 768, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await page.waitForTimeout(350);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `No page overflow at ${width}px`);
      await page.screenshot({ path: path.join(out, `documents-${width}.png`), fullPage: true });
    }
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(`${base}/knowledge-bases?q=接口`);
    await page.getByText('接口文档库', { exact: true }).waitFor();
    assert.equal(await page.locator('.ant-card').count(), 1);
    await page.getByRole('button', { name: '管理文档 →' }).click();
    await page.getByText('尚未上传文档', { exact: true }).waitFor();
    assert.equal(await page.locator('.kb-select').innerText(), '接口文档库');
    assert.deepEqual(errors, []);
    console.log('PASS: desktop width, pagination, search, status filter, failure feedback, extraction failure, 1280/768/390 responsive layout, knowledge-base search and document navigation.');
  } finally { await browser.close(); server.close(); }
})().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
