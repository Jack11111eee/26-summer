<template>
  <div class="pager">
    <span>{{ total }} 条</span>
    <div class="pages">
      <button type="button" :disabled="page <= 1" @click="go(page - 1)">‹</button>
      <template v-for="(p, i) in pageList" :key="`${p}-${i}`">
        <span v-if="p === '…'" class="dots">…</span>
        <button v-else type="button" class="cur-btn" :class="{ cur: p === page }" @click="go(p)">{{ p }}</button>
      </template>
      <button type="button" :disabled="page >= maxPage" @click="go(page + 1)">›</button>
    </div>
    <span v-if="maxPage > 1" class="jump">跳至 <input
      v-model="jumpRaw"
      class="input"
      type="number"
      min="1"
      :max="maxPage"
      @keyup.enter="onJump"
      @blur="onJump"
    /> / {{ maxPage }} 页</span>
    <select class="select" :value="pageSize" aria-label="每页条数" @change="onSize">
      <option v-for="s in sizeOptions" :key="s" :value="s">{{ s }} / 页</option>
    </select>
  </div>
</template>

<script setup>
// 分页器：{items,total} 契约（后端 clamp 上限 100）。
// 页码窗口：{1,2,3} ∪ {cur-1,cur,cur+1} ∪ {末3页} 合并，组间不连续处插省略号；
// 总页数 ≤ 7 时全部平铺无省略。总页数 > 1 时提供「跳至 xx / N 页」输入跳转。
import { computed, ref, watch } from 'vue'

const props = defineProps({
  page: { type: Number, required: true },
  pageSize: { type: Number, default: 10 },
  total: { type: Number, default: 0 }
})
const emit = defineEmits(['update:page', 'update:page-size', 'change'])

const jumpRaw = ref('')
watch(() => props.page, (p) => { jumpRaw.value = String(p) }, { immediate: true })
const sizeOptions = [10, 20, 50, 100]
const maxPage = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize) || 1))

const pageList = computed(() => {
  const m = maxPage.value
  if (m <= 7) return Array.from({ length: m }, (_, i) => i + 1)
  const groups = [new Set([1, 2, 3]), new Set([props.page - 1, props.page, props.page + 1]), new Set([m - 2, m - 1, m])]
  const all = new Set()
  for (const g of groups) for (const p of g) {
    if (p >= 1 && p <= m) all.add(p) // 当前页近边界时窗口与头/尾组自然重叠合并
  }
  const nums = [...all].sort((a, b) => a - b)
  const out = []
  let prev = 0
  for (const n of nums) {
    if (n - prev > 1) out.push('…')
    out.push(n)
    prev = n
  }
  return out
})

function go(p) {
  const clamped = Math.min(Math.max(1, p), maxPage.value)
  if (clamped !== props.page) {
    emit('update:page', clamped)
    emit('change')
  }
}

// 跳转：回车或失焦触发；空/非法输入回退显示当前页，越界钳制到 [1, maxPage]
function onJump() {
  const n = parseInt(jumpRaw.value, 10)
  if (!Number.isFinite(n)) { jumpRaw.value = String(props.page); return }
  if (n < 1 || n > maxPage.value) { jumpRaw.value = String(props.page); return }
  if (n !== props.page) {
    emit('update:page', n)
    emit('change')
  }
  jumpRaw.value = String(n)
}

function onSize(e) {
  emit('update:page-size', Number(e.target.value))
  emit('update:page', 1)
  emit('change')
}
</script>
