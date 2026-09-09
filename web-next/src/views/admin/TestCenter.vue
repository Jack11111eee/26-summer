<template>
  <div>
    <UiConfirm
      v-if="confirmState.show"
      :title="CONFIRM_META[confirmState.kind]?.title || '请确认'"
      :message="confirmTextMap[confirmState.kind]"
      :confirm-text="confirmState.kind === 'publish' ? '发布' : '确认'"
      :danger="confirmState.kind === 'bad_case' || confirmState.kind === 'eval_delete'"
      @close="confirmState.show = false"
      @confirm="onConfirm"
    />

    <header class="topbar">
      <div>
        <div class="topbar-title">测试<span>中心</span></div>
        <div class="topbar-meta">EVAL · TRACE · FEEDBACK</div>
      </div>
      <div class="topbar-actions">
        <button class="btn" @click="reloadAll">刷新</button>
      </div>
    </header>

    <UiTabs v-model="tab" :tabs="tabs" />

    <!-- Tab 1 评测运行 -->
    <template v-if="tab === 'eval'">
      <div class="cols" style="grid-template-columns: 1fr 280px">
        <div>
          <section class="block n2" style="margin-bottom: 14px">
            <div class="block-head"><span class="block-title">评分一致性</span></div>
            <p class="cell-sub" style="margin-bottom: 10px">对指定会话重复跑评分链路，检验输出稳定性。</p>
            <div class="filters" style="margin-bottom: 0">
              <input v-model="evalForm.sessionId" class="input" style="width: 260px" type="text" placeholder="session_id" />
              <input v-model.number="evalForm.runs" class="input" style="width: 90px" type="number" min="1" max="10" />
              <button class="btn primary" :disabled="running" @click="runConsistency">运行</button>
            </div>
          </section>

          <section class="block n2" style="margin-bottom: 14px">
            <div class="block-head"><span class="block-title">虚拟考生三档</span></div>
            <p class="cell-sub" style="margin-bottom: 10px">按岗位模型生成弱/中/强三档虚拟作答，验证区分度。</p>
            <div class="filters" style="margin-bottom: 0">
              <select v-model="evalForm.positionId" class="select" style="min-width: 220px">
                <option value="" disabled>选择岗位…</option>
                <option v-for="o in positionOptions" :key="o.position_id" :value="o.position_id">{{ o.name }}</option>
              </select>
              <button class="btn primary" :disabled="running" @click="runVirtual">运行</button>
            </div>
          </section>
          <!-- 当前任务卡 -->
          <section v-if="current" class="block card">
            <div class="block-head">
              <span class="block-title">{{ current.test_name }}</span>
              <span class="block-cnt">{{ current.task_id }}</span>
              <span v-if="current.status === 'running'" class="tag warm">RUNNING</span>
              <span v-else-if="current.status === 'completed'" class="tag tag-solid">COMPLETED</span>
              <span v-else class="tag tag-red">FAILED</span>
            </div>
            <p class="cell-sub" style="margin-bottom: 8px">
              创建 {{ formatTime(current.created_at) }}
              <template v-if="current.completed_at"> · 完成 {{ formatTime(current.completed_at) }}</template>
            </p>
            <pre class="raw" style="max-height: 420px">{{ prettyResult }}</pre>
          </section>
        </div>

        <!-- 右栏：运行历史（终态行可勾选/删除——SSOT §23，2026-09-09；运行中行禁选） -->
        <aside>
          <section class="block card">
            <div class="block-head">
              <span class="block-title">运行历史</span>
              <template v-if="history.length">
                <label v-if="deletableHistory.length" class="cell-sub" style="cursor: pointer; margin-right: 8px">
                  <input v-model="selectAll" type="checkbox" /> 全选
                </label>
                <button
                  v-if="confirmState.deleteIds.length"
                  class="row-btn row-btn-danger"
                  @click="askBatchDelete"
                >删除所选（{{ confirmState.deleteIds.length }}）</button>
              </template>
            </div>
            <table>
              <tbody>
                <tr v-for="h in history" :key="h.task_id" style="cursor: pointer" @click="loadTask(h.task_id)">
                  <td style="width: 28px" @click.stop>
                    <input
                      v-if="isTerminal(h)"
                      v-model="confirmState.deleteIds"
                      :value="h.task_id"
                      type="checkbox"
                      @click.stop
                    />
                  </td>
                  <td>
                    <div class="cell-main" style="font-size: 12px">{{ h.test_name }}</div>
                    <div class="cell-sub">{{ formatTime(h.created_at) }}</div>
                  </td>
                  <td>
                    <span v-if="h.status === 'completed'" class="tag tag-solid">完成</span>
                    <span v-else-if="h.status === 'failed'" class="tag tag-red">失败</span>
                    <span v-else class="tag warm">运行中</span>
                  </td>
                  <td v-if="isTerminal(h)" style="width: 44px">
                    <button class="row-btn row-btn-danger" @click.stop="askDeleteOne(h)">删除</button>
                  </td>
                  <td v-else></td>
                </tr>
                <tr v-if="!history.length"><td class="empty-row">暂无历史</td></tr>
              </tbody>
            </table>
          </section>
        </aside>
      </div>
    </template>

    <!-- Tab 2 Trace 查看器 -->
    <template v-else-if="tab === 'trace'">
      <div class="filters">
        <select v-model="traceFilters.call_type" class="select" @change="resetTrace">
          <option value="">全部 call_type</option>
          <option v-for="t in CALL_TYPES" :key="t" :value="t">{{ t }}</option>
        </select>
        <input v-model="traceFilters.ref_id" class="input" type="text" placeholder="ref_id（session / question…）" style="width: 240px" @keyup.enter="resetTrace" />
        <select v-model="traceFilters.success" class="select" @change="resetTrace">
          <option value="">全部结果</option>
          <option value="1">成功</option>
          <option value="0">失败</option>
        </select>
        <button class="btn" @click="resetTrace">查询</button>
      </div>

      <section class="block n2">
        <div class="block-head">
          <span class="block-title">调用留痕</span>
          <span class="block-cnt">{{ traceTotal }} 条</span>
        </div>
        <table>
          <thead>
            <tr><th style="width: 14%">调用类型</th><th style="width: 20%">关联ID</th><th class="num" style="width: 9%">尝试次数</th><th style="width: 9%">是否成功</th><th style="width: 14%">创建时间</th><th style="width: 34%">提示词</th></tr>
          </thead>
          <tbody>
            <tr v-for="t in traces" :key="t.trace_id" style="cursor: pointer" @click="openTrace(t)">
              <td><span class="tag">{{ t.call_type }}</span></td>
              <td v-clip class="cell-sub">{{ t.ref_id }}</td>
              <td class="num">{{ t.attempt }}</td>
              <td>
                <span v-if="t.success" class="tag tag-solid">OK</span>
                <span v-else class="tag tag-red">FAIL</span>
              </td>
              <td>{{ formatTime(t.created_at) }}</td>
              <td v-clip class="cell-sub">{{ t.prompt_preview }}</td>
            </tr>
            <tr v-if="!traces.length && !traceLoading"><td colspan="6" class="empty-row">无匹配留痕</td></tr>
          </tbody>
        </table>
        <div class="pager">
          <span>{{ traceTotal }} 条</span>
          <div class="pages">
            <button :disabled="tracePage <= 1" @click="pageTrace(-1)">‹</button>
            <button :disabled="tracePage >= traceMaxPage" @click="pageTrace(1)">›</button>
          </div>
          <span v-if="traceMaxPage > 1" class="jump">跳至 <input
            v-model="traceJumpRaw"
            class="input"
            type="number"
            min="1"
            :max="traceMaxPage"
            @keyup.enter="onTraceJump"
            @blur="onTraceJump"
          /> / {{ traceMaxPage }} 页</span>
        </div>
      </section>

      <!-- 单条 trace 详情 -->
      <UiDrawer v-if="traceDetail" :title="`Trace · ${traceDetail.call_type}`" @close="traceDetail = null">
        <p class="cell-sub" style="margin-bottom: 12px">
          ref {{ traceDetail.ref_id }} · attempt {{ traceDetail.attempt }} ·
          {{ traceDetail.success ? '成功' : '失败' }} · {{ formatTime(traceDetail.created_at) }}
        </p>
        <details class="fold" open>
          <summary><span class="caret">▶</span> prompt</summary>
          <div class="fold-body"><pre class="raw">{{ traceDetail.prompt || '—' }}</pre></div>
        </details>
        <details class="fold" open>
          <summary><span class="caret">▶</span> response</summary>
          <div class="fold-body"><pre class="raw">{{ traceDetail.response || '—' }}</pre></div>
        </details>
        <div v-if="traceDetail.error" class="banner" style="margin-top: 4px">
          <span>{{ traceDetail.error }}</span>
        </div>
      </UiDrawer>
    </template>

    <!-- Tab 3 反馈管理（异议反馈 / 意见反馈切换——SSOT §22.1） -->
    <template v-else>
      <div class="filters">
        <div class="tabs" style="margin-right: 12px">
          <button
            v-for="t in FEEDBACK_KINDS"
            :key="t.key"
            type="button"
            class="tab"
            :class="{ active: feedbackKind === t.key }"
            @click="onFeedbackKind(t.key)"
          >{{ t.label }}</button>
        </div>
        <select v-if="feedbackKind === 'objection'" v-model="feedbackStatus" class="select" @change="loadFeedback">
          <option value="">全部状态</option>
          <option value="pending">待处理</option>
          <option value="reviewed">已处理</option>
          <option value="bad_case">bad case</option>
        </select>
        <select v-else v-model="suggestionStatus" class="select" @change="loadSuggestions">
          <option value="">全部状态</option>
          <option value="pending">待处理</option>
          <option value="reviewed">已处理</option>
        </select>
      </div>

      <!-- 异议反馈（逐分异议——feedback 通道） -->
      <section v-if="feedbackKind === 'objection'" class="block n2">
        <div class="block-head">
          <span class="block-title">候选人异议</span>
          <span class="block-cnt">{{ feedbacks.length }} 条</span>
        </div>
        <table>
          <thead>
            <tr><th style="width: 11%">标准名</th><th style="width: 9%">类别</th><th style="width: 24%">反馈</th><th class="num" style="width: 7%">得分</th><th style="width: 9%">状态</th><th style="width: 12%">创建时间</th><th style="width: 28%">操作</th></tr>
          </thead>
          <tbody>
            <template v-for="f in feedbacks" :key="f.feedback_id">
              <tr>
                <td v-clip><span class="cell-main">{{ f.std_name }}</span></td>
                <td><span class="tag">{{ categoryLabel(f.category) }}</span></td>
                <td v-clip class="cell-sub">{{ f.feedback_text || '—' }}</td>
                <td class="num">{{ f.total_score ?? '—' }}</td>
                <td>
                  <span v-if="f.status === 'pending'" class="tag warm">待处理</span>
                  <span v-else-if="f.status === 'reviewed'" class="tag tag-solid">已处理</span>
                  <span v-else class="tag tag-red">BAD CASE</span>
                </td>
                <td>{{ formatTime(f.created_at) }}</td>
                <td>
                  <div class="row-actions">
                    <button v-if="f.status === 'pending'" class="row-btn" @click="askFeedback(f, 'review')">标记已处理</button>
                    <button v-if="f.status !== 'bad_case'" class="row-btn row-btn-danger" @click="askFeedback(f, 'bad_case')">标 bad case</button>
                    <button class="row-btn row-btn-solid" @click="askPublish(f)">发布报告</button>
                  </div>
                </td>
              </tr>
            </template>
            <tr v-if="!feedbacks.length && !feedbackLoading"><td colspan="7" class="empty-row">暂无反馈</td></tr>
          </tbody>
        </table>
      </section>

      <!-- 意见反馈（通用系统建议——suggestion 通道，§22.1） -->
      <section v-else class="block n2">
        <div class="block-head">
          <span class="block-title">意见反馈</span>
          <span class="block-cnt">{{ suggestions.length }} 条</span>
        </div>
        <table>
          <thead>
            <tr><th style="width: 14%">用户</th><th style="width: 16%">时间</th><th style="width: 32%">内容</th><th style="width: 10%">状态</th><th style="width: 16%">处理备注</th><th style="width: 12%">操作</th></tr>
          </thead>
          <tbody>
            <template v-for="s in suggestions" :key="s.suggestion_id">
              <tr>
                <td><span class="cell-main">{{ s.username || '—' }}</span></td>
                <td>{{ formatTime(s.created_at) }}</td>
                <td v-clip class="cell-sub">{{ s.text || '—' }}</td>
                <td>
                  <span v-if="s.status === 'pending'" class="tag warm">待处理</span>
                  <span v-else class="tag tag-solid">已处理</span>
                </td>
                <td v-clip class="cell-sub">{{ s.review_note || '—' }}</td>
                <td>
                  <div class="row-actions">
                    <button v-if="s.status === 'pending'" class="row-btn" @click="askSuggestion(s)">标记已处理</button>
                    <span v-else class="cell-sub" style="font-size: 11px">{{ formatTime(s.reviewed_at) }}</span>
                  </div>
                </td>
              </tr>
            </template>
            <tr v-if="!suggestions.length && !suggestionLoading"><td colspan="6" class="empty-row">暂无意见反馈</td></tr>
          </tbody>
        </table>
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { admin, adminPositions, errMsg } from '../../api'
import { UiTabs, UiDrawer, UiConfirm, toast } from '../../components/ui'
import { categoryLabel, formatTime } from '../../lib/labels'

