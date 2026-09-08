<template>
  <div class="app">
    <!-- 退出确认 -->
    <UiConfirm
      v-if="exitConfirm"
      title="退出测评"
      message="退出后本场测评不会作废，回来后可从中断处继续。确认退出？"
      confirm-text="退出"
      @close="exitConfirm = false"
      @confirm="confirmExit"
    />

    <div class="main">
      <header class="topbar">
        <div class="tb-title">
          胜任力测评
          <span v-if="session?.position_name" class="tb-badge">{{ session.position_name }}</span>
          <span v-if="session?.model_version" class="tb-badge">模型 v{{ session.model_version }}</span>
        </div>
        <div class="tb-actions">
          <span>{{ auth.user?.username }}</span>
          <button
            class="btn-ghost"
            type="button"
            :disabled="!canPause"
            title="暂停后计时停止，可随时回来继续"
            @click="onPause"
          >暂停</button>
          <button class="btn-ghost btn-theme" type="button" @click="toggleTheme">{{ isDark ? '日间' : '夜间' }}</button>
          <button class="btn-ghost" type="button" @click="onExit">退出</button>
        </div>
      </header>

      <main ref="msgBox" class="thread" aria-label="测评对话">
        <div class="thread-inner">
          <div class="open-head serif">
            <div class="kicker">ASSESSMENT · {{ session?.position_name || '' }} · 共 {{ session?.total_count ?? '—' }} 题</div>
            <h1>请结合你的真实经历作答</h1>
            <p>约 40 分钟。题目没有标准答案；我会根据你的回答追问，或推进下一题。回答发送后即保存，中途退出后可回来继续。</p>
          </div>

          <hr class="divider" />

          <!-- 消息流（刷新恢复 + live 追加共用同一渲染） -->
          <template v-for="(m, i) in messages" :key="i">
            <div v-if="m.role === 'user'" class="msg me">
              <div class="who">{{ auth.user?.username || '你的回答' }} · {{ m.time || '' }}</div>
              <div class="bubble" :class="{ draft: m.pending }">{{ m.content }}</div>
            </div>

            <div v-else class="msg ai">
              <div class="avatar ai">测</div>
              <div class="msg-body">
                <!-- 测评思路折叠（去分数；仅 AI 追问类回复有 reason 时展示） -->
                <details v-if="m.reason" class="think">
                  <summary><span class="caret">▶</span> 测评思路 · 为什么追问</summary>
                  <div class="body">{{ m.reason }}</div>
                </details>
                <div class="msg-meta">
                  <b>{{ m.label || '访谈' }}</b>
                  <template v-if="m.chips">
                    <span v-if="m.chips.category" class="chip">{{ m.chips.category }}</span>
                    <span v-if="m.chips.qtype" class="chip">{{ m.chips.qtype }}</span>
                    <span v-if="m.chips.difficulty" class="chip amber">{{ m.chips.difficulty }}</span>
                  </template>
                </div>
                <p class="stem serif">
                  {{ m.content }}<span v-if="m.streaming" class="cursor">▍</span>
                </p>
                <FormCard
                  v-if="m.formId"
                  :form-id="m.formId"
                  :session-id="sessionId"
                  :initial-schema="m.formSchema || openForm"
                  class="thread-form"
                  @submitted="onFormSubmitted"
                />
              </div>
            </div>
          </template>

          <div class="statusline" aria-live="polite">
            <span class="dot"></span><span class="status-text">{{ statusText }}</span>
          </div>
        </div>
      </main>

      <!-- 入场确认（PENDING_START）：计时起点在现场确认 -->
      <div v-if="pendingStart" class="composer-wrap">
        <div class="gate-card">
          <div class="title serif">准备就绪</div>
          <p>本场测评共 40 分钟，从你点击「开始测评」起算。开始后请结合真实经历依次作答；中途可暂停、退出后可回来继续。</p>
          <button class="btn-accent" style="width: auto; padding: 10px 34px" :disabled="starting" @click="onStart">
            {{ starting ? '正在开始…' : '开始测评' }}
          </button>
        </div>
      </div>

      <!-- 暂停确认卡（PAUSED） -->
      <div v-else-if="paused" class="composer-wrap">
        <div class="gate-card">
          <div class="title serif">测评已暂停</div>
          <p>计时已停止。你可以休息片刻，回来后点击「继续测评」从中断处接着作答。</p>
          <button class="btn-accent" style="width: auto; padding: 10px 34px" :disabled="resuming" @click="onResume">
            {{ resuming ? '正在继续…' : '继续测评' }}
          </button>
        </div>
      </div>

      <!-- 输入区 -->
      <div v-else class="composer-wrap">
        <form class="composer" novalidate @submit.prevent="onSend">
          <textarea
            ref="taEl"
            v-model="draft"
            class="ta"
            rows="1"
            :disabled="!canAnswer"
            :placeholder="composerPlaceholder"
            aria-label="回答输入框"
            @input="fitTextarea"
            @compositionstart="composing = true"
            @compositionend="composing = false"
            @keydown.enter.exact.prevent="onEnter"
          ></textarea>
          <div class="composer-foot">
            <span class="hint"><b>Enter</b> 发送 · <b>Shift+Enter</b> 换行</span>
            <button class="send" type="submit" :disabled="!canAnswer || !draft.trim()">
              {{ streaming ? '生成中…' : '发送作答' }}
            </button>
          </div>
        </form>
        <p class="composer-note">回答发送后保存 · 本场测评约 40 分钟 · 中途可暂停</p>
      </div>
    </div>

    <aside class="rail" aria-label="本场访谈进度">
      <div class="rail-title">本场访谈</div>
      <div class="rail-num"><span class="big">{{ pad2(session?.answered_count ?? 0) }}</span><span class="total"> / {{ pad2(session?.total_count ?? '—') }} 题</span></div>
      <div class="rail-bar" aria-hidden="true"><i :style="{ width: `${progressPct}%` }"></i></div>

      <div
        v-for="(t, i) in toc"
        :key="i"
        class="toc-item"
        :class="{ done: t.state === 'done', current: t.state === 'current' }"
      >
        <span class="no">{{ pad2(i + 1) }}</span>
        <span>{{ t.label }}</span>
      </div>

      <div class="rail-tip">没有标准答案。请尽量讲述真实情境、你的行动和结果。</div>
    </aside>
  </div>
