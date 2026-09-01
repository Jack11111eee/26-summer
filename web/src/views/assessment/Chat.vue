<template>
  <div class="chat-hybrid">
    <header class="chat-hybrid__topbar">
      <div class="chat-hybrid__title-group">
        <div class="chat-hybrid__mark">测</div>
        <div>
          <div class="chat-hybrid__title">胜任力测评</div>
          <div class="chat-hybrid__subtitle">
            <span v-if="session?.position_name">{{ session.position_name }}</span>
            <span v-if="session?.model_version"> · 模型 v{{ session.model_version }}</span>
          </div>
        </div>
      </div>
      <div class="chat-hybrid__actions">
        <span class="chat-hybrid__user">{{ auth.user?.username }}</span>
        <button class="chat-hybrid__button" type="button" @click="toggleTheme">
          {{ isDark ? '日间' : '夜间' }}
        </button>
        <button class="chat-hybrid__button" type="button" @click="onExit">退出</button>
      </div>
    </header>

    <div class="chat-hybrid__body">
      <main ref="msgBox" class="chat-hybrid__thread" aria-label="测评对话">
        <div class="chat-hybrid__thread-inner" v-loading="loading">
          <section class="chat-hybrid__opening">
            <div class="chat-hybrid__kicker">ASSESSMENT · 本场访谈</div>
            <h1>请结合你的真实经历作答</h1>
            <p>
              题目没有标准答案，请尽量讲述真实情境、你的行动和结果；我会根据你的回答追问或推进下一题。
              回答发送后即保存。
            </p>
          </section>

          <hr class="chat-hybrid__divider">

          <template v-for="(m, i) in messages" :key="i">
            <div v-if="m.role === 'user'" class="chat-hybrid__message chat-hybrid__message--user">
              <div class="chat-hybrid__message-meta">
                <b>{{ auth.user?.username || '你的回答' }}</b>
                <span v-if="messageTime(m)">· {{ messageTime(m) }}</span>
              </div>
              <div class="chat-hybrid__user-bubble">{{ m.content }}</div>
            </div>

            <div v-else class="chat-hybrid__message chat-hybrid__message--assistant">
              <div class="chat-hybrid__avatar">测</div>
              <div class="chat-hybrid__message-body">
                <div class="chat-hybrid__message-meta"><b>{{ i === 0 ? '访谈' : '当前问题' }}</b></div>
                <p class="chat-hybrid__stem">{{ displayContent(m) }}<span v-if="m.streaming" class="chat-hybrid__cursor">▍</span></p>
                <FormCard
                  v-if="m.formId"
                  :form-id="m.formId"
                  :session-id="sessionId"
                  class="chat-hybrid__form"
                  @submitted="onFormSubmitted"
                />
              </div>
            </div>
          </template>

          <el-empty v-if="!loading && !messages.length" description="暂无对话内容" />

          <div class="chat-hybrid__status" aria-live="polite">
            <span class="chat-hybrid__status-dot"></span>
            <span>{{ statusText }}</span>
          </div>
        </div>
      </main>

      <aside class="chat-hybrid__rail" aria-label="本场访谈进度">
        <div class="chat-hybrid__rail-title">本场访谈</div>
        <div class="chat-hybrid__rail-count">
          <strong>{{ session?.answered_count ?? 0 }}</strong>
          <span v-if="session?.total_count != null"> / {{ session.total_count }} 题</span>
        </div>
        <div class="chat-hybrid__rail-bar" aria-hidden="true">
          <i :style="{ width: `${progressPct}%` }"></i>
        </div>

        <section v-if="currentQuestion" class="chat-hybrid__rail-card">
          <div class="chat-hybrid__rail-label">当前题目</div>
          <p>{{ currentQuestion.stem }}</p>
        </section>

        <section class="chat-hybrid__rail-tip">
          <div class="chat-hybrid__rail-label">作答提示</div>
          <p>没有标准答案。请尽量展开真实情境、你的行动和结果。</p>
        </section>
      </aside>
    </div>

    <div class="chat-hybrid__composer-wrap">
      <form class="chat-hybrid__composer" novalidate @submit.prevent="onSend">
        <textarea
          ref="textarea"
          v-model="draft"
          rows="1"
          :disabled="!canAnswer"
          :placeholder="canAnswer ? '在此写下你的回答……' : '测评已结束或正在生成回复…'"
          aria-label="回答输入框"
          @input="fitTextarea"
          @compositionstart="composing = true"
          @compositionend="composing = false"
          @keydown.enter.exact.prevent="handleEnter"
        ></textarea>
        <div class="chat-hybrid__composer-foot">
          <span class="chat-hybrid__hint"><b>Enter</b> 发送 · <b>Shift+Enter</b> 换行</span>
          <button class="chat-hybrid__send" type="submit" :disabled="!canAnswer || !draft.trim()">
            {{ streaming ? '生成中…' : '发送作答' }}
          </button>
        </div>
      </form>
      <p class="chat-hybrid__note">回答发送后保存 · 请按自己的节奏作答</p>
    </div>
  </div>