defineOptions({ name: 'AdminTestCenter' }) // 壳内 keep-alive include 依名匹配（§5，2026-09-08）

const CALL_TYPES = ['extract', 'disambiguate', 'aggregate_level', 'question_gen', 'interviewer', 'refine', 'score', 'report']
const TRACE_LIMIT = 50

const tab = ref('eval')
const tabs = computed(() => [
  { key: 'eval', label: '评测运行' },
  { key: 'trace', label: 'Trace 查看器' },
  { key: 'feedback', label: '反馈管理' }
])

const running = ref(false)
const positionOptions = ref([])
const evalForm = reactive({ sessionId: '', runs: 3, positionId: '' })
const current = ref(null)
const history = ref([])

const traceFilters = reactive({ call_type: '', ref_id: '', success: '' })
const traces = ref([])
const traceTotal = ref(0)
const tracePage = ref(1)
const traceJumpRaw = ref('')
watch(tracePage, (p) => { traceJumpRaw.value = String(p) }, { immediate: true })
const traceLoading = ref(false)
const traceDetail = ref(null)
const traceMaxPage = computed(() => Math.max(1, Math.ceil(traceTotal.value / TRACE_LIMIT) || 1))

const feedbackKind = ref('objection') // 反馈区切换：objection（逐分异议）/ suggestion（意见反馈 §22.1）
const feedbackStatus = ref('') // ''=全部状态；默认全量而非锁死 pending
const feedbacks = ref([])
const feedbackLoading = ref(false)
const suggestionStatus = ref('') // ''=全部状态
const suggestions = ref([])
const suggestionLoading = ref(false)

