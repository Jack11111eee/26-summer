<template>
  <div class="grail">
    <!-- 通栏头 -->
    <header class="grail-head">
      <div class="gh-brand">
        <div class="gh-mark">测</div>
        <div class="gh-name">胜任力测评 · 管理端</div>
      </div>
      <div class="gh-divider"></div>
      <div class="gh-crumb">测试中心 <b>P8</b></div>
      <div class="gh-actions">
        <span class="aside-note">{{ auth.user?.username }}</span>
        <button class="btn btn-sm" @click="onLogout">退出</button>
      </div>
    </header>

    <div class="grail-body">
      <!-- 左栏：管理导航 -->
      <aside class="rail-left">
        <div class="rl-section">导航</div>
        <div
          v-for="item in navItems"
          :key="item.path"
          class="nav-item"
          :class="{ active: item.path === '/admin/test-center' }"
          @click="$router.push(item.path)"
        >
          <span class="icon">{{ item.icon }}</span>{{ item.label }}
        </div>
        <div class="rl-user">
          <div class="avatar">{{ auth.user?.username?.[0] || 'A' }}</div>
          <div>
            <div class="user-name">{{ auth.user?.username }}</div>
            <div class="user-role">admin</div>
          </div>
        </div>
      </aside>

      <!-- 中栏：三 tab -->
      <main class="rail-center">
        <div class="rc-head">
          <div class="rc-title">测试中心</div>
          <div class="rc-meta">
            <span>评测运行</span><span>·</span><span>trace 查看器</span><span>·</span><span>反馈·bad case</span>
          </div>
        </div>

        <el-tabs v-model="activeTab">
          <!-- ============ Tab 1: 评测运行 ============ -->
          <el-tab-pane label="评测运行" name="eval">
            <div class="rc-section">一致性测试<span class="cnt">scoring_consistency</span></div>
            <div class="rr-card">
              <div class="form-row">
                <input v-model="consistencyForm.session_id" class="input mono" placeholder="session_id（必填）" />
                <input v-model.number="consistencyForm.runs" type="number" min="1" class="input input-sm-fixed" placeholder="runs" />
                <button class="btn btn-primary" :disabled="!consistencyForm.session_id || evalRunning" @click="onRunConsistency">
                  运行一致性测试
                </button>
              </div>
            </div>

            <div class="rc-section">虚拟考生测试<span class="cnt">virtual_candidates</span></div>
            <div class="rr-card">
              <div class="form-row">
                <input v-model="virtualForm.position_id" class="input mono" placeholder="position_id（必填）" />
                <button class="btn btn-primary" :disabled="!virtualForm.position_id || evalRunning" @click="onRunVirtual">
                  运行虚拟考生测试
                </button>
              </div>
            </div>

            <template v-if="currentTask">
              <div class="rc-section">当前任务<span class="cnt mono">{{ currentTask.task_id }}</span></div>
              <div class="rr-card">
                <div class="kv-row">
                  <span class="kv-key">测试</span><span class="mono">{{ currentTask.test_name }}</span>
                  <span class="kv-key">状态</span>
                  <span class="tag" :class="statusTagClass(currentTask.status)">{{ currentTask.status }}</span>
                </div>
                <div v-if="currentTask.result" class="result-block">
                  <div class="kv-row" v-if="currentTask.result.passed !== undefined">
                    <span class="kv-key">结论</span>
                    <span class="tag" :class="currentTask.result.passed ? 'tag-green' : 'tag-red'">
                      {{ currentTask.result.passed ? 'passed' : 'failed' }}
                    </span>
                  </div>
                  <pre class="pre-block">{{ prettyJson(currentTask.result) }}</pre>
                </div>
                <div v-else-if="currentTask.status === 'running'" class="aside-note">运行中，每 3s 轮询…</div>
              </div>
            </template>

            <div class="rc-section">历史<span class="cnt">最近 5 次</span></div>
            <div class="table-wrap">
              <table>
                <thead>
                  <tr><th>task_id</th><th>test_name</th><th>status</th><th>created_at</th></tr>
                </thead>
                <tbody>
                  <tr v-for="row in evalHistory.slice(0, 5)" :key="row.task_id" @click="loadTask(row.task_id)">
                    <td class="mono">{{ row.task_id }}</td>
                    <td>{{ row.test_name }}</td>
                    <td><span class="tag" :class="statusTagClass(row.status)">{{ row.status }}</span></td>
                    <td class="mono">{{ formatTime(row.created_at) }}</td>
                  </tr>
                  <tr v-if="!evalHistory.length"><td colspan="4" class="aside-note">暂无评测历史</td></tr>
                </tbody>
              </table>
            </div>
          </el-tab-pane>

          <!-- ============ Tab 2: Trace 查看器 ============ -->
          <el-tab-pane label="trace 查看器" name="trace">
            <div class="rc-section">筛选</div>
            <div class="rr-card">
              <div class="form-row">
                <select v-model="traceFilters.call_type" class="select">
                  <option value="">全部 call_type</option>
                  <option v-for="ct in callTypes" :key="ct" :value="ct">{{ ct }}</option>
                </select>
                <input v-model="traceFilters.ref_id" class="input mono" placeholder="ref_id" />
                <select v-model="traceFilters.success" class="select">
                  <option value="">全部</option>
                  <option value="true">成功</option>
                  <option value="false">失败</option>
                </select>
                <button class="btn btn-primary" @click="loadTraces">查询</button>
              </div>
            </div>

            <div class="rc-section">结果<span class="cnt">{{ traceTotal }} 条</span></div>
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>trace_id</th><th>call_type</th><th>ref_id</th><th>attempt</th>
                    <th>success</th><th>created_at</th><th>prompt 预览</th>
                  </tr>
                </thead>
                <tbody>
                  <template v-for="row in traces" :key="row.trace_id">
                    <tr class="clickable" @click="toggleTrace(row)">
                      <td class="mono">{{ row.trace_id }}</td>
                      <td><span class="tag tag-grey">{{ row.call_type }}</span></td>
                      <td class="mono">{{ row.ref_id }}</td>
                      <td class="num">{{ row.attempt }}</td>
                      <td>
                        <span class="tag" :class="row.success ? 'tag-green' : 'tag-red'">
                          {{ row.success ? '成功' : '失败' }}
                        </span>
                      </td>
                      <td class="mono">{{ formatTime(row.created_at) }}</td>
                      <td class="mono preview-cell">{{ row.prompt_preview }}</td>
                    </tr>
                    <tr v-if="expandedTraceId === row.trace_id" class="detail-row">
                      <td colspan="7">
                        <div v-if="traceDetailLoading" class="aside-note">加载中…</div>
                        <template v-else-if="traceDetail">
                          <div class="kv-row">
                            <span class="kv-key">model</span><span class="mono">{{ traceDetail.model || '—' }}</span>
                            <span class="kv-key">temperature</span><span class="mono">{{ traceDetail.temperature ?? '—' }}</span>
                            <span class="kv-key">latency</span><span class="mono">{{ traceDetail.latency_ms ?? '—' }} ms</span>
                            <span class="kv-key">tokens</span>
                            <span class="mono">{{ traceDetail.prompt_tokens ?? '—' }}/{{ traceDetail.completion_tokens ?? '—' }}</span>
                          </div>
                          <div class="detail-label">prompt</div>
                          <pre class="pre-block">{{ traceDetail.prompt }}</pre>
                          <div class="detail-label">response</div>
                          <pre class="pre-block">{{ traceDetail.response }}</pre>
                          <template v-if="traceDetail.error">
                            <div class="detail-label">error</div>
                            <pre class="pre-block err">{{ traceDetail.error }}</pre>
                          </template>
                        </template>
                      </td>
                    </tr>
                  </template>
                  <tr v-if="!traces.length"><td colspan="7" class="aside-note">暂无数据</td></tr>
                </tbody>
              </table>
            </div>
          </el-tab-pane>

          <!-- ============ Tab 3: 反馈管理 ============ -->
          <el-tab-pane label="反馈管理" name="feedback">
            <div class="rc-section">筛选</div>
            <div class="rr-card">
              <div class="form-row">
                <select v-model="feedbackStatus" class="select" @change="loadFeedback">
                  <option value="">全部</option>
                  <option value="pending">pending</option>
                  <option value="reviewed">reviewed</option>
                  <option value="bad_case">bad_case</option>
                </select>
                <button class="btn" @click="loadFeedback">刷新</button>
              </div>
            </div>

            <div class="rc-section">反馈列表<span class="cnt">{{ feedbackList.length }} 条</span></div>
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>反馈项</th><th>分类</th><th>内容</th><th>状态</th><th>创建时间</th><th>报告上下文</th><th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  <template v-for="row in feedbackList" :key="row.feedback_id">
                    <tr class="clickable" @click="toggleFeedback(row.feedback_id)">
                      <td class="cell-main">{{ row.std_name }}</td>
                      <td><span class="tag tag-grey">{{ row.category }}</span></td>
                      <td class="preview-cell">{{ row.feedback_text }}</td>
                      <td><span class="tag" :class="feedbackStatusClass(row.status)">{{ row.status }}</span></td>
                      <td class="mono">{{ formatTime(row.created_at) }}</td>
                      <td class="mono num">Σ {{ row.total_score?.toFixed?.(1) ?? row.total_score }}</td>
                      <td @click.stop>
                        <template v-if="row.status === 'pending'">
                          <button class="btn btn-sm btn-success-ghost" @click="onReview(row)">标记已处理</button>
                          <button class="btn btn-sm btn-danger-ghost" @click="onBadCase(row)">标 bad case</button>
                        </template>
                        <span v-else class="aside-note">{{ row.status === 'reviewed' ? '已处理' : 'bad case' }}</span>
                      </td>
                    </tr>
                    <tr v-if="expandedFeedbackId === row.feedback_id" class="detail-row">
                      <td colspan="7">
                        <div class="kv-row">
                          <span class="kv-key">feedback_id</span><span class="mono">{{ row.feedback_id }}</span>
                          <span class="kv-key">report_id</span><span class="mono">{{ row.report_id }}</span>
                          <span class="kv-key">session_id</span><span class="mono">{{ row.session_id }}</span>
                          <span class="kv-key">item_id</span><span class="mono">{{ row.item_id }}</span>
                        </div>
                        <div class="detail-label">反馈全文</div>
                        <div class="quote">{{ row.feedback_text }}</div>
                      </td>
                    </tr>
                  </template>
                  <tr v-if="!feedbackList.length"><td colspan="7" class="aside-note">暂无反馈</td></tr>
                </tbody>
              </table>
            </div>
          </el-tab-pane>
        </el-tabs>
      </main>

      <!-- 右栏：系统状态 -->
      <aside class="rail-right">
        <div class="rr-title">最近一次评测</div>
        <div class="rr-card" v-if="lastEval">
          <div class="kv-row">
            <span class="tag" :class="statusTagClass(lastEval.status)">{{ lastEval.status }}</span>
          </div>
          <div class="cell-sub mono">{{ lastEval.test_name }}</div>
          <div class="cell-sub mono">{{ formatTime(lastEval.created_at) }}</div>
        </div>
        <div class="rr-card aside-note" v-else>暂无</div>

        <div class="rr-title">待处理反馈</div>
        <div class="rr-callout amber" @click="goPendingFeedback">
          <div class="rr-callout-top">
            <span class="callout-dot callout-dot-amber"></span>
            <span class="rr-callout-label">pending</span>
            <span class="rr-callout-arrow">→</span>
          </div>
          <div class="rr-callout-num">{{ pendingCount }}</div>
          <div class="rr-callout-foot">点击跳转反馈 tab</div>
        </div>
      </aside>
    </div>

    <footer class="grail-foot">
      <span>P8 · 测试中心</span>
      <span class="f-right">
        <span class="ok">●</span><span>M7 测试闭环</span>
      </span>
    </footer>
  </div>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { admin } from '../../api'
