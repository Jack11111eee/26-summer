import puppeteer from 'puppeteer-core'
const browser = await puppeteer.launch({ headless: 'new', executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', args: ['--no-sandbox'] })
const page = await browser.newPage()
await page.setViewport({ width: 1440, height: 900 })
const resp = await fetch('http://localhost:8410/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: 'admin', password: 'admin123' }) })
const { token, user } = await resp.json()
await page.goto('http://localhost:5175/login', { waitUntil: 'domcontentloaded' })
await page.evaluate((t, u) => { localStorage.setItem('token', t); localStorage.setItem('user', JSON.stringify(u)) }, token, user)

await page.goto('http://localhost:5175/admin/positions/pos_06424b3bc518/review', { waitUntil: 'networkidle2', timeout: 25000 })
await new Promise(r => setTimeout(r, 3200))
const m = await page.evaluate(() => ({
  cards: document.querySelectorAll('.item-card').length,
  sigmaText: document.querySelector('.sigma .num')?.textContent,
  sigmaBad: document.querySelector('.sigma')?.className,
  catBlocks: [...document.querySelectorAll('.block-title')].map(e => e.textContent).slice(0, 8)
}))
console.log('edit state:', JSON.stringify(m))

// 试保存草稿（Σ 权重要 ok 才可点）
const canSave = await page.evaluate(() => {
  const btns = [...document.querySelectorAll('.btn')]
  const save = btns.find(b => b.textContent.includes('保存草稿'))
  return save ? !save.disabled : false
})
console.log('save enabled (Σ 合法):', canSave)
// 点保存 → 应成功 toast
await page.evaluate(() => {
  const btns = [...document.querySelectorAll('.btn')]
  btns.find(b => b.textContent.includes('保存草稿'))?.click()
})
await new Promise(r => setTimeout(r, 2500))
const afterSave = await page.evaluate(() => document.querySelector('.toast')?.textContent || 'no toast')
console.log('save toast:', afterSave)
await browser.close()