</template>

<script setup>
// 测评对话页：candidate.html 定稿逐结构移植（开场/题面衬线/纸灰气泡/折叠思路/
// 三态状态行/右栏 TOC/胶囊 composer/Enter+IME 门），叠加真实数据流：
// GET session 恢复 + SSE 流式作答 + 暂停继续 + 表单分支 + 入场确认门。
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { assessment, errMsg } from '../../api'
import { toast, UiConfirm } from '../../components/ui'
import FormCard from '../../components/FormCard.vue'
import { useAuthStore } from '../../stores/auth'
import { useTheme } from '../../lib/theme'
import { categoryLabel } from '../../lib/labels'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const { theme, toggle: toggleTheme } = useTheme()
const isDark = computed(() => theme.value === 'dark')

const sessionId = route.params.session_id

const session = ref(null)
const messages = ref([])
const loading = ref(false)
const streaming = ref(false)
const draft = ref('')
const starting = ref(false)
const resuming = ref(false)
const pausing = ref(false)
const statusText = ref('正在加载测评内容')
const openForm = ref(null)
const exitConfirm = ref(false)

const msgBox = ref(null)
const taEl = ref(null)
let composing = false
let abortStream = null

// ---- 派生态 ----
const currentQuestion = computed(() => session.value?.current_question || null)
const canAnswer = computed(
  () => !!currentQuestion.value && !streaming.value && session.value?.status === 'in_progress' && session.value?.phase === 'ACTIVE'
)
const pendingStart = computed(
  () => session.value?.status === 'in_progress' && session.value?.phase === 'PENDING_START'
)
const paused = computed(
  () => session.value?.status === 'in_progress' && session.value?.phase === 'PAUSED'
)
// 暂停可用：进行中 + ACTIVE + 不在流式回复中（流中暂停会打断 SSE 消费合同）
const canPause = computed(
  () => session.value?.status === 'in_progress' && session.value?.phase === 'ACTIVE' && !streaming.value && !pausing.value
)
const progressPct = computed(() => {
  const total = session.value?.total_count
  if (!total) return 0
  return Math.min(100, ((session.value?.answered_count ?? 0) / total) * 100)
})
const composerPlaceholder = computed(() =>
  canAnswer.value ? '在此写下你的回答……' : '正在准备下一问…'
)

