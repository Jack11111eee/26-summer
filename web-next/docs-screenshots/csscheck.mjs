import puppeteer from 'puppeteer-core'
const browser = await puppeteer.launch({ headless: 'new', executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', args: ['--no-sandbox'] })
const page = await browser.newPage()
await page.setViewport({ width: 1440, height: 900 })
const resp = await fetch('http://localhost:8410/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: 'admin', password: 'admin123' }) })
const { token, user } = await resp.json()
await page.goto('http://localhost:5175/login', { waitUntil: 'domcontentloaded' })
await page.evaluate((t, u) => { localStorage.setItem('token', t); localStorage.setItem('user', JSON.stringify(u)) }, token, user)

// 模型审核页：验证两栏布局与编辑卡出现
await page.goto('http://localhost:5175/admin/positions/pos_032dc6ab6aff/review', { waitUntil: 'networkidle2', timeout: 25000 })
await new Promise(r => setTimeout(r, 3200))
const m = await page.evaluate(() => {
  const cols = document.querySelector('.cols')
  const cards = document.querySelectorAll('.item-card').length
  const sigma = document.querySelector('.sigma')
  const evidence = document.querySelector('.col-side')
  const topbar = document.querySelector('.topbar-title')?.textContent
  return { cols: !!cols, cards, sigma: !!sigma, sigmaText: sigma?.querySelector('.num')?.textContent, evidence: !!evidence, topbar }
})
console.log('ModelReview:', JSON.stringify(m))

// 岗位库：KPI 四卡 + 三色块结构
await page.goto('http://localhost:5175/admin/positions', { waitUntil: 'networkidle2', timeout: 25000 })
await new Promise(r => setTimeout(r, 3200))
const p = await page.evaluate(() => ({
  stats: document.querySelectorAll('.stats .stat').length,
  statNums: [...document.querySelectorAll('.stat-num')].map(e => e.textContent),
  n1: !!document.querySelector('.block.n1'), n2: document.querySelectorAll('.block.n2').length,
  sidebar: !!document.querySelector('.sidebar'), blob: !!document.querySelector('.blob'),
  edge: !!document.querySelector('.edge'),
  tags: [...document.querySelectorAll('.tag')].slice(0, 4).map(e => e.textContent)
}))
console.log('Positions:', JSON.stringify(p))

// 测评报告页：雷达 SVG + 五段结构
const resp2 = await fetch('http://localhost:8410/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: 'demo_user', password: 'demo123' }) })
const c = await resp2.json()
await page.evaluate(() => localStorage.clear())
await page.goto('http://localhost:5175/login', { waitUntil: 'domcontentloaded' })
await page.evaluate((t, u) => { localStorage.setItem('token', t); localStorage.setItem('user', JSON.stringify(u)) }, c.token, c.user)
await page.goto('http://localhost:5175/assessment/report/sess_e39e46a7b5b9', { waitUntil: 'networkidle2', timeout: 25000 })
await new Promise(r => setTimeout(r, 4500))
const r = await page.evaluate(() => ({
  score: document.querySelector('.rep-score')?.textContent,
  svgPolygons: document.querySelectorAll('.radar-box svg polygon').length,
  itemRows: document.querySelectorAll('.rep-table tbody tr').length,
  folds: document.querySelectorAll('.rep-fold').length,
  coverage: !!document.querySelector('.coverage-bar'),
  strengths: document.querySelectorAll('.rep-duo .paper-card li').length,
  bodyClass: document.body.className
}))
console.log('Report:', JSON.stringify(r))
await browser.close()
