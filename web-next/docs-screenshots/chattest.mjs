import puppeteer from 'puppeteer-core'
const SID = 'sess_5f09c067d79d'
const browser = await puppeteer.launch({ headless: 'new', executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', args: ['--no-sandbox'] })
const page = await browser.newPage()
await page.setViewport({ width: 1440, height: 900 })
const errors = []
page.on('pageerror', e => errors.push(String(e).slice(0, 120)))

const resp = await fetch('http://localhost:8410/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: 'demo_user', password: 'demo123' }) })
const { token, user } = await resp.json()
await page.goto('http://localhost:5175/login', { waitUntil: 'domcontentloaded' })
await page.evaluate((t, u) => { localStorage.setItem('token', t); localStorage.setItem('user', JSON.stringify(u)) }, token, user)

// 1. 进入会话 → PENDING_START 卡
await page.goto(`http://localhost:5175/assessment/session/${SID}`, { waitUntil: 'networkidle2', timeout: 25000 })
await new Promise(r => setTimeout(r, 2000))
const gate = await page.evaluate(() => ({
  title: document.querySelector('.gate-card .title')?.textContent,
  rail: document.querySelector('.rail-title')?.textContent,
  statusline: document.querySelector('.status-text')?.textContent,
  topbarBadges: [...document.querySelectorAll('.tb-badge')].map(e => e.textContent),
  sidebar: document.body.className
}))
console.log('1) PENDING_START gate:', JSON.stringify(gate))

// 2. 点击开始测评 → 派第一题
await page.click('.gate-card .btn-accent')
await new Promise(r => setTimeout(r, 3500))
const after = await page.evaluate(() => {
  const stem = document.querySelector('.msg.ai .stem')
  return {
    stem: stem?.textContent?.slice(0, 26),
    railNum: document.querySelector('.rail-num')?.textContent?.replace(/\s+/g, ' '),
    barWidth: document.querySelector('.rail-bar i')?.style.width,
    tocCurrent: document.querySelector('.toc-item.current span:last-child')?.textContent?.slice(0, 16),
    status: document.querySelector('.status-text')?.textContent
  }
})
console.log('2) after start:', JSON.stringify(after))

// 3. 打字作答（输入框 auto-grow + Enter 提交 Enter 键推进）
await page.type('.ta', '我负责过产线传感器的多批标定：漂移超标时设计三点标定流程验证线性度，用最小二乘拟合补偿曲线，良品率从82%提到97%，并将流程文档化交给产线。')
const grew = await page.evaluate(() => document.querySelector('.ta').style.height)
await page.keyboard.press('Enter')
await new Promise(r => setTimeout(r, 6000))
const reply = await page.evaluate(() => {
  const bubbles = [...document.querySelectorAll('.msg.me .bubble')]
  const aiStems = [...document.querySelectorAll('.msg.ai .stem')]
  return {
    meBubbles: bubbles.length,
    lastAi: aiStems[aiStems.length - 1]?.textContent?.slice(0, 30),
    status: document.querySelector('.status-text')?.textContent,
    railNum: document.querySelector('.rail-num')?.textContent?.replace(/\s+/g, ' ')
  }
})
console.log('3) after answer (ta height', grew, '):', JSON.stringify(reply))

// 4. 暂停按钮 → PAUSED 卡
const pauseEnabled = await page.evaluate(() => {
  const btns = [...document.querySelectorAll('.btn-ghost')]
  const p = btns.find(b => b.textContent === '暂停')
  return p ? !p.disabled : null
})
console.log('4) pause enabled:', pauseEnabled)
await page.evaluate(() => { [...document.querySelectorAll('.btn-ghost')].find(b => b.textContent === '暂停')?.click() })
await new Promise(r => setTimeout(r, 2500))
const paused = await page.evaluate(() => ({
  card: document.querySelector('.gate-card .title')?.textContent,
  status: document.querySelector('.status-text')?.textContent
}))
console.log('   paused:', JSON.stringify(paused))

// 5. 继续 → 恢复输入
await page.evaluate(() => { const b = document.querySelector('.gate-card .btn-accent'); b?.click() })
await new Promise(r => setTimeout(r, 3000))
const resumed = await page.evaluate(() => ({
  composer: !!document.querySelector('.composer'),
  status: document.querySelector('.status-text')?.textContent
}))
console.log('5) resumed:', JSON.stringify(resumed))
console.log('pageerrors:', errors.length ? errors : 'none')
await browser.close()