</template>

<script setup>
import FormCard from '../../components/FormCard.vue'
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { assessment } from '../../api'
import { useAuthStore } from '../../stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const sessionId = route.params.session_id

const session = ref(null)
const messages = ref([])
const loading = ref(false)
const streaming = ref(false)
const draft = ref('')
const msgBox = ref(null)
const textarea = ref(null)
const statusText = ref('正在加载测评内容')
const isDark = ref(false)
const composing = ref(false)

let abortStream = null

const currentQuestion = computed(() => session.value?.current_question || null)
const canAnswer = computed(
  () => !!currentQuestion.value && !streaming.value && session.value?.status === 'in_progress'
)
const progressPct = computed(() => {
  const total = session.value?.total_count
  if (!total) return 0
  return Math.min(100, Math.round(((session.value?.answered_count ?? 0) / total) * 100))
})

function displayContent(m) {
  return m.formId ? m.content.replace(/📎\[form:[^\]]+\]/g, '').trim() : m.content
}

function extractFormId(text) {
  const hit = text.match(/📎\[form:([^\]]+)\]/)
  return hit ? hit[1] : null
}

function messageTime(m) {
  const value = m.created_at || m.timestamp || m.sent_at
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

async function load() {
  loading.value = true
  statusText.value = '正在加载测评内容'
  try {
    const { data } = await assessment.getSession(sessionId)
    session.value = data
    for (const m of data.messages || []) {
      pushMessage(m.role, m.content, { decision: m.decision, created_at: m.created_at })
    }
    if (data.current_question && !(data.messages || []).length) {
      pushMessage('assistant', data.current_question.stem || '')
    }
    if (data.status === 'completed') {
      router.replace(`/assessment/report/${sessionId}`)
      return
    }
    statusText.value = canAnswer.value ? '可以继续了 · 等待你的回答' : '正在准备下一问'
  } catch (e) {
    statusText.value = '测评内容加载失败，请重试'
    ElMessage.error(e.response?.data?.detail || '会话加载失败')
  } finally {
    loading.value = false
  }
}

async function refreshSession() {
  try {
    const { data } = await assessment.getSession(sessionId)
    session.value = { ...session.value, ...data }
  } catch {
    /* 刷新失败不阻断对话，下轮仍会再试 */
  }
}

function pushMessage(role, content, extra = {}) {
  messages.value.push({ role, content, ...extra })
  scrollToBottom()
  return messages.value[messages.value.length - 1]
}

async function scrollToBottom() {
  await nextTick()
  if (msgBox.value) msgBox.value.scrollTop = msgBox.value.scrollHeight
}

function onSend() {
  const text = draft.value.trim()
  if (!text || !canAnswer.value || composing.value) return
  const questionId = currentQuestion.value?.question_id
  if (!questionId) {
    ElMessage.warning('当前没有可回答的题目')
    return
  }

  pushMessage('user', text)
  draft.value = ''
  fitTextarea()
  streaming.value = true
  statusText.value = '回答已保存 · 正在理解你的回答'

  const assistantMsg = pushMessage('assistant', '', { streaming: true })
  abortStream = assessment.submitAnswer(sessionId, questionId, text, {
    onDecision(d) {
      assistantMsg.decision = d
    },
    onReply(chunk) {
      assistantMsg.content += chunk
      scrollToBottom()
    },
    onDone(d) {
      assistantMsg.streaming = false
      assistantMsg.formId = extractFormId(assistantMsg.content)
      streaming.value = false
      statusText.value = '正在准备下一问'

      if (d.action === 'finish' || assistantMsg.decision?.action === 'finish') {
        session.value.status = 'completed'
        router.push(`/assessment/report/${sessionId}`)
      } else {
        refreshSession().then(() => {
          statusText.value = canAnswer.value ? '可以继续了 · 等待你的回答' : '正在准备下一问'
        })
      }
      scrollToBottom()
    },
    onError(err) {
      assistantMsg.streaming = false
      streaming.value = false
      if (!assistantMsg.content) {
        messages.value = messages.value.filter((m) => m !== assistantMsg)
      }
      statusText.value = '回复生成失败，请重试'
      ElMessage.error(err.message || '回复生成失败')
    }
  })
}

function fitTextarea() {
  if (!textarea.value) return
  textarea.value.style.height = 'auto'
  textarea.value.style.height = `${Math.min(textarea.value.scrollHeight, 200)}px`
}

function handleEnter(event) {
  if (!event.isComposing && !composing.value) onSend()
}

function toggleTheme() {
  isDark.value = !isDark.value
  document.documentElement.dataset.theme = isDark.value ? 'dark' : 'light'
  try {
    localStorage.setItem('assessment-chat-theme', isDark.value ? 'dark' : 'light')
  } catch {
    /* 无法持久化时仅保持本次页面状态 */
  }
}

function initTheme() {
  let theme = ''
  try {
    theme = new URLSearchParams(location.search).get('theme') || localStorage.getItem('assessment-chat-theme') || ''
  } catch {
    /* 使用系统偏好 */
  }
  isDark.value = theme === 'dark' || (theme !== 'light' && window.matchMedia('(prefers-color-scheme: dark)').matches)
  document.documentElement.dataset.theme = isDark.value ? 'dark' : 'light'
}

function onFormSubmitted() {
  statusText.value = '回答已保存 · 正在准备下一问'
}

async function onExit() {
  try {
    await ElMessageBox.confirm('退出后可继续当前测评，确定离开吗？', '退出测评', {
      confirmButtonText: '离开',
      cancelButtonText: '继续作答',
      type: 'warning'
    })
  } catch {
    return
  }
  router.push('/assessment/positions')
}

onMounted(() => {
  initTheme()
  load()
})
onBeforeUnmount(() => {
  abortStream?.()
})
</script>

<style scoped>
.chat-hybrid {
  --chat-bg: #faf9f5;
  --chat-rail: #f3f1ea;
  --chat-paper: #fff;
  --chat-user: #e9e6dc;
  --chat-ink-1: #262624;
  --chat-ink-2: #555552;
  --chat-ink-3: #807e78;
  --chat-line: #e2dfd4;
  --chat-accent: #b4552d;
  --chat-accent-soft: rgba(180, 85, 45, .1);
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
  background: var(--chat-bg);
  color: var(--chat-ink-1);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  font-size: 15px;
  line-height: 1.75;
  -webkit-font-smoothing: antialiased;
}

:global(html[data-theme="dark"]) .chat-hybrid {
  --chat-bg: #26241f;
  --chat-rail: #201e19;
  --chat-paper: #2e2c26;
  --chat-user: #3a382f;
  --chat-ink-1: #eeece4;
  --chat-ink-2: #c2bfb4;
  --chat-ink-3: #8d8b82;
  --chat-line: #413e35;
  --chat-accent: #d98e5f;
  --chat-accent-soft: rgba(217, 142, 95, .14);
}

.chat-hybrid *,
.chat-hybrid *::before,
.chat-hybrid *::after { box-sizing: border-box; }

.chat-hybrid__topbar {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 24px;
  border-bottom: 1px solid var(--chat-line);
  background: var(--chat-paper);
}

.chat-hybrid__title-group,
.chat-hybrid__actions { display: flex; align-items: center; }
.chat-hybrid__title-group { gap: 10px; }
.chat-hybrid__actions { gap: 12px; color: var(--chat-ink-2); }
.chat-hybrid__mark {
  width: 30px; height: 30px; border-radius: 7px;
  display: grid; place-items: center;
  background: var(--chat-accent); color: #fff; font-weight: 700;
}
.chat-hybrid__title { font-size: 14.5px; font-weight: 600; line-height: 1.3; }
.chat-hybrid__subtitle { min-height: 18px; color: var(--chat-ink-3); font-size: 11.5px; }
.chat-hybrid__user { font-size: 13px; }
.chat-hybrid__button {
  border: 1px solid var(--chat-line); border-radius: 8px;
  padding: 5px 12px; background: var(--chat-paper); color: var(--chat-ink-2);
  font: inherit; font-size: 12.5px; cursor: pointer;
}
.chat-hybrid__button:hover { background: var(--chat-user); }

.chat-hybrid__body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1fr) 264px; }
.chat-hybrid__thread { min-width: 0; overflow-y: auto; }
.chat-hybrid__thread-inner { max-width: 768px; min-height: 100%; margin: 0 auto; padding: 32px 24px 20px; }
.chat-hybrid__opening { margin-bottom: 24px; }
.chat-hybrid__kicker,
.chat-hybrid__rail-label {
  color: var(--chat-accent); font-size: 11.5px; font-weight: 600; letter-spacing: .14em;
}
.chat-hybrid__kicker { margin-bottom: 8px; }
.chat-hybrid__opening h1 {
  margin: 0 0 8px; font-family: Georgia, "Songti SC", "Noto Serif SC", serif;
  font-size: 26px; font-weight: 500; line-height: 1.35;
}
.chat-hybrid__opening p { max-width: 56ch; margin: 0; color: var(--chat-ink-2); font-size: 14px; }
.chat-hybrid__divider { margin: 24px 0; border: 0; border-top: 1px solid var(--chat-line); }

