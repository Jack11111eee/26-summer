<template>
  <div class="pager">
    <span>{{ total }} 条</span>
    <div class="pages">
      <button type="button" :disabled="page <= 1" @click="go(page - 1)">‹</button>
      <button v-for="p in pageList" :key="p" type="button" class="cur-btn" :class="{ cur: p === page }" @click="go(p)">{{ p }}</button>
      <button type="button" :disabled="page >= maxPage" @click="go(page + 1)">›</button>
    </div>
    <select class="select" :value="pageSize" aria-label="每页条数" @change="onSize">
      <option v-for="s in sizeOptions" :key="s" :value="s">{{ s }} / 页</option>
    </select>
  </div>
</template>

<script setup>
// 分页器：{items,total} 契约（后端 clamp 上限 100）。页码窗口 5 个，超出折叠省略。
import { computed } from 'vue'

const props = defineProps({
  page: { type: Number, required: true },
  pageSize: { type: Number, default: 20 },
  total: { type: Number, default: 0 }
})
const emit = defineEmits(['update:page', 'update:page-size', 'change'])

const sizeOptions = [10, 20, 50, 100]
const maxPage = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize) || 1))

const pageList = computed(() => {
  const m = maxPage.value
  if (m <= 7) return Array.from({ length: m }, (_, i) => i + 1)
  const cur = props.page
  const start = Math.max(1, Math.min(cur - 2, m - 4))
  const end = Math.min(m, start + 4)
  return Array.from({ length: end - start + 1 }, (_, i) => start + i)
})

function go(p) {
  const clamped = Math.min(Math.max(1, p), maxPage.value)
  if (clamped !== props.page) {
    emit('update:page', clamped)
    emit('change')
  }
}

function onSize(e) {
  emit('update:page-size', Number(e.target.value))
  emit('update:page', 1)
  emit('change')
}
</script>
