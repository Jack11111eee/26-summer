// v-clip 指令：用于 table-layout:fixed 表格的长文本单元格。
// 检测内容溢出（scrollWidth > clientWidth），溢出时把全称挂到 el.dataset.tip，
// 由 admin.css 的 .tip-host::after 气泡在悬停 0.5s 后显示；未溢出不挂（无气泡）。
export const clip = {
  mounted: clipEl,
  updated: clipEl,
  beforeUnmount(el) {
    delete el.dataset.tip
  }
}

function clipEl(el) {
  if (el.dataset.tipTimer) {
    clearTimeout(el.dataset.tipTimer)
    el.dataset.tipTimer = ''
  }
  el.classList.add('clip')
  // 内容可能还在渲染途，rAF 后量宽准确
  requestAnimationFrame(() => {
    if (el.scrollWidth > el.clientWidth + 1) el.dataset.tip = el.textContent.trim()
    else delete el.dataset.tip
  })
}