const FEEDBACK_KINDS = [
  { key: 'objection', label: '异议反馈' },
  { key: 'suggestion', label: '意见反馈' }
]

function onFeedbackKind(kind) {
  if (feedbackKind.value === kind) return
  feedbackKind.value = kind
  if (kind === 'suggestion') loadSuggestions()
  else loadFeedback()
}

const confirmState = reactive({ show: false, kind: '', feedback: null, suggestion: null, deleteIds: [] })

const prettyResult = computed(() =>
  current.value?.result ? JSON.stringify(current.value.result, null, 2) : '— 生成中 —'
)

// ---- 历史删除（SSOT §23，2026-09-09）：仅终态行可删 ----
function isTerminal(h) {
  return h.status === 'completed' || h.status === 'failed'
}

// 历史重拉后清掉已消失行的勾选（删除完成/刷新均走 getHistory 后调用）
function pruneSelection() {
  const alive = new Set(history.value.map(h => h.task_id))
  confirmState.deleteIds = confirmState.deleteIds.filter(id => alive.has(id))
}

const deletableHistory = computed(() => history.value.filter(isTerminal))

// 全选 = 终态行全部勾上 / 取消 = 清空（-running 行天然不进 checkbox v-model）
const selectAll = computed({
  get: () => deletableHistory.value.length > 0
    && confirmState.deleteIds.length === deletableHistory.value.length,
  set: (v) => { confirmState.deleteIds = v ? deletableHistory.value.map(h => h.task_id) : [] }
})

