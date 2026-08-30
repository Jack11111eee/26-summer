<template>
  <CandidateNav />
  <div class="page">
    <el-card shadow="never" class="panel">
      <!-- 页头 -->
      <div class="head">
        <div>
          <el-button text @click="$router.push('/assessment/positions')">← 返回岗位列表</el-button>
          <h2 class="title">{{ model?.position_name || '岗位测评' }}</h2>
          <div v-if="meta.version" class="subtitle">
            <el-tag size="small" effect="plain">模型 v{{ meta.version }}</el-tag>
          </div>
        </div>
      </div>

      <el-alert type="info" :closable="false" class="mb16"
        title="交互式测评由模块二提供，敬请期待。以下为该岗位已确认的胜任力模型（只读）。" />

      <div v-loading="loading">
        <template v-if="model">
          <!-- 按类目分组展示能力项 -->
          <div v-for="cat in categoryOrder" :key="cat" class="group">
            <template v-if="groups[cat]?.length">
              <div class="cat-head">{{ categoryLabel(cat) }}（{{ groups[cat].length }}）</div>
              <el-table :data="groups[cat]" size="small" border>
                <el-table-column prop="std_name" label="能力项" min-width="140" />
                <el-table-column label="等级" width="80" align="center">
                  <template #default="{ row }">
                    {{ row.required_level != null ? 'Lv' + row.required_level : '—' }}
                  </template>
                </el-table-column>
                <el-table-column label="重要性" width="90">
                  <template #default="{ row }">
                    <el-tag size="small" :type="importanceType(row.importance)">
                      {{ importanceLabel(row.importance) }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="权重" width="90" align="center">
                  <template #default="{ row }">{{ pct(row.weight) }}%</template>
                </el-table-column>
              </el-table>
            </template>
          </div>

          <!-- 测评入口（后端本期返回 501） -->
          <div class="actions">
            <el-button type="primary" size="large" :loading="starting" @click="onStart">开始测评</el-button>
          </div>
        </template>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import CandidateNav from '../../components/CandidateNav.vue'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '../../api'
import { useAuthStore } from '../../stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const positionId = route.params.id

const meta = ref({}) // {model_id, version}
const model = ref(null) // {position_name, items[]}
const loading = ref(false)
const starting = ref(false)

const categoryOrder = ['hard_skill', 'soft_skill', 'experience', 'qualification']

// 按类目分组（保持固定顺序）
const groups = computed(() => {
  const g = {}
  for (const it of model.value?.items || []) {
    ;(g[it.category] ||= []).push(it)
  }
  return g
})

async function load() {
  loading.value = true
  try {
    const { data } = await api.get(`/assessment/positions/${positionId}/model`)
    meta.value = { model_id: data.model_id, version: data.version }
    model.value = data.model
  } finally {
    loading.value = false
  }
}

// 开始测评：模块二未上线，后端返回 501，捕获后提示
async function onStart() {
  starting.value = true
  try {
    await api.post('/assessment/sessions', { position_id: positionId })
  } catch (e) {
    if (e.response?.status === 501) {
      ElMessage.warning('测评功能尚未上线（模块二）')
    } else {
      ElMessage.error(e.response?.data?.detail || '创建测评会话失败')
    }
  } finally {
    starting.value = false
  }
}


function categoryLabel(c) {
  return { hard_skill: '硬技能', soft_skill: '软技能', experience: '经验', qualification: '门槛' }[c] || c
}
function importanceLabel(i) {
  return { required: '必备', preferred: '优先', plus: '加分' }[i] || i
}
function importanceType(i) {
  return { required: 'danger', preferred: 'primary', plus: 'info' }[i] || 'info'
}
// 权重 0-1 小数 -> 百分比整数
function pct(v) {
  if (v === null || v === undefined) return '—'
  const n = Number(v)
  return n <= 1 ? (n * 100).toFixed(0) : n.toFixed(0)
}

onMounted(load)
</script>

<style scoped>
.page {
  padding: 24px;
}
.panel {
  max-width: 960px;
  margin: 0 auto;
  border-radius: 12px;
}
.head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 12px;
}
.title {
  margin: 4px 0 0;
  color: #303133;
}
.subtitle {
  margin-top: 6px;
}
.mb16 {
  margin-bottom: 16px;
}
.group {
  margin-bottom: 20px;
}
.cat-head {
  font-weight: 600;
  color: #303133;
  margin-bottom: 8px;
}
.actions {
  display: flex;
  justify-content: center;
  margin-top: 24px;
}
</style>