.chat-hybrid__message { display: flex; padding: 13px 0; }
.chat-hybrid__message--assistant { gap: 14px; }
.chat-hybrid__message--user { flex-direction: column; align-items: flex-end; }
.chat-hybrid__avatar {
  flex: none; width: 32px; height: 32px; margin-top: 2px; border-radius: 50%;
  display: grid; place-items: center; background: var(--chat-accent); color: #fff;
  font-size: 13px; font-weight: 700;
}
.chat-hybrid__message-body { min-width: 0; }
.chat-hybrid__message-meta {
  display: flex; align-items: center; gap: 8px; margin-bottom: 5px;
  color: var(--chat-ink-3); font-size: 12px;
}
.chat-hybrid__message-meta b { color: var(--chat-ink-2); font-weight: 600; }
.chat-hybrid__stem {
  margin: 0; font-family: Georgia, "Songti SC", "Noto Serif SC", serif;
  font-size: 17.5px; font-weight: 500; line-height: 1.7; white-space: pre-line; overflow-wrap: anywhere;
}
.chat-hybrid__user-bubble {
  max-width: 85%; padding: 10px 15px; border-radius: 16px 16px 5px 16px;
  background: var(--chat-user); color: var(--chat-ink-1); white-space: pre-line; overflow-wrap: anywhere;
}
.chat-hybrid__cursor { display: inline-block; margin-left: 2px; animation: chat-hybrid-blink 1s step-start infinite; }
@keyframes chat-hybrid-blink { 50% { opacity: 0; } }
.chat-hybrid__form { margin-top: 10px; }
.chat-hybrid__status {
  display: flex; align-items: center; gap: 8px; margin: 3px 0 10px 46px;
  color: var(--chat-ink-3); font-size: 12.5px;
}
.chat-hybrid__status-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--chat-accent); animation: chat-hybrid-pulse 1.6s ease-in-out infinite; }
@keyframes chat-hybrid-pulse { 0%, 100% { opacity: .3; } 50% { opacity: 1; } }