// ---- TOC 右栏：done/current/upcoming + 折叠省略 ----
const toc = computed(() => {
  const answered = session.value?.answered_count ?? 0
  const total = session.value?.total_count ?? 0
  const stem = currentQuestion.value?.stem || ''
  const out = []
  for (let i = 0; i < Math.min(total, answered + 1); i++) {
    if (i < answered - 1) {
      out.push({ state: 'done', label: '已完成作答' })
    } else if (i === answered - 1) {
      out.push({ state: 'done', label: '已完成作答' })
    } else if (i === answered) {
      out.push({ state: 'current', label: stem ? briefStem(stem) : '当前题目' })
    }
  }
  if (total > answered + 1) {
    out.push({ state: 'more', label: `还有 ${total - answered - 1} 题` })
  }
  return out.slice(0, 12)
})

function briefStem(s) {
  const t = s.trim().replace(/\s+/g, ' ')
  return t.length > 18 ? `${t.slice(0, 18)}…` : t
}

function pad2(n) {
  return n == null ? '—' : String(n).padStart(2, '0')
}

// ---- 消息构建 ----
const QTYPE_LABELS = { subjective: '主观题', objective: '客观题', behavioral: '行为题' }

function pushMessage(msg) {
  messages.value.push(msg)
  scrollToBottom()
  return msg
}

async function scrollToBottom() {
  await nextTick()
  if (msgBox.value) msgBox.value.scrollTop = msgBox.value.scrollHeight
}

function hmNow() {
  const d = new Date()
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function extractFormId(text) {
  const hit = text.match(/📎\[form:([^\]]+)\]/)
  return hit ? hit[1] : null
}

function displayContent(m) {
  return m.formId ? m.content.replace(/📎\[form:[^\]]+\]/g, '').trim() : m.content
}

// ---- 加载与恢复 ----
async function load() {
  loading.value = true
  statusText.value = '正在加载测评内容'
  try {
    const { data } = await assessment.getSession(sessionId)
    applySession(data)

    if (data.status === 'completed') {
      router.replace(`/assessment/report/${sessionId}`)
      return
    }

    // 恢复 open_form（filled 后端只回白名单 schema）
    openForm.value = data.open_form || null

    // 时间线重建：messages（role/content/created_at 三键契约）+ 当前题
    messages.value = []
    let qSeen = 0
    for (const m of data.messages || []) {
      if (m.role === 'assistant') {
        const formId = extractFormId(m.content)
        qSeen += 1
        pushMessage({
          role: 'assistant',
          content: displayContent({ content: m.content, formId }),
          formId,
          formSchema: formId === extractFormId(m.content) && formId ? openForm.value : null,
          label: `第${cnNum(qSeen)}问`,
          reason: null,
          time: m.created_at
        })
      } else {
        pushMessage({ role: 'user', content: m.content, time: hmTimeOf(m.created_at) })
      }
    }
    if (data.current_question && !(data.messages || []).length) {
      pushMessage({ role: 'assistant', content: data.current_question.stem, label: '第一问', chips: chipsOf(data.current_question) })
    } else if (data.current_question) {
      // 最新一问若已在 messages 中则不重复渲染
    }

    statusText.value = statusFor()
  } catch (e) {
    statusText.value = '测评内容加载失败，请刷新重试'
    toast(errMsg(e, '会话加载失败'), 'error')
  } finally {
    loading.value = false
  }
}

