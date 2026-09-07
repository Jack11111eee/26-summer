import puppeteer from 'puppeteer-core'
const SID = 'sess_5f09c067d79d'
const browser = await puppeteer.launch({ headless: 'new', executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', args: ['--no-sandbox'] })
const page = await browser.newPage()
await page.setViewport({ width: 1440, height: 900 })
const resp = await fetch('http://localhost:8410/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: 'demo_user', password: 'demo123' }) })
const { token, user } = await resp.json()
await page.goto('http://localhost:5175/login', { waitUntil: 'domcontentloaded' })
await page.evaluate((t, u) => { localStorage.setItem('token', t); localStorage.setItem('user', JSON.stringify(u)) }, token, user)
await page.goto(`http://localhost:5175/assessment/session/${SID}`, { waitUntil: 'networkidle2', timeout: 25000 })
await new Promise(r => setTimeout(r, 3000))
await page.screenshot({ path: '/Users/huaxinzhang/.claude/jobs/d06cd4e2/tmp/shots/cand-chat.png' })
console.log('chat shot done')
await browser.close()
