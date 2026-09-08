<template>
  <div>
    <UiConfirm
      v-if="confirmState.show"
      :title="CONFIRM_META[confirmState.kind]?.title || '请确认'"
      :message="confirmTextMap[confirmState.kind]"
      :confirm-text="confirmState.kind === 'publish' ? '发布' : '确认'"
      :danger="confirmState.kind === 'bad_case'"
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

        <!-- 右栏：运行历史 -->
        <aside>
          <section class="block card">
            <div class="block-head"><span class="block-title">运行历史</span></div>
            <table>
              <tbody>
                <tr v-for="h in history" :key="h.task_id" style="cursor: pointer" @click="loadTask(h.task_id)">
                  <td>
                    <div class="cell-main" style="font-size: 12px">{{ h.test_name }}</div>
                    <div class="cell-sub">{{ formatTime(h.created_at) }}</div>
                  </td>
                  <td>
                    <span v-if="h.status === 'completed'" class="tag tag-solid">完成</span>
                    <span v-else-if="h.status === 'failed'" class="tag tag-red">失败</span>
                    <span v-else class="tag warm">运行中</span>
                  </td>
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
            <tr><th style="width: 14%">call_type</th><th style="width: 20%">ref_id</th><th class="num" style="width: 9%">attempt</th><th style="width: 9%">success</th><th style="width: 14%">created_at</th><th style="width: 34%">prompt</th></tr>
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
            <button :disabled="traceOffset === 0" @click="pageTrace(-1)">‹</button>
            <button :disabled="traceOffset + TRACE_LIMIT >= traceTotal" @click="pageTrace(1)">›</button>
          </div>
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
            <tr><th style="width: 14%">std_name</th><th style="width: 10%">category</th><th style="width: 28%">feedback</th><th class="num" style="width: 8%">score</th><th style="width: 10%">status</th><th style="width: 14%">created_at</th><th style="width: 16%; text-align: right">action</th></tr>
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
            <tr><th style="width: 14%">用户</th><th style="width: 16%">时间</th><th style="width: 32%">内容</th><th style="width: 10%">status</th><th style="width: 16%">处理备注</th><th style="width: 12%; text-align: right">action</th></tr>
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
import { computed, reactive, ref } from 'vue'
import { admin, adminPositions, errMsg } from '../../api'
import { UiTabs, UiDrawer, UiConfirm, toast } from '../../components/ui'
import { categoryLabel, formatTime } from '../../lib/labels'

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
const traceOffset = ref(0)
const traceLoading = ref(false)
const traceDetail = ref(null)

const feedbackKind = ref('objection') // 反馈区切换：objection（逐分异议）/ suggestion（意见反馈 §22.1）
const feedbackStatus = ref('pending')
const feedbacks = ref([])
const feedbackLoading = ref(false)
const suggestionStatus = ref('pending')
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

const confirmState = reactive({ show: false, kind: '', feedback: null, suggestion: null })

const prettyResult = computed(() =>
  current.value?.result ? JSON.stringify(current.value.result, null, 2) : '— 生成中 —'
)

// ---- 通用加载 ----
async function reloadAll() {
  try {
    const [oRes, hRes] = await Promise.all([
      adminPositions.positionOptions(),
      admin.eval.getHistory()
    ])
    positionOptions.value = oRes.data
    history.value = hRes.data
  } catch (e) {
    toast(errMsg(e, '加载失败'), 'error')
  }
  if (tab.value === 'trace') loadTraces()
  if (tab.value === 'feedback') {
    if (feedbackKind.value === 'suggestion') loadSuggestions()
    else loadFeedback()
  }
}

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
    const params = { limit: TRACE_LIMIT, offset: traceOffset.value }
    if (traceFilters.call_type) params.call_type = traceFilters.call_type
    if (traceFilters.ref_id.trim()) params.ref_id = traceFilters.ref_id.trim()
    if (traceFilters.success !== '') params.success = traceFilters.success === '1'
    const { data } = await admin.trace.list(params)
    traces.value = data.traces
    traceTotal.value = data.total
  } catch (e) {
    toast(errMsg(e, 'trace 加载失败'), 'error')
  } finally {
    traceLoading.value = false
  }
}

function resetTrace() {
  traceOffset.value = 0
  loadTraces()
}

function pageTrace(dir) {
  traceOffset.value = Math.max(0, traceOffset.value + dir * TRACE_LIMIT)
  loadTraces()
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
  }
}

const confirmTextMap = computed(() => ({
  review: '确认标记「' + confirmState.feedback?.std_name + '」异议为已处理？（不改分，仅留痕）',
  'bad_case': '确认标「' + confirmState.feedback?.std_name + '」异议为 bad case？（沉淀为评测素材）',
  publish: '确认为该反馈所属报告执行发布？（发布后考生可见最终报告）',
  suggestion_review: '确认标记用户「' + confirmState.suggestion?.username + '」的意见反馈为已处理？（reviewed + 处理留痕）'
}))

async function onConfirm() {
  const meta = CONFIRM_META[confirmState.kind]
  const target = confirmState.kind === 'suggestion_review' ? confirmState.suggestion : confirmState.feedback
  confirmState.show = false
  if (!meta || !target) return
  try {
    await meta.act(target)
    toast(meta.ok)
    await meta.reload()
  } catch (e) {
    toast(errMsg(e, '操作失败'), 'error')
  }
}

import { onBeforeUnmount } from 'vue'
onBeforeUnmount(stopPoll)

reloadAll()
</script>