import { useAuthStore } from '../../stores/auth'

const router = useRouter()
const auth = useAuthStore()

const navItems = [
  { path: '/admin/positions', label: '岗位库', icon: '▤' },
  { path: '/admin/dict', label: '能力词典', icon: '□' },
  { path: '/admin/users', label: '用户管理', icon: '◍' },
  { path: '/admin/test-center', label: '测试中心', icon: '✓' },
]

const activeTab = ref('eval')

/* ---------------- Tab 1: 评测运行 ---------------- */
const consistencyForm = reactive({ session_id: '', runs: 3 })
const virtualForm = reactive({ position_id: '' })
const currentTask = ref(null)
const evalHistory = ref([])
const evalRunning = computed(() => currentTask.value?.status === 'running')
let pollTimer = null

async function onRunConsistency() {
  try {
    const { data } = await admin.eval.runConsistency(consistencyForm.session_id, consistencyForm.runs || 3)
    ElMessage.success(`任务已创建 ${data.task_id}`)
    await loadTask(data.task_id)
    startPolling(data.task_id)
    loadHistory()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '触发失败')
  }
}

async function onRunVirtual() {
  try {
    const { data } = await admin.eval.runVirtualCandidates(virtualForm.position_id)
    ElMessage.success(`任务已创建 ${data.task_id}`)
    await loadTask(data.task_id)
    startPolling(data.task_id)
    loadHistory()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '触发失败')
  }
}

