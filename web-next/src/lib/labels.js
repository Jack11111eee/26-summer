// 展示层标签/格式化集中定义（消除联调前端里逐页重复的同名函数）。

export const CATEGORY_LABELS = {
  hard_skill: '硬技能',
  soft_skill: '软技能',
  experience: '经验',
  qualification: '资格'
}

export const IMPORTANCE_LABELS = {
  required: '必备',
  preferred: '优选',
  plus: '加分'
}

export const JD_STATUS_LABELS = {
  imported: '已导入',
  parsing: '解析中',
  parsed: '已解析',
  failed: '失败'
}

export const MODEL_STATUS_LABELS = {
  draft: '草稿',
  confirmed: '已确认',
  stalled: '滞留'
}

export const POSITION_STATUS_LABELS = {
  active: '上架',
  inactive: '下架',
  pending_review: '待审核'
}

export const DICT_STATUS_LABELS = {
  active: '启用',
  disabled: '停用'
}

export const SOURCE_LABELS = {
  paste: '粘贴',
  file: '文件',
  plugin: '插件'
}

export const SCORE_STATE_LABELS = {
  NO_DATA: '未观测到有效回答',
  NOT_MEASURED: '未纳入计分',
  IMPUTED_LOW: '按低档补算',
  IMPUTED_DEFAULT: '按默认档补算',
  OBSERVED: '有观测数据'
}

export function categoryLabel(c) {
  return CATEGORY_LABELS[c] || c || '—'
}

export function importanceLabel(v) {
  return IMPORTANCE_LABELS[v] || v || '—'
}

// 0-1 权重 → 百分比显示（保留 1 位小数，去尾零）
export function pct(v) {
  if (v == null || Number.isNaN(Number(v))) return '—'
  const p = Number(v) * 100
  return `${Math.round(p * 10) / 10}%`
}

// ISO 时间 → 本地可读短格式（列表列通用）
export function formatTime(v) {
  if (!v) return '—'
  const d = new Date(v)
  if (Number.isNaN(d.getTime())) return String(v)
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

// ISO 时间 → HH:MM（聊天气泡时间戳）
export function hmTime(v) {
  if (!v) return ''
  const d = new Date(v)
  if (Number.isNaN(d.getTime())) return ''
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}`
}
