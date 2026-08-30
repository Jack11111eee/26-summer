<template>
  <AdminNav />
  <div class="page">
    <!-- 页头 -->
    <div class="head-wrap">
      <h2 class="title">岗位库</h2>
      <div>
        <el-button @click="loadAll">刷新</el-button>
      </div>
    </div>

    <!-- 顶部待办统计条 -->
    <el-row :gutter="16" class="mb16">
      <el-col :span="8">
        <el-card shadow="never" class="stat" :class="{ hot: todos.pending_positions > 0 }">
          <div class="stat-num">{{ todos.pending_positions }}</div>
          <div class="stat-label">待审新岗位</div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="never" class="stat" :class="{ hot: todos.stalled_models > 0 }">
          <div class="stat-num">{{ todos.stalled_models }}</div>
          <div class="stat-label">stalled 模型</div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="never" class="stat" :class="{ hot: todos.orphan_jds > 0 }">
          <div class="stat-num">{{ todos.orphan_jds }}</div>
          <div class="stat-label">待归属 JD</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 待办处理区 -->
    <el-card shadow="never" class="panel mb16" v-if="hasTodo">
      <el-collapse v-model="activeTodo">
        <!-- 待审新岗位 -->
        <el-collapse-item :title="`待审新岗位（${pendingPositions.length}）`" name="pending">
          <el-table :data="pendingPositions" v-loading="pendingLoading" size="small">
            <el-table-column prop="name" label="岗位名称" min-width="160" />
            <el-table-column prop="jd_count" label="JD 数" width="80" align="center" />
            <el-table-column prop="created_at" label="创建时间" width="180">
              <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="150" fixed="right">
              <template #default="{ row }">
                <el-button size="small" type="success" @click="onReview(row, 'approve')">通过</el-button>
                <el-button size="small" type="danger" plain @click="onReview(row, 'reject')">拒绝</el-button>
              </template>
            </el-table-column>
            <template #empty><el-empty description="暂无待审岗位" :image-size="60" /></template>
          </el-table>
        </el-collapse-item>

        <!-- 待归属 JD -->
        <el-collapse-item :title="`待归属 JD（${orphanJds.length}）`" name="orphan">
          <el-table :data="orphanJds" v-loading="orphanLoading" size="small">
            <el-table-column prop="job_title" label="岗位名称" min-width="140">
              <template #default="{ row }">{{ row.job_title || '（未解析）' }}</template>
            </el-table-column>
            <el-table-column prop="company" label="公司" min-width="110">
              <template #default="{ row }">{{ row.company || '—' }}</template>
            </el-table-column>
            <el-table-column prop="source_type" label="来源" width="80">
              <template #default="{ row }">
                <el-tag size="small" effect="plain">{{ sourceLabel(row.source_type) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="导入时间" width="170">
              <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="改归到岗位" min-width="220" fixed="right">
              <template #default="{ row }">
                <el-select
                  v-model="reassignMap[row.jd_id]"
                  placeholder="选择岗位"
                  size="small"
                  style="width: 130px; margin-right: 8px"
                >
                  <el-option
                    v-for="p in positions"
                    :key="p.position_id"
                    :label="p.name"
                    :value="p.position_id"
                  />
                </el-select>
                <el-button
                  size="small"
                  type="primary"
                  :disabled="!reassignMap[row.jd_id]"
                  @click="onReassign(row)"
                >
                  改归
                </el-button>
              </template>
            </el-table-column>
            <template #empty><el-empty description="暂无待归属 JD" :image-size="60" /></template>
          </el-table>
        </el-collapse-item>
      </el-collapse>
    </el-card>

    <!-- 岗位列表 -->
    <el-card shadow="never" class="panel">
      <el-table :data="positions" v-loading="loading" stripe>
        <el-table-column prop="name" label="岗位名称" min-width="180" />
        <el-table-column label="状态" width="130">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'active' ? 'success' : 'warning'">
              {{ row.status === 'active' ? 'active' : '待审核' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="jd_count" label="JD 数" width="90" align="center" />
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain @click="$router.push(`/admin/positions/${row.position_id}`)">
              进入详情
            </el-button>
            <el-button size="small" type="success" plain @click="$router.push(`/admin/positions/${row.position_id}/review`)">
              模型审核
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无岗位。导入 JD 后系统会自动归岗创建岗位。" />
        </template>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../../api'
import AdminNav from '../../components/AdminNav.vue'

// 待办统计
const todos = ref({ pending_positions: 0, stalled_models: 0, orphan_jds: 0 })
// 待办列表
const pendingPositions = ref([])
const orphanJds = ref([])
const pendingLoading = ref(false)
const orphanLoading = ref(false)
const activeTodo = ref(['pending', 'orphan'])
// 每行的改归岗位选择
const reassignMap = ref({})
// 岗位列表
const positions = ref([])
const loading = ref(false)

const hasTodo = computed(() => pendingPositions.value.length > 0 || orphanJds.value.length > 0)

async function loadTodos() {
  const { data } = await api.get('/admin/todos')
  todos.value = data
}

async function loadPositions() {
  loading.value = true
  try {
    const { data } = await api.get('/admin/positions')
    positions.value = data
  } finally {
    loading.value = false
  }
}

async function loadPending() {
  pendingLoading.value = true
  try {
    const { data } = await api.get('/admin/positions/pending')
    pendingPositions.value = data
  } finally {
    pendingLoading.value = false
  }
}

async function loadOrphan() {
  orphanLoading.value = true
  try {
    const { data } = await api.get('/admin/jds/orphan')
    orphanJds.value = data
  } finally {
    orphanLoading.value = false
  }
}

function loadAll() {
  loadTodos()
  loadPositions()
  loadPending()
  loadOrphan()
}

// 岗位审核：approve 直接过；reject 需二次确认
async function onReview(row, action) {
  if (action === 'reject') {
    try {
      await ElMessageBox.confirm(
        `拒绝后岗位「${row.name}」将被撤销，其下 JD 退回待归属队列。确认拒绝？`,
        '拒绝岗位',
        { confirmButtonText: '确认拒绝', cancelButtonText: '取消', type: 'warning' }
      )
    } catch {
      return // 取消
    }
  }
  try {
    await api.post(`/admin/positions/${row.position_id}/review`, { action })
    ElMessage.success(action === 'approve' ? '已通过' : '已拒绝')
    loadAll()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  }
}

// JD 改归
async function onReassign(row) {
  try {
    await api.post(`/admin/jds/${row.jd_id}/reassign`, { position_id: reassignMap.value[row.jd_id] })
    ElMessage.success('已改归')
    loadAll()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '改归失败')
  }
}

function sourceLabel(t) {
  return { paste: '粘贴', file: '文件', plugin: '插件' }[t] || t
}
function formatTime(iso) {
  return iso ? new Date(iso).toLocaleString('zh-CN', { hour12: false }) : '—'
}

onMounted(loadAll)
</script>

<style scoped>
.page {
  padding: 24px;
  max-width: 1100px;
  margin: 0 auto;
}
.head-wrap {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.title {
  margin: 0;
  color: #303133;
}
.panel {
  border-radius: 12px;
}
.mb16 {
  margin-bottom: 16px;
}
/* 待办统计卡 */
.stat {
  border-radius: 12px;
  text-align: center;
}
.stat-num {
  font-size: 28px;
  font-weight: 600;
  color: #606266;
  line-height: 1.2;
}
.stat-label {
  font-size: 13px;
  color: #909399;
  margin-top: 4px;
}
/* 有待办时高亮为橙 */
.stat.hot {
  border-color: #e6a23c;
  background: #fdf6ec;
}
.stat.hot .stat-num {
  color: #e6a23c;
}
</style>
