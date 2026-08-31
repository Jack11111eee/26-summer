<template>
  <div class="grail">
    <!-- 通栏头 -->
    <header class="grail-head">
      <div class="gh-brand">
        <div class="gh-mark">测</div>
        <span class="gh-name">胜任力测评</span>
      </div>
      <div class="gh-divider"></div>
      <div class="gh-crumb">测评端 / <b>测评进行中</b>
        <span v-if="session?.model_version" class="tag tag-grey ver-tag">模型 v{{ session.model_version }}</span>
      </div>
      <div class="gh-actions">
        <span class="gh-user">{{ auth.user?.username }}</span>
        <button class="btn btn-sm" @click="onExit">退出测评</button>
      </div>
    </header>

    <!-- 三栏体：中栏聊天 + 右栏上下文（候选人端无左导航） -->
    <div class="grail-body">
      <!-- 中栏：聊天主区 -->
      <main class="rail-center chat-center">
        <div ref="msgBox" class="messages" v-loading="loading">
          <template v-for="(m, i) in messages" :key="i">
            <!-- 候选人消息：右侧蓝气泡 -->
            <div v-if="m.role === 'user'" class="row row-user">
              <div class="bubble bubble-user">{{ m.content }}</div>
            </div>

            <!-- 助手消息：左侧灰气泡；决策理由可折叠；含表单标记则渲染表单卡 -->
            <div v-else class="row row-assistant">
              <div class="bubble-wrap">
                <div v-if="m.decision" class="decision">
                  <el-collapse>
                    <el-collapse-item name="d">
                      <template #title>
                        <span class="decision-title">测评思路（{{ actionLabel(m.decision.action) }}）</span>
                      </template>
                      <div class="decision-body">
                        {{ m.decision.reason }}
                        <span v-if="m.decision.score_live != null" class="score">
                          过程判分 {{ m.decision.score_live }} / 5
                        </span>
                      </div>
                    </el-collapse-item>
                  </el-collapse>
                </div>
                <div class="bubble bubble-assistant">
                  {{ displayContent(m) }}<span v-if="m.streaming" class="cursor">▍</span>
                </div>
                <FormCard
                  v-if="m.formId"
                  :form-id="m.formId"
                  :session-id="sessionId"
                  class="form"
                  @submitted="onFormSubmitted"
                />
              </div>
            </div>
          </template>

          <el-empty v-if="!loading && !messages.length" description="暂无对话内容" />
        </div>

        <!-- 底部输入区（会话结束或流式回复中禁用） -->
        <div class="input-bar">
          <el-input
            v-model="draft"
            type="textarea"
            :rows="2"
            :disabled="!canAnswer"
            :placeholder="canAnswer ? '请输入回答，Enter 发送（Shift+Enter 换行）' : '测评已结束或正在生成回复…'"
            @keydown.enter.exact.prevent="onSend"
          />
          <button
            class="btn btn-primary send-btn"
            :disabled="!canAnswer || !draft.trim()"
            @click="onSend"
          >
            {{ streaming ? '生成中…' : '发送' }}
          </button>
        </div>
      </main>

      <!-- 右栏：常驻上下文（进度 + 当前题） -->
      <aside class="rail-right">
        <div class="rr-card">
          <div class="rr-title">完成进度</div>
          <div class="progress-num">
            <span class="num-big">{{ session?.answered_count ?? 0 }}</span>
            <span class="num-total">/ {{ session?.total_count ?? 0 }}</span>
          </div>
          <el-progress
            :percentage="progressPct"
            :status="progressPct >= 100 ? 'success' : undefined"
            :stroke-width="8"
            :show-text="false"
            color="#448361"
          />
          <div class="progress-sub">已作答 / 总题量</div>
        </div>

        <div v-if="currentQuestion" class="rr-card">
          <div class="rr-title">当前题目</div>
          <div class="cur-q">
            <span v-if="currentQuestion.category" class="tag tag-grey">{{ categoryLabel(currentQuestion.category) }}</span>
            <span v-if="currentQuestion.difficulty" class="tag tag-amber">{{ difficultyLabel(currentQuestion.difficulty) }}</span>
          </div>
          <div class="cur-q-stem">{{ currentQuestion.stem }}</div>
        </div>

        <div class="rr-callout grey">
          <div class="rr-callout-top">
            <span class="callout-dot callout-dot-grey"></span>
            <span class="rr-callout-label">作答提示</span>
          </div>
          <div class="rr-callout-foot">结合真实经历作答，AI 会基于回答追问或推进下一题。</div>
        </div>
      </aside>
    </div>

    <!-- 通栏脚 -->
    <footer class="grail-foot">
      <span>CF · 测评端</span>
      <div class="f-right"><span>候选人</span></div>
    </footer>
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

const session = ref(null) // {session_id, status, position_id, model_version, answered_count, total_count, current_question, messages?}
const messages = ref([]) // {role, content, decision?, formId?, streaming?}
const loading = ref(false)
const streaming = ref(false)
const draft = ref('')
const msgBox = ref(null)

let abortStream = null

const currentQuestion = computed(() => session.value?.current_question || null)
const canAnswer = computed(
  () => !!currentQuestion.value && !streaming.value && session.value?.status === 'in_progress'
)
const progressPct = computed(() => {
  const total = session.value?.total_count
  if (!total) return 0
  return Math.round(((session.value?.answered_count ?? 0) / total) * 100)
})

// 从助手文本中剥离 📎[form:xxx] 标记，返回展示用纯文本
function displayContent(m) {
  return m.formId ? m.content.replace(/📎\[form:[^\]]+\]/g, '').trim() : m.content
}
// 提取消息中的表单 id（若有）
function extractFormId(text) {
  const hit = text.match(/📎\[form:([^\]]+)\]/)
  return hit ? hit[1] : null
}