async function loadTask(taskId) {
  try {
    const { data } = await admin.eval.getResult(taskId)
    currentTask.value = data
    if (data.status === 'running') startPolling(taskId)
    else stopPolling()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '查询任务失败')
  }
}

function startPolling(taskId) {
  stopPolling()
  pollTimer = setInterval(async () => {
    try {
      const { data } = await admin.eval.getResult(taskId)
      currentTask.value = data
      if (data.status !== 'running') {
        stopPolling()
        loadHistory()
      }
    } catch { stopPolling() }
  }, 3000)
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

async function loadHistory() {
  try {
    const { data } = await admin.eval.getHistory()
    evalHistory.value = data
  } catch { /* 静默 */ }
}

/* ---------------- Tab 2: Trace 查看器 ---------------- */
const callTypes = ['extract', 'disambiguate', 'aggregate_level', 'question_gen', 'interviewer', 'refine', 'score', 'report']
const traceFilters = reactive({ call_type: '', ref_id: '', success: '' })
const traces = ref([])
const traceTotal = ref(0)
const expandedTraceId = ref(null)
const traceDetail = ref(null)
const traceDetailLoading = ref(false)

async function loadTraces() {
  const params = { limit: 50 }
  if (traceFilters.call_type) params.call_type = traceFilters.call_type
  if (traceFilters.ref_id) params.ref_id = traceFilters.ref_id
  if (traceFilters.success !== '') params.success = traceFilters.success
  try {
    const { data } = await admin.trace.list(params)
    traces.value = data.traces
    traceTotal.value = data.total
    expandedTraceId.value = null
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '查询失败')
  }
}