// ---- 通用加载 ----
async function reloadAll() {
  try {
    const [oRes, hRes] = await Promise.all([
      // banked=1（SSOT §23，2026-09-09）：虚拟考生下拉只列已落库且使用中的 active 岗
      adminPositions.positionOptions({ status: 'active', banked: 1 }),
      admin.eval.getHistory()
    ])
    positionOptions.value = oRes.data
    history.value = hRes.data
    // 岗位过滤收紧后，已选岗位可能不再可选——清选防悬空提交
    if (evalForm.positionId && !positionOptions.value.some(o => o.position_id === evalForm.positionId)) {
      evalForm.positionId = ''
    }
    pruneSelection()
  } catch (e) {
    toast(errMsg(e, '加载失败'), 'error')
  }
  loadActiveTab()
}

// 当前 tab 对应列表：trace/feedback 切入即拉（eval 无列表）
function loadActiveTab() {
  if (tab.value === 'trace') loadTraces()
  else if (tab.value === 'feedback') {
    if (feedbackKind.value === 'suggestion') loadSuggestions()
    else loadFeedback()
  }
}

// 页内 tab 切换即重拉目标列表（与顶栏刷新/keep-alive 静默刷新同哲学，无首屏双拉：
// 首次 setup 的 reloadAll 已按当时 tab 拉过，watch 无 immediate）
watch(tab, loadActiveTab)