.chat-hybrid__rail {
  overflow-y: auto; padding: 20px 18px; background: var(--chat-rail); border-left: 1px solid var(--chat-line);
}
.chat-hybrid__rail-title { margin-bottom: 3px; font-size: 13px; font-weight: 700; }
.chat-hybrid__rail-count { font-variant-numeric: tabular-nums; }
.chat-hybrid__rail-count strong { font-size: 22px; }
.chat-hybrid__rail-count span { color: var(--chat-ink-3); font-size: 13px; }
.chat-hybrid__rail-bar { height: 5px; margin: 10px 0 18px; overflow: hidden; border-radius: 3px; background: var(--chat-line); }
.chat-hybrid__rail-bar i { display: block; height: 100%; border-radius: 3px; background: var(--chat-accent); transition: width .2s ease; }
.chat-hybrid__rail-card,
.chat-hybrid__rail-tip { padding: 13px 14px; border-radius: 10px; background: var(--chat-paper); }
.chat-hybrid__rail-card { border: 1px solid var(--chat-line); }
.chat-hybrid__rail-label { font-size: 11px; letter-spacing: .1em; }
.chat-hybrid__rail-card p,
.chat-hybrid__rail-tip p { margin: 7px 0 0; color: var(--chat-ink-2); font-size: 13px; line-height: 1.65; }
.chat-hybrid__rail-tip { margin-top: 12px; background: var(--chat-user); }

