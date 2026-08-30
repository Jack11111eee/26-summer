<template>
  <el-table v-if="items && items.length" :data="items" size="small" border>
    <el-table-column prop="name" label="能力项" min-width="120" />
    <el-table-column label="类目" width="110">
      <template #default="{ row }">
        <el-tag size="small" effect="plain">{{ categoryLabel(row.category) }}</el-tag>
      </template>
    </el-table-column>
    <el-table-column label="等级" width="70" align="center">
      <template #default="{ row }">Lv{{ row.required_level }}</template>
    </el-table-column>
    <el-table-column label="重要性" width="90">
      <template #default="{ row }">
        <el-tag size="small" :type="importanceType(row.importance)">{{ importanceLabel(row.importance) }}</el-tag>
      </template>
    </el-table-column>
    <el-table-column v-if="hasYears" label="年限" width="70" align="center">
      <template #default="{ row }">{{ row.years != null ? row.years + '年' : '—' }}</template>
    </el-table-column>
    <el-table-column label="原文证据" min-width="180">
      <template #default="{ row }">
        <span v-for="(ev, i) in row.evidence || []" :key="i" class="ev">「{{ ev }}」</span>
      </template>
    </el-table-column>
  </el-table>
  <el-empty v-else description="（无数据）" :image-size="60" />
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  items: { type: Array, default: () => [] }
})

const hasYears = computed(() => props.items.some((it) => it.years != null))

function categoryLabel(c) {
  return { hard_skill: '硬技能', soft_skill: '软技能', experience: '经验', qualification: '门槛' }[c] || c
}
function importanceLabel(i) {
  return { required: '必备', preferred: '优先', plus: '加分' }[i] || i
}
function importanceType(i) {
  return { required: 'danger', preferred: 'primary', plus: 'info' }[i] || 'info'
}
</script>

<style scoped>
.ev {
  color: #606266;
  margin-right: 6px;
}
</style>
