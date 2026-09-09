import { ref } from 'vue'

// 暖纸双主题（candidate.css 契约）：?theme= → localStorage → 默认日间。
// themeRef 各页共享同一 localStorage 键；直接监听 storage 事件跨页签同步（轻量）。
// 默认日间（SSOT §5 2026-09-09 裁决）：无记录不再跟随系统 prefers-color-scheme。
// 另提供按场次的测评主题快照（asmt-theme:<session_id>）——异议详情覆盖层用它
// 跟随候选人当时看报告/答题的主题（无快照回落日间）。
const KEY = 'web-next-theme'
const ASMT_KEY = (sessionId) => `asmt-theme:${sessionId}`
const theme = ref(readTheme())

function readTheme() {
  try {
    const q = new URLSearchParams(location.search).get('theme')
    if (q === 'dark' || q === 'light') return q
  } catch { /* ignore */ }
  try {
    const v = localStorage.getItem(KEY)
    if (v === 'dark' || v === 'light') return v
  } catch { /* ignore */ }
  return 'light'
}

function apply() {
  document.documentElement.setAttribute('data-theme', theme.value)
}

apply()

// 测评主题快照（SSOT §22.2 覆盖层跟随）：Chat / Report 进入与切换时写入；
// 覆盖层读取。无效值（清库/手工改坏）一律得 null，调用方回落 'light'。
export function readAsmtTheme(sessionId) {
  try {
    const v = localStorage.getItem(ASMT_KEY(sessionId))
    if (v === 'dark' || v === 'light') return v
  } catch { /* ignore */ }
  return null
}

export function writeAsmtTheme(sessionId, value) {
  if (value !== 'dark' && value !== 'light') return
  try { localStorage.setItem(ASMT_KEY(sessionId), value) } catch { /* ignore */ }
}

export function useTheme() {
  function toggle() {
    theme.value = theme.value === 'dark' ? 'light' : 'dark'
    try { localStorage.setItem(KEY, theme.value) } catch { /* ignore */ }
    apply()
  }
  return { theme, toggle }
}
