<template>
  <AdminNav />
  <div class="page">
    <el-card shadow="never" class="panel">
      <!-- 页头 -->
      <div class="head">
        <div>
          <el-button text @click="$router.push(`/admin/positions/${positionId}`)">← 返回岗位详情</el-button>
          <h2 class="title">版本历史与对比</h2>
        </div>
      </div>

      <!-- 版本列表 -->
      <el-table :data="versions" v-loading="loading" stripe class="mb16">
        <el-table-column label="版本" width="90" align="center">
          <template #default="{ row }">v{{ row.version }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="确认人" width="120">
          <template #default="{ row }">{{ row.confirmed_by || '—' }}</template>
        </el-table-column>
        <el-table-column label="确认时间" width="180">
          <template #default="{ row }">{{ formatTime(row.confirmed_at) }}</template>
        </el-table-column>
        <el-table-column label="创建时间" width="180">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="model_id" label="模型 ID" min-width="140" show-overflow-tooltip />
        <template #empty>
          <el-empty description="暂无版本记录" />
        </template>
      </el-table>

      <!-- 版本对比选择 -->
      <div class="compare-bar">
        <span class="compare-label">基准版本</span>
        <el-select v-model="baseId" placeholder="旧版本" class="compare-select">
          <el-option v-for="v in versions" :key="v.model_id" :value="v.model_id"
            :label="`v${v.version}（${statusLabel(v.status)}）`" :disabled="v.model_id === compareId" />
        </el-select>
        <span class="compare-label">对比版本</span>
        <el-select v-model="compareId" placeholder="新版本" class="compare-select">
          <el-option v-for="v in versions" :key="v.model_id" :value="v.model_id"
            :label="`v${v.version}（${statusLabel(v.status)}）`" :disabled="v.model_id === baseId" />
        </el-select>
        <el-button type="primary" :disabled="!baseId || !compareId" :loading="diffing" @click="onCompare">
          对比
        </el-button>
      </div>

      <!-- diff 结果 -->
      <div v-if="diffLoaded" v-loading="diffing">
        <template v-if="changes.length">
          <div v-for="(c, i) in changes" :key="i" class="change-row" :class="`change-${c.change}`">
            <div class="change-head">
              <el-tag size="small" :type="changeType(c.change)" effect="dark">{{ changeLabel(c.change) }}</el-tag>
              <span class="change-name">{{ c.std_name }}</span>
              <el-tag size="small" effect="plain">{{ categoryLabel(c.category) }}</el-tag>
            </div>
            <!-- 字段级差异 -->
            <div v-if="c.change === 'field'" class="diff-list">
              <div v-for="d in c.diffs" :key="d.field" class="diff-item">
                <span class="diff-field">{{ d.label }}</span>
                <span class="diff-old">{{ fmtField(d.field, d.old) }}</span>
                <span class="diff-arrow">→</span>
                <span class="diff-new">{{ fmtField(d.field, d.new) }}</span>
              </div>
            </div>
            <!-- 新增/删除：展示该项要点 -->
            <div v-else class="diff-list">
              <span class="diff-brief">{{ itemBrief(c.change === 'added' ? c.new : c.old) }}</span>
            </div>
          </div>
        </template>
        <el-empty v-else description="两版本能力项完全一致" :image-size="60" />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import AdminNav from '../../components/AdminNav.vue'
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '../../api'

const route = useRoute()
const router = useRouter()
const positionId = route.params.id

const versions = ref([])
const loading = ref(false)

// 对比选择与结果
const baseId = ref('') // 基准（旧）
const compareId = ref('') // 对比（新）
const changes = ref([])
const diffing = ref(false)
const diffLoaded = ref(false)

async function load() {
  loading.value = true
  try {
    const { data } = await api.get(`/admin/positions/${positionId}/versions`)
    versions.value = data
  } finally {
    loading.value = false
  }
}

async function onCompare() {
  diffing.value = true
  try {
    const { data } = await api.get(`/admin/models/${compareId.value}/diff`, {
      params: { against: baseId.value }
    })
    changes.value = data.changes
    diffLoaded.value = true
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '对比失败')
  } finally {
    diffing.value = false
  }
}

function statusLabel(s) {
  return { draft: '草稿', confirmed: '已确认', stalled: '滞留' }[s] || s
}
function statusType(s) {
  return { draft: 'info', confirmed: 'success', stalled: 'danger' }[s] || 'info'
}
function changeLabel(c) {
  return { added: '新增', removed: '删除', field: '变更' }[c] || c
}
function changeType(c) {
  return { added: 'success', removed: 'danger', field: 'warning' }[c] || 'info'
}
function categoryLabel(c) {
  return { hard_skill: '硬技能', soft_skill: '软技能', experience: '经验', qualification: '门槛' }[c] || c
}
function importanceLabel(i) {
  return { required: '必备', preferred: '优先', plus: '加分' }[i] || i
}
function formatTime(iso) {
  return iso ? new Date(iso).toLocaleString('zh-CN', { hour12: false }) : '—'
}
// 权重/occurrence 以百分比显示；importance 转中文；其余原样
function fmtField(field, v) {
  if (v === null || v === undefined) return '—'
  if (field === 'weight' || field === 'occurrence') {
    const n = Number(v)
    return (n <= 1 ? (n * 100).toFixed(0) : n.toFixed(0)) + '%'
  }
  if (field === 'importance') return importanceLabel(v)
  if (field === 'gate') return v ? '是' : '否'
  return v
}
// 新增/删除项的一行摘要
function itemBrief(it) {
  if (!it) return ''
  const parts = []
  if (it.required_level != null) parts.push(`Lv${it.required_level}`)
  parts.push(importanceLabel(it.importance))
  parts.push(`权重 ${fmtField('weight', it.weight)}`)
  if (it.years != null) parts.push(`${it.years}年`)
  return parts.join(' · ')
}

onMounted(load)
</script>

<style scoped>
.page {
  padding: 24px;
}
.panel {
  max-width: 1100px;
  margin: 0 auto;
  border-radius: 12px;
}
.head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
}
.title {
  margin: 4px 0 0;
  color: #303133;
}
.mb16 {
  margin-bottom: 16px;
}
.compare-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 20px;
}
.compare-label {
  color: #606266;
  font-size: 14px;
}
.compare-select {
  width: 220px;
}
.change-row {
  border: 1px solid #ebeef5;
  border-left-width: 4px;
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 10px;
}
.change-added {
  border-left-color: #67c23a;
}
.change-removed {
  border-left-color: #f56c6c;
}
.change-field {
  border-left-color: #e6a23c;
}
.change-head {
  display: flex;
  align-items: center;
  gap: 10px;
}
.change-name {
  font-weight: 600;
  color: #303133;
}
.diff-list {
  margin-top: 8px;
  padding-left: 4px;
}
.diff-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  line-height: 1.8;
}
.diff-field {
  color: #909399;
  min-width: 48px;
}
.diff-old {
  color: #f56c6c;
  text-decoration: line-through;
}
.diff-arrow {
  color: #909399;
}
.diff-new {
  color: #67c23a;
  font-weight: 600;
}
.diff-brief {
  color: #606266;
  font-size: 13px;
}
</style>