// ---- 评测运行 ----
let pollTimer = null
function stopPoll() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

async function runConsistency() {
  if (!evalForm.sessionId.trim()) {
    toast('请输入 session_id', 'warn')
    return
  }
  await launchTask(() => admin.eval.runConsistency(evalForm.sessionId.trim(), evalForm.runs || 3))
}

async function runVirtual() {
  if (!evalForm.positionId) {
    toast('请选择岗位', 'warn')
    return
  }
  await launchTask(() => admin.eval.runVirtualCandidates(evalForm.positionId))
}

async function launchTask(fn) {
  running.value = true
  try {
    const { data } = await fn()
    await loadTask(data.task_id)
    toast('评测任务已启动')
  } catch (e) {
    toast(errMsg(e, '任务启动失败'), 'error')
  } finally {
    running.value = false
  }
}

async function loadTask(taskId) {
  current.value = { task_id: taskId, test_name: '', status: 'running', result: null, created_at: '', completed_at: null }
  stopPoll()
  try {
    await pollTask()
  } catch (e) {
    toast(errMsg(e, '任务加载失败'), 'error')
    current.value = null
  }
}

async function pollTask() {
  const refresh = async () => {
    try {
      const { data } = await admin.eval.getResult(current.value.task_id)
      current.value = data
      if (data.status === 'running') return
      stopPoll()
      const hRes = await admin.eval.getHistory()
      history.value = hRes.data
      if (data.status === 'failed') toast('评测任务失败', 'error')
    } catch {
      /* 瞬时失败下轮重试 */
    }
  }
  await refresh()
  if (current.value?.status === 'running') {
    pollTimer = setInterval(refresh, 3000)
  }
}

// ---- Trace ----
async function loadTraces() {
  traceLoading.value = true
  try {
    const params = { limit: TRACE_LIMIT, offset: (tracePage.value - 1) * TRACE_LIMIT }
    if (traceFilters.call_type) params.call_type = traceFilters.call_type
    if (traceFilters.ref_id.trim()) params.ref_id = traceFilters.ref_id.trim()
    if (traceFilters.success !== '') params.success = traceFilters.success === '1'
    const { data } = await admin.trace.list(params)
    traces.value = data.traces
    traceTotal.value = data.total
    // 过滤后总页数变小时把当前页钳回末页，避免落在空页
    if (tracePage.value > traceMaxPage.value) tracePage.value = traceMaxPage.value
  } catch (e) {
    toast(errMsg(e, 'trace 加载失败'), 'error')
  } finally {
    traceLoading.value = false
  }
}

function resetTrace() {
  tracePage.value = 1
  loadTraces()
}

function pageTrace(dir) {
  tracePage.value = Math.min(Math.max(1, tracePage.value + dir), traceMaxPage.value)
  loadTraces()
}

// 跳转：回车/失焦触发，空/越界回退当前页；页码同步进输入框
function onTraceJump() {
  const n = parseInt(traceJumpRaw.value, 10)
  if (Number.isFinite(n) && n >= 1 && n <= traceMaxPage.value) {
    tracePage.value = n
    traceJumpRaw.value = String(n)
    loadTraces()
  } else {
    traceJumpRaw.value = String(tracePage.value)
  }
}

async function openTrace(t) {
  traceDetail.value = null
  try {
    const { data } = await admin.trace.getDetail(t.trace_id)
    traceDetail.value = data
  } catch (e) {
    toast(errMsg(e, 'trace 详情加载失败'), 'error')
  }
}

// ---- 反馈 ----
async function loadFeedback() {
  feedbackLoading.value = true
  try {
    const { data } = await admin.feedback.list(feedbackStatus.value || undefined)
    feedbacks.value = data
  } catch (e) {
    toast(errMsg(e, '反馈加载失败'), 'error')
  } finally {
    feedbackLoading.value = false
  }
}

// ---- 意见反馈（§22.1，镜像异议区交互）----
async function loadSuggestions() {
  suggestionLoading.value = true
  try {
    const { data } = await admin.suggestions.list(suggestionStatus.value || undefined)
    suggestions.value = data
  } catch (e) {
    toast(errMsg(e, '意见反馈加载失败'), 'error')
  } finally {
    suggestionLoading.value = false
  }
}

