import { ref } from 'vue'

// 暖纸双主题（candidate.css 契约）：?theme= → localStorage → prefers-color-scheme。
// themeRef 各页共享同一 localStorage 键；直接监听 storage 事件跨页签同步（轻量）。
const KEY = 'web-next-theme'
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
  return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function apply() {
  document.documentElement.setAttribute('data-theme', theme.value)
}

apply()

export function useTheme() {
  function toggle() {
    theme.value = theme.value === 'dark' ? 'light' : 'dark'
    try { localStorage.setItem(KEY, theme.value) } catch { /* ignore */ }
    apply()
  }
  return { theme, toggle }
}