async function toggleTrace(row) {
  if (expandedTraceId.value === row.trace_id) {
    expandedTraceId.value = null
    traceDetail.value = null
    return
  }
  expandedTraceId.value = row.trace_id
  traceDetailLoading.value = true
  traceDetail.value = null
  try {
    const { data } = await admin.trace.getDetail(row.trace_id)
    traceDetail.value = data
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '加载详情失败')
  } finally {
    traceDetailLoading.value = false
  }
}

/* ---------------- Tab 3: 反馈管理 ---------------- */
const feedbackStatus = ref('')
const feedbackList = ref([])
const expandedFeedbackId = ref(null)

const pendingCount = computed(() => feedbackList.value.filter(f => f.status === 'pending').length)

async function loadFeedback() {
  try {
    const { data } = await admin.feedback.list(feedbackStatus.value || undefined)
    feedbackList.value = data
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '加载失败')
  }
}

function toggleFeedback(id) {
  expandedFeedbackId.value = expandedFeedbackId.value === id ? null : id
}

async function onReview(row) {
  try {
    await ElMessageBox.confirm(`将反馈 ${row.feedback_id} 标记为已处理？`, '确认', { type: 'info' })
  } catch { return }
  try {
    await admin.feedback.review(row.feedback_id)
    ElMessage.success('已标记')
    loadFeedback()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  }
}