function askSuggestion(s) {
  confirmState.kind = 'suggestion_review'
  confirmState.suggestion = s
  confirmState.show = true
}

function askFeedback(f, kind) {
  confirmState.kind = kind
  confirmState.feedback = f
  confirmState.show = true
}

function askPublish(f) {
  confirmState.kind = 'publish'
  confirmState.feedback = f
  confirmState.show = true
}

// 删除所选（批量）/ 删除单条：确认后走同一段删除逻辑
function askBatchDelete() {
  if (!confirmState.deleteIds.length) return
  confirmState.kind = 'eval_delete'
  confirmState.show = true
}

function askDeleteOne(h) {
  confirmState.kind = 'eval_delete'
  confirmState.deleteIds = [h.task_id]
  confirmState.show = true
}

async function deleteSelected() {
  const ids = [...confirmState.deleteIds]
  try {
    if (ids.length === 1) await admin.eval.deleteResult(ids[0])
    else await admin.eval.batchDeleteResults(ids)
    confirmState.deleteIds = []
    toast(ids.length === 1 ? '已删除 1 条历史' : `已删除 ${ids.length} 条历史`)
    // 删除后重拉历史（含当前任务卡对应行被删的清理）
    const hRes = await admin.eval.getHistory()
    history.value = hRes.data
    pruneSelection()
    if (current.value && !history.value.some(h => h.task_id === current.value.task_id)) {
      current.value = null
      stopPoll()
    }
  } catch (e) {
    toast(errMsg(e, '删除失败'), 'error')
  }
}

const CONFIRM_META = {
  review: { title: '标记已处理', act: (f) => admin.feedback.review(f.feedback_id), ok: '已标记处理', reload: loadFeedback },
  'bad_case': { title: '标 bad case', act: (f) => admin.feedback.badCase(f.feedback_id), ok: '已标 bad case', reload: loadFeedback },
  publish: { title: '发布报告', act: (f) => admin.reports.publish(f.report_id), ok: '报告已发布', reload: loadFeedback },
  suggestion_review: {
    title: '标记已处理',
    // 意见反馈经 suggestion 通道（§22.1）——note 留空与异议 review 动作同形态
    act: (s) => admin.suggestions.review(s.suggestion_id),
    ok: '已标记处理',
    reload: loadSuggestions
  },
  eval_delete: {
    title: '删除运行历史',
    act: deleteSelected,
    ok: '',
    reload: null // deleteSelected 自带历史重拉
  }
}

const confirmTextMap = computed(() => ({
  review: '确认标记「' + confirmState.feedback?.std_name + '」异议为已处理？（不改分，仅留痕）',
  'bad_case': '确认标「' + confirmState.feedback?.std_name + '」异议为 bad case？（沉淀为评测素材）',
  publish: '确认为该反馈所属报告执行发布？（发布后考生可见最终报告）',
  suggestion_review: '确认标记用户「' + confirmState.suggestion?.username + '」的意见反馈为已处理？（reviewed + 处理留痕）',
  eval_delete: '确认删除 ' + (confirmState.deleteIds.length === 1 ? '这 1 条' : '所选 ' + confirmState.deleteIds.length + ' 条')
    + '评测运行历史？删除后不可恢复（仅清运行记录，不动业务数据）。'
}))

async function onConfirm() {
  const meta = CONFIRM_META[confirmState.kind]
  const target = confirmState.kind === 'suggestion_review' ? confirmState.suggestion : confirmState.feedback
  confirmState.show = false
  // eval_delete 目标在 confirmState.deleteIds，不走 feedback/suggestion 实体
  if (!meta || (confirmState.kind !== 'eval_delete' && !target)) return
  try {
    await meta.act(target)
    if (meta.ok) toast(meta.ok)
    if (meta.reload) await meta.reload()
  } catch (e) {
    toast(errMsg(e, '操作失败'), 'error')
  }
}

import { onBeforeUnmount, onActivated, onDeactivated } from 'vue'
onBeforeUnmount(stopPoll)

// keep-alive（§5，2026-09-08）：激活 = 静默刷新保筛选保 tab（booted 守卫防首屏双拉）；
// 失活 = 停轮询（keep-alive 下路由切换不触发 unmount，不停表则后台常跑）
let booted = false
onActivated(() => {
  if (!booted) { booted = true; return }
  reloadAll()
})
onDeactivated(stopPoll)

reloadAll()
</script>