.chat-hybrid__composer-wrap { flex: none; padding: 8px 24px 16px; background: var(--chat-bg); }
.chat-hybrid__composer {
  max-width: 720px; margin: 0 auto; padding: 4px 8px 4px 16px;
  border: 1px solid var(--chat-line); border-radius: 20px; background: var(--chat-paper);
  box-shadow: 0 1px 5px rgba(60, 50, 30, .05);
}
.chat-hybrid__composer:focus-within { border-color: var(--chat-accent); box-shadow: 0 0 0 3px var(--chat-accent-soft); }
.chat-hybrid__composer textarea {
  display: block; width: 100%; min-height: 28px; max-height: 200px; padding: 10px 0 6px;
  resize: none; border: 0; outline: 0; background: transparent; color: var(--chat-ink-1);
  font: inherit; font-size: 15px; line-height: 1.65;
}
.chat-hybrid__composer textarea::placeholder { color: var(--chat-ink-3); }
.chat-hybrid__composer textarea:disabled { cursor: not-allowed; opacity: .6; }
.chat-hybrid__composer-foot { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.chat-hybrid__hint,
.chat-hybrid__note { color: var(--chat-ink-3); font-size: 11.5px; }
.chat-hybrid__hint b { color: var(--chat-ink-2); }
.chat-hybrid__send {
  padding: 8px 18px; border: 0; border-radius: 12px; background: var(--chat-accent); color: #fff;
  font: inherit; font-size: 13px; font-weight: 600; cursor: pointer;
}
.chat-hybrid__send:hover { opacity: .88; }
.chat-hybrid__send:disabled { cursor: not-allowed; opacity: .4; }
.chat-hybrid__note { max-width: 720px; margin: 8px auto 0; text-align: center; font-size: 11px; }
.chat-hybrid :deep(.el-empty) { padding: 36px 0; }
.chat-hybrid :deep(.el-loading-mask) { background: color-mix(in srgb, var(--chat-bg) 75%, transparent); }

:global(.chat-hybrid button:focus-visible),
:global(.chat-hybrid textarea:focus-visible) { outline: 2px solid var(--chat-accent); outline-offset: 2px; }

@media (prefers-reduced-motion: reduce) {
  .chat-hybrid__status-dot,
  .chat-hybrid__cursor { animation: none; }
}

@media (max-width: 1060px) {
  .chat-hybrid__body { grid-template-columns: 1fr; }
  .chat-hybrid__rail { display: none; }
}

@media (max-width: 600px) {
  .chat-hybrid__topbar { padding: 10px 14px; }
  .chat-hybrid__user { display: none; }
  .chat-hybrid__actions { gap: 6px; }
  .chat-hybrid__button { padding: 5px 9px; }
  .chat-hybrid__thread-inner { padding: 24px 16px 16px; }
  .chat-hybrid__composer-wrap { padding: 8px 12px 12px; }
  .chat-hybrid__hint { display: none; }
}
</style>