function hmTimeOf(v) {
  if (!v) return ''
  const d = new Date(v)
  if (Number.isNaN(d.getTime())) return ''
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function cnNum(n) {
  const s = '一二三四五六七八九十'
  return n <= 10 ? s[n - 1] : String(n)
}

function chipsOf(q) {
  if (!q) return null
  const out = {}
  if (q.category) out.category = categoryLabel(q.category)
  if (q.qtype && QTYPE_LABELS[q.qtype]) out.qtype = QTYPE_LABELS[q.qtype]
  if (q.difficulty) out.difficulty = `难度 ${q.difficulty}`
  return Object.keys(out).length ? out : null
}

function applySession(data) {
  session.value = data
}

function statusFor() {
  if (pendingStart.value) return '等待入场确认 · 点击「开始测评」起算 40 分钟'
  if (paused.value) return '测评已暂停 · 计时已停止'
  if (streaming.value) return '回答已保存 · 正在理解你的回答'
  if (canAnswer.value) return '可以继续了 · 等待你的回答'
  if (session.value?.status === 'completed') return '本场测评已完成'
  return '正在准备下一问'
}

async function refreshSession() {
  try {
    const { data } = await assessment.getSession(sessionId)
    // 若新题已派发且未在消息流中，补渲染（SSE done 后 refresh 场景）
    const stem = data.current_question?.stem
    const lastAi = [...messages.value].reverse().find((m) => m.role === 'assistant')
    if (stem && data.status === 'in_progress' && !paused.value && !pendingStart.value) {
      if (!lastAi || lastAi.content !== stem) {
        pushMessage({
          role: 'assistant',
          content: stem,
          label: `第${cnNum((data.answered_count ?? 0) + 1)}问`,
          chips: chipsOf(data.current_question),
          reason: null
        })
      }
    }
    applySession(data)
    statusText.value = statusFor()
  } catch { /* 刷新失败不阻断对话，下轮仍会再试 */ }
}

// ---- 入场确认 ----
async function onStart() {
  if (starting.value) return
  starting.value = true
  try {
    try {
      await assessment.startSession(sessionId)
    } catch (e) {
      const code = e?.response?.data?.detail?.error_code
      if (e?.response?.status === 409 && code === 'SESSION_ALREADY_ACTIVE') {
        /* 幂等：已被 start 过（双击/重复进入），直接进入 */
      } else {
        throw e
      }
    }
    statusText.value = '已开始 · 正在派发第一题'
    const { data } = await assessment.getSession(sessionId)
    applySession(data)
    if (data.current_question) {
      pushMessage({
        role: 'assistant',
        content: data.current_question.stem,
        label: '第一问',
        chips: chipsOf(data.current_question)
      })
    }
    statusText.value = statusFor()
  } catch (e) {
    if (e?.response?.status === 409 && e?.response?.data?.detail?.error_code === 'SESSION_NOT_IN_PROGRESS') {
      toast('会话已结束，正在前往报告')
      router.replace(`/assessment/report/${sessionId}`)
      return
    }
    statusText.value = '开始失败，请重试'
    toast(errMsg(e, '开始测评失败'), 'error')
  } finally {
    starting.value = false
  }
}

// ---- 暂停 / 继续（web-next 首次接线 03-05 端点）----
async function onPause() {
  if (!canPause.value) return
  pausing.value = true
  try {
    await assessment.pauseSession(sessionId)
    toast('已暂停 · 计时停止')
    await refreshSessionAfterPause()
  } catch (e) {
    const code = e?.response?.data?.detail?.error_code
    if (code === 'SESSION_ALREADY_PAUSED') {
      await refreshSessionAfterPause() // 幂等：直接进入暂停态
    } else {
      toast(errMsg(e, '暂停失败'), 'error')
    }
  } finally {
    pausing.value = false
  }
}

async function refreshSessionAfterPause() {
  try {
    const { data } = await assessment.getSession(sessionId)
    applySession(data)
    statusText.value = statusFor()
  } catch { /* ignore */ }
}

async function onResume() {
  if (resuming.value) return
  resuming.value = true
  try {
    try {
      await assessment.resumeSession(sessionId)
    } catch (e) {
      const code = e?.response?.data?.detail?.error_code
      if (e?.response?.status === 409 && code === 'SESSION_NOT_PAUSED') {
        /* 幂等兜底：无 open paused 区间（极端时序），照常刷新 */
      } else {
        throw e
      }
    }
    await refreshSession()
    statusText.value = statusFor()
  } catch (e) {
    toast(errMsg(e, '继续失败，请重试'), 'error')
  } finally {
    resuming.value = false
  }
}

// ---- 发送与 SSE ----
function fitTextarea() {
  const el = taEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 200)}px`
}

function onEnter() {
  if (!composing) onSend()
}

function onSend() {
  const text = draft.value.trim()
  if (!text || !canAnswer.value || composing) return
  const questionId = currentQuestion.value?.question_id
  if (!questionId) {
    toast('当前没有可回答的题目', 'warn')
    return
  }

  pushMessage({ role: 'user', content: text, time: hmNow(), pending: true })
  draft.value = ''
  fitTextarea()
  streaming.value = true
  statusText.value = '回答已保存 · AI 正在理解你的回答'

  const aiMsg = pushMessage({ role: 'assistant', content: '', streaming: true, label: '回应' })
  abortStream = assessment.submitAnswer(sessionId, questionId, text, {
    onDecision(d) {
      aiMsg.reason = d?.reason || null
    },
    onReply(chunk) {
      aiMsg.content += chunk
      scrollToBottom()
    },
    onDone(d) {
      aiMsg.streaming = false
      aiMsg.formId = extractFormId(aiMsg.content)
      if (aiMsg.formId) {
        aiMsg.content = aiMsg.content.replace(/📎\[form:[^\]]+\]/g, '').trim()
        aiMsg.formSchema = openForm.value
      }
      // 用户消息解除 pending（落库已确认）
      const u = [...messages.value].reverse().find((m) => m.role === 'user' && m.pending)
      if (u) u.pending = false
      streaming.value = false
      statusText.value = 'AI 正在准备下一问'

      if (d.action === 'finish') {
        session.value.status = 'completed'
        toast('本场测评完成，正在生成报告')
        router.push(`/assessment/report/${sessionId}`)
      } else if (d.action === 'form') {
        statusText.value = '请先填写资格核验表单'
        refreshSession().then(() => {
          if (openForm.value) statusText.value = '请先填写资格核验表单'
        })
      } else {
        refreshSession()
      }
    },
    onError(err) {
      aiMsg.streaming = false
      streaming.value = false
      statusText.value = '发送失败，请重试'
      toast(err?.message || '作答提交失败', 'error')
      // 失败回退草稿，避免重打全文
      draft.value = text
      fitTextarea()
    }
  })
}

// ---- 表单（gate 分支）----
function onFormSubmitted() {
  statusText.value = '表单已提交 · 继续作答'
  refreshSession()
}

// ---- 退出 ----
function onExit() {
  exitConfirm.value = true
}
async function confirmExit() {
  exitConfirm.value = false
  router.push('/assessment/positions')
}

onMounted(async () => {
  await load()
  await nextTick()
  fitTextarea()
})

onBeforeUnmount(() => {
  if (abortStream) abortStream()
})
</script>