async function load() {
  loading.value = true
  try {
    const { data } = await assessment.getSession(sessionId)
    session.value = data
    // 历史消息回放（后端返回 messages[] 时）
    for (const m of data.messages || []) {
      pushMessage(m.role, m.content, { decision: m.decision })
    }
    // 当前题作为最新一条助手消息（无历史时）
    if (data.current_question && !(data.messages || []).length) {
      pushMessage('assistant', data.current_question.stem || '')
    }
    if (data.status === 'completed') {
      router.replace(`/assessment/report/${sessionId}`)
    }
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '会话加载失败')
  } finally {
    loading.value = false
  }
}

// 作答后轮询刷新会话状态（answered_count/total_count/current_question 以后端为准，
// 避免 followup 不推进题数时前端误增计数）。
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
  if (!text || !canAnswer.value) return
  const questionId = currentQuestion.value?.question_id
  if (!questionId) {
    ElMessage.warning('当前没有可回答的题目')
    return
  }

  pushMessage('user', text)
  draft.value = ''
  streaming.value = true

  // 先占一条流式中的助手气泡
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

      if (d.action === 'finish' || assistantMsg.decision?.action === 'finish') {
        session.value.status = 'completed'
        router.push(`/assessment/report/${sessionId}`)
      } else {
        // 拉取权威会话状态：answered_count（followup 不计数）与下一题
        refreshSession()
      }
      scrollToBottom()
    },
    onError(err) {
      assistantMsg.streaming = false
      streaming.value = false
      if (!assistantMsg.content) {
        // 流失败且无任何内容时移除空气泡
        messages.value = messages.value.filter((m) => m !== assistantMsg)
      }
      ElMessage.error(err.message || '回复生成失败')
    }
  })
}

function onFormSubmitted() {
  // 表单提交成功后由后端下一轮驱动提问；此处仅提示，不重复落消息
}

async function onExit() {
  try {
    await ElMessageBox.confirm('退出后可在「我的测评」中继续，确定离开当前测评吗？', '退出测评', {
      confirmButtonText: '离开',
      cancelButtonText: '继续作答',
      type: 'warning'
    })
  } catch {
    return // 取消
  }
  router.push('/assessment/positions')
}

function actionLabel(a) {
  return { followup: '追问', next: '下一题', finish: '结束' }[a] || a
}
function difficultyLabel(d) {
  return { easy: '简单', medium: '中等', hard: '困难' }[d] || d
}
function categoryLabel(c) {
  return { hard_skill: '硬技能', soft_skill: '软技能', experience: '经验', qualification: '门槛' }[c] || c
}

onMounted(load)
onBeforeUnmount(() => abortStream?.())
</script>

<style scoped>
.gh-user {
  font-size: 13px;
  color: var(--ink-2);
  align-self: center;
}
.ver-tag {
  margin-left: 8px;
}
/* 中栏聊天区：消息流 + 输入条纵向铺满 */
.chat-center {
  display: flex;
  flex-direction: column;
  padding: 16px 18px 18px;
}
.messages {
  flex: 1;
  overflow-y: auto;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 16px;
}
.row {
  display: flex;
  margin-bottom: 14px;
}
.row-user {
  justify-content: flex-end;
}
.row-assistant {
  justify-content: flex-start;
}
.bubble-wrap {
  max-width: 78%;
}
.bubble {
  padding: 10px 14px;
  border-radius: 8px;
  line-height: 1.6;
  font-size: 14px;
  white-space: pre-wrap;
  word-break: break-word;
}
/* 用户：右对齐蓝（Notion 蓝） */
.bubble-user {
  background: var(--blue-bg);
  color: var(--blue);
  border-bottom-right-radius: 3px;
}
/* AI：左对齐灰 */
.bubble-assistant {
  background: var(--grey-bg);
  color: var(--ink-1);
  border-bottom-left-radius: 3px;
}
.cursor {
  display: inline-block;
  margin-left: 2px;
  animation: blink 1s step-start infinite;
}
@keyframes blink {
  50% {
    opacity: 0;
  }
}
/* 决策理由（可折叠） */
.decision {
  margin-bottom: 6px;
}
.decision :deep(.el-collapse) {
  border: none;
  --el-collapse-header-height: auto;
}
.decision :deep(.el-collapse-item__header) {
  background: transparent;
  border: none;
  height: auto;
  padding: 2px 0;
  font-size: 12px;
  color: var(--ink-3);
}
.decision :deep(.el-collapse-item__wrap) {
  border: none;
  background: transparent;
}
.decision-title {
  font-size: 12px;
  color: var(--ink-3);
}
.decision-body {
  font-size: 12px;
  color: var(--ink-2);
  background: var(--panel-2);
  border-radius: 8px;
  padding: 8px 10px;
}
.score {
  margin-left: 8px;
  color: var(--ink-3);
}
.form {
  margin-top: 8px;
}
/* 输入区 */
.input-bar {
  display: flex;
  gap: 10px;
  align-items: flex-end;
  margin-top: 12px;
}
.input-bar :deep(.el-textarea) {
  flex: 1;
}
.send-btn {
  height: 34px;
  padding: 0 18px;
  flex-shrink: 0;
}
/* 右栏进度 */
.progress-num {
  margin: 4px 0 8px;
}
.num-big {
  font-size: 24px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--ink-1);
}
.num-total {
  font-size: 13px;
  color: var(--ink-3);
}
.progress-sub {
  font-size: 11px;
  color: var(--ink-3);
  margin-top: 6px;
}
.cur-q {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.cur-q-stem {
  margin-top: 8px;
  font-size: 12px;
  color: var(--ink-2);
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
