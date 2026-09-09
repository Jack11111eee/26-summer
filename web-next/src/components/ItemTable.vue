<template>
  <table v-if="items.length">
    <thead>
      <tr>
        <th style="width: 16%">名称</th><th style="width: 10%">类别</th><th class="num" style="width: 14%">要求等级</th><th style="width: 12%">重要性</th>
        <th v-if="hasYears" class="num" style="width: 8%">年限</th><th style="width: 46%">证据</th>
      </tr>
    </thead>
    <tbody>
      <tr v-for="(it, i) in items" :key="i">
        <td v-clip><span class="cell-main">{{ it.name }}</span></td>
        <td><span class="tag">{{ categoryLabel(it.category) }}</span></td>
        <td class="num">{{ it.required_level ?? '—' }}</td>
        <td>{{ importanceLabel(it.importance) }}</td>
        <td v-if="hasYears" class="num">{{ it.years ?? '—' }}</td>
        <td v-clip class="cell-sub">{{ evidenceBrief(it) }}</td>
      </tr>
    </tbody>
  </table>
</template>

<script setup>
// JD 工序留档 raw_items / std_items 只读表（与旧版 ItemTable 同字段消费）。
import { computed } from 'vue'
import { categoryLabel, importanceLabel } from '../lib/labels'

const props = defineProps({
  items: { type: Array, default: () => [] }
})

const hasYears = computed(() => props.items.some((it) => it.years != null))

function evidenceBrief(it) {
  const ev = it.evidence || []
  if (!ev.length) return '—'
  const first = String(ev[0])
  return ev.length > 1 ? `${first} …（${ev.length} 条）` : first
}
</script>
