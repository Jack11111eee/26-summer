<template>
  <div class="toasts" aria-live="polite">
    <div v-for="t in items" :key="t.id" class="toast" :class="t.type">{{ t.text }}</div>
  </div>
</template>

<script>
// 全局 toast：单一 <UiToast/> 实例由 App.vue 挂在根，业务侧 import { toast } 调用。
// 样式云端到云端双体系各有一份（.admin .toasts / .candidate .toasts），toast 自身不选色。
import { reactive } from 'vue'

const state = reactive({ items: [] })
let seq = 0

export function toast(text, type = 'info', duration = 3200) {
  const id = ++seq
  state.items.push({ id, text, type })
  setTimeout(() => {
    const i = state.items.findIndex((t) => t.id === id)
    if (i !== -1) state.items.splice(i, 1)
  }, duration)
}

export function installToast(app) {
  app.config.globalProperties.$toast = toast
}

export default {
  name: 'UiToast',
  setup() {
    return { items: state.items }
  }
}
</script>
