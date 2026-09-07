<template>
  <table v-if="items.length">
    <thead>
      <tr>
        <th>name</th><th>category</th><th class="num">required_level</th><th>importance</th>
        <th v-if="hasYears" class="num">years</th><th>evidence</th>
      </tr>
    </thead>
    <tbody>
      <tr v-for="(it, i) in items" :key="i">
        <td><span class="cell-main">{{ it.name }}</span></td>
        <td><span class="tag">{{ categoryLabel(it.category) }}</span></td>
        <td class="num">{{ it.required_level ?? '—' }}</td>
        <td>{{ importanceLabel(it.importance) }}</td>
        <td v-if="hasYears" class="num">{{ it.years ?? '—' }}</td>
        <td>
          <span class="cell-sub" :title="evidenceText(it)">{{ evidenceBrief(it) }}</span>
        </td>
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

function evidenceText(it) {
  const ev = it.evidence || []
  return ev.join('\n')
}
function evidenceBrief(it) {
  const ev = it.evidence || []
  if (!ev.length) return '—'
  const first = String(ev[0])
  return ev.length > 1 ? `${first} …（${ev.length} 条）` : first
}
</script>