async function onBadCase(row) {
  try {
    await ElMessageBox.confirm(`将反馈 ${row.feedback_id} 标为 bad case？`, '确认', { type: 'warning' })
  } catch { return }
  try {
    await admin.feedback.badCase(row.feedback_id)
    ElMessage.success('已标为 bad case')
    loadFeedback()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  }
}

function goPendingFeedback() {
  activeTab.value = 'feedback'
  feedbackStatus.value = 'pending'
  loadFeedback()
}

/* ---------------- 公共 ---------------- */
function statusTagClass(s) {
  if (s === 'completed') return 'tag-green'
  if (s === 'failed') return 'tag-red'
  if (s === 'running') return 'tag-amber'
  return 'tag-grey'
}

function feedbackStatusClass(s) {
  if (s === 'reviewed') return 'tag-green'
  if (s === 'pending') return 'tag-amber'
  if (s === 'bad_case') return 'tag-red'
  return 'tag-grey'
}

function formatTime(iso) {
  return iso ? new Date(iso).toLocaleString('zh-CN', { hour12: false }) : '—'
}

function prettyJson(o) {
  try { return JSON.stringify(o, null, 2) } catch { return String(o) }
}

const lastEval = computed(() => evalHistory.value[0] || null)

function onLogout() {
  auth.logout()
  router.push('/login')
}

onMounted(() => {
  loadHistory()
  loadFeedback()
})

onBeforeUnmount(stopPolling)
</script>

<style scoped>
/* 仅做布局微调；视觉令牌全部走 grail-notion.css */
.form-row {
  display: flex;
  gap: 8px;
  align-items: center;
}
.form-row .input,
.form-row .select { flex: 1; min-width: 0; }
.form-row .input-sm-fixed { flex: 0 0 80px; }
.form-row .btn { flex-shrink: 0; }

.kv-row {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  margin-bottom: 6px;
}
.kv-key { font-size: 12px; color: var(--ink-3); }
.kv-row .mono { font-size: 12px; }

.result-block { margin-top: 8px; }

.pre-block {
  font-family: var(--mono); font-size: 11px; line-height: 1.6;
  background: var(--panel-2); border: 1px solid var(--line); border-radius: 5px;
  padding: 10px 12px; margin: 6px 0;
  max-height: 400px; overflow: auto;
  white-space: pre-wrap; word-break: break-all;
  color: var(--ink-1);
}
.pre-block.err { color: var(--red); background: var(--red-bg); border-color: var(--red); }

.detail-label {
  font-size: 11px; font-weight: 600; color: var(--ink-3);
  margin: 10px 2px 4px; text-transform: uppercase; letter-spacing: 0.4px;
}

.clickable { cursor: pointer; }
.detail-row td { background: var(--panel-2); }

.preview-cell {
  max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  display: block;
}

.grail-foot { justify-content: space-between; }
</style>
