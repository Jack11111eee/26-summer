<template>
  <AdminNav />
  <div class="page">
    <el-card shadow="never" class="panel">
      <!-- 页头 -->
      <div class="head">
        <div>
          <el-button text @click="$router.push('/admin/positions')">← 返回岗位库</el-button>
          <h2 class="title">{{ positionName || '岗位详情' }}</h2>
        </div>
        <div>
          <el-button type="success" plain @click="$router.push(`/admin/positions/${positionId}/review`)">
            模型审核
          </el-button>
          <el-button type="primary" @click="importVisible = true">+ 导入 JD</el-button>
        </div>
      </div>

      <!-- JD 列表 -->
      <el-table :data="jds" v-loading="loading" stripe>
        <el-table-column prop="job_title" label="岗位名称" min-width="140">
          <template #default="{ row }">{{ row.job_title || '（解析中）' }}</template>
        </el-table-column>
        <el-table-column prop="company" label="公司" min-width="120">
          <template #default="{ row }">{{ row.company || '—' }}</template>
        </el-table-column>
        <el-table-column prop="source_type" label="来源" width="90">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ sourceLabel(row.source_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
            <el-tooltip v-if="row.low_confidence" content="要求块为空或过短，解析置信度低" placement="top">
              <el-tag type="warning" size="small" effect="plain" class="ml4">低置信</el-tag>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="导入时间" width="180">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openDetail(row)">工序留档</el-button>
            <el-button v-if="row.status === 'failed'" size="small" type="warning" @click="onReparse(row)">
              重新解析
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无 JD，点击右上角「导入 JD」开始" />
        </template>
      </el-table>
    </el-card>

    <!-- 导入 JD 弹窗 -->
    <el-dialog v-model="importVisible" title="导入 JD" width="560px" @closed="resetImport">
      <el-tabs v-model="importTab">
        <el-tab-pane label="粘贴文本" name="paste">
          <el-input
            v-model="importText"
            type="textarea"
            :rows="10"
            placeholder="粘贴 JD 全文（岗位职责 + 任职要求）…"
          />
          <el-input v-model="importCompany" placeholder="公司名（可选，已脱敏）" class="mt12" />
        </el-tab-pane>
        <el-tab-pane label="JSONL 文件" name="file">
          <el-upload
            ref="uploadRef"
            drag
            :auto-upload="false"
            :limit="1"
            accept=".jsonl,.txt"
            :on-change="onFileChange"
            :on-exceed="onFileExceed"
          >
            <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
            <div class="el-upload__text">拖拽文件到此处，或 <em>点击选择</em></div>
            <template #tip>
              <div class="el-upload__tip">每行一条 JSON：{"jd_text": "...", "company": "可选"}</div>
            </template>
          </el-upload>
        </el-tab-pane>
      </el-tabs>
      <template #footer>
        <el-button @click="importVisible = false">取消</el-button>
        <el-button type="primary" :loading="importing" @click="onImportSubmit">导入并解析</el-button>
      </template>
    </el-dialog>

    <!-- 工序留档抽屉 -->
    <el-drawer v-model="detailVisible" size="52%" :title="`工序留档 · ${detail.job_title || ''}`">
      <div v-loading="detailLoading" class="drawer-body">
        <template v-if="detail.jd_id">
          <div class="kv">
            <el-tag :type="statusType(detail.status)">{{ statusLabel(detail.status) }}</el-tag>
            <el-tag v-if="detail.low_confidence" type="warning" effect="plain" class="ml8">低置信</el-tag>
            <span class="kv-time">{{ formatTime(detail.created_at) }}</span>
          </div>
          <el-alert v-if="detail.error_msg" type="error" :title="`解析失败：${detail.error_msg}`" :closable="false" class="mb12" />

          <el-collapse v-model="activeSections">
            <el-collapse-item title="① 原文" name="raw">
              <pre class="mono">{{ detail.raw_text }}</pre>
            </el-collapse-item>
            <el-collapse-item title="② 清洗结果" name="cleaned">
              <pre class="mono">{{ detail.cleaned_text || '（未生成）' }}</pre>
            </el-collapse-item>
            <el-collapse-item :title="`③ 抽取 raw_items（${(detail.raw_items || []).length} 项）`" name="raw_items">
              <ItemTable :items="detail.raw_items" />
            </el-collapse-item>
            <el-collapse-item :title="`④ 消歧 std_items（${(detail.std_items || []).length} 项）`" name="std_items">
              <ItemTable :items="detail.std_items" />
            </el-collapse-item>
          </el-collapse>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import AdminNav from '../../components/AdminNav.vue'
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import api from '../../api'
import ItemTable from '../../components/ItemTable.vue'

const route = useRoute()
const router = useRouter()
const positionId = route.params.id

const positionName = ref('')
const jds = ref([])
const loading = ref(false)

// 导入弹窗
const importVisible = ref(false)
const importTab = ref('paste')
const importText = ref('')
const importCompany = ref('')
const importing = ref(false)
const uploadRef = ref()
const importFile = ref(null)

// 抽屉
const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref({})
const activeSections = ref(['raw', 'cleaned', 'raw_items', 'std_items'])

let pollTimer = null

async function loadPosition() {
  const { data } = await api.get('/admin/positions')
  const cur = data.find((p) => p.position_id === positionId)
  positionName.value = cur ? cur.name : ''
}

async function loadJds() {
  loading.value = true
  try {
    const { data } = await api.get(`/admin/positions/${positionId}/jds`)
    jds.value = data
    // 有未终态的 JD 才继续轮询
    const pending = data.some((j) => j.status === 'imported' || j.status === 'parsing')
    if (pending && !pollTimer) startPoll()
    if (!pending && pollTimer) stopPoll()
  } finally {
    loading.value = false
  }
}

function startPoll() {
  pollTimer = setInterval(loadJds, 5000)
}
function stopPoll() {
  clearInterval(pollTimer)
  pollTimer = null
}

function onFileChange(file) {
  importFile.value = file.raw
}
function onFileExceed(files) {
  uploadRef.value.clearFiles()
  uploadRef.value.handleStart(files[0])
  importFile.value = files[0]
}

async function onImportSubmit() {
  importing.value = true
  try {
    if (importTab.value === 'paste') {
      if (!importText.value.trim()) {
        ElMessage.warning('请粘贴 JD 文本')
        importing.value = false
        return
      }
      await api.post('/admin/jds/import', { jd_text: importText.value, company: importCompany.value || null })
    } else {
      if (!importFile.value) {
        ElMessage.warning('请选择 JSONL 文件')
        importing.value = false
        return
      }
      const fd = new FormData()
      fd.append('file', importFile.value)
      await api.post('/admin/jds/import-file', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
    }
    ElMessage.success('已导入，解析进行中…')
    importVisible.value = false
    loadJds()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '导入失败')
  } finally {
    importing.value = false
  }
}

async function openDetail(row) {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = {}
  try {
    const { data } = await api.get(`/admin/jds/${row.jd_id}`)
    detail.value = data
  } finally {
    detailLoading.value = false
  }
}

async function onReparse(row) {
  await api.post(`/admin/jds/${row.jd_id}/reparse`)
  ElMessage.info('已重新提交解析')
  loadJds()
}

function resetImport() {
  importText.value = ''
  importCompany.value = ''
  importFile.value = null
  importTab.value = 'paste'
}

function sourceLabel(t) {
  return { paste: '粘贴', file: '文件', plugin: '插件' }[t] || t
}
function statusLabel(s) {
  return { imported: '已导入', parsing: '解析中', parsed: '已解析', failed: '失败' }[s] || s
}
function statusType(s) {
  return { imported: 'info', parsing: 'primary', parsed: 'success', failed: 'danger' }[s] || 'info'
}
function formatTime(iso) {
  return iso ? new Date(iso).toLocaleString('zh-CN', { hour12: false }) : '—'
}

onMounted(() => {
  loadPosition()
  loadJds()
})
onBeforeUnmount(stopPoll)
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
.mt12 {
  margin-top: 12px;
}
.ml4 {
  margin-left: 4px;
}
.ml8 {
  margin-left: 8px;
}
.mb12 {
  margin-bottom: 12px;
}
.kv {
  display: flex;
  align-items: center;
  margin-bottom: 12px;
}
.kv-time {
  margin-left: auto;
  color: #909399;
  font-size: 13px;
}
.mono {
  white-space: pre-wrap;
  word-break: break-word;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 13px;
  background: #f5f7fa;
  padding: 12px;
  border-radius: 6px;
  margin: 0;
}
</style>
