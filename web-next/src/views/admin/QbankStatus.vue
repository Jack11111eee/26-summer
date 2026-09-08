<template>
  <div>
    <header class="topbar">
      <div>
        <div class="topbar-title">题库<span>状态</span></div>
        <div class="topbar-meta">QBANK TASKS · {{ total }} UNITS</div>
      </div>
      <div class="topbar-actions">
        <button class="btn" :disabled="loading" @click="load">刷新</button>
      </div>
    </header>

    <!-- 状态过滤（§9.5：全部 / 生成中 / 已落库 / 失败；归档扩展：全部 / 使用中 / 已归档） -->
    <div class="filters">
      <select v-model="statusFilter" class="select" @change="resetAndLoad">
        <option value="">全部状态</option>
        <option value="RUNNING">生成中</option>
        <option value="QUEUED">排队中</option>
        <option value="SUCCEEDED">已落库</option>
        <option value="FAILED">失败</option>
      </select>
      <select v-model="bankStatusFilter" class="select" @change="resetAndLoad">
        <option value="">全部题库</option>
        <option value="active">使用中</option>
        <option value="archived">已归档</option>
      </select>
    </div>

    <section class="block n2">
      <div class="block-head">
        <span class="block-title">题库单元</span>
        <span class="block-cnt">{{ total }} 个（岗位 × 模型版本）</span>
      </div>
      <table>
        <thead>
          <tr>
            <th style="width: 24%">position</th><th style="width: 10%">version</th><th style="width: 12%">status</th>
            <th style="width: 34%">progress / error</th><th class="num" style="width: 6%">题量</th><th style="width: 14%">created_at</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="t in items"
            :key="t.task_id"
            style="cursor: pointer"
            @click="openDetail(t)"
          >
            <td v-clip><span class="cell-main">{{ t.position_name }}</span></td>
            <td><span class="tag">v{{ t.model_version }}</span></td>
            <td>
              <span v-if="t.status === 'SUCCEEDED'" class="tag tag-solid">已落库</span>
              <span v-else-if="t.status === 'RUNNING'" class="tag warm">生成中</span>
              <span v-else-if="t.status === 'QUEUED'" class="tag warm">排队中</span>
              <span v-else class="tag tag-red">失败</span>
              <!-- 归档扩展：题库使用态标签（已归档行弱化视觉） -->
              <span v-if="t.bank_status === 'archived'" class="tag qk-archived-tag">已归档</span>
            </td>
            <td>
              <!-- 生成中 / 排队中：进度条 + done/total + 当前项（§9.5） -->
              <div v-if="t.status === 'RUNNING' || t.status === 'QUEUED'">
                <div class="qk-bar">
                  <div class="qk-bar-fill" :style="{ width: percent(t) + '%' }"></div>
                </div>
                <div class="qk-line">
                  {{ t.progress?.done ?? 0 }}/{{ t.progress?.total ?? 0 }} 档
                  <template v-if="t.progress?.current_item"> · {{ t.progress.current_item }}</template>
                </div>
              </div>
              <!-- 失败：error 摘要单行截断 -->
              <div v-else-if="t.status === 'FAILED'" class="qk-err" v-clip>
                {{ t.error_msg || '未知错误' }}
              </div>
              <div v-else class="cell-sub">—</div>
            </td>
            <td class="num">
              {{ t.question_count ?? 0 }}
              <!-- 归档扩展：archived_count 并列展示（仅归档行或有归档计数时显示，避免噪音） -->
              <span v-if="t.bank_status === 'archived' || t.archived_count > 0"
                    class="qk-archived-cnt">（归档 {{ t.archived_count }}）</span>
            </td>
            <td>{{ formatTime(t.created_at) }}</td>
          </tr>
          <tr v-if="!items.length && !loading"><td colspan="6" class="empty-row">暂无题库任务（模型确认后自动生成）</td></tr>
        </tbody>
      </table>
      <UiPager v-model:page="page" v-model:page-size="pageSize" :total="total" @change="load" />
    </section>

    <!-- 详情抽屉（§9.5：已落库统计概览+题目表；失败 error 全文+历史+llm_trace+retry） -->
    <UiDrawer v-if="detail.show" :title="drawerTitle" @close="detail.show = false">
      <template v-if="detail.data">
        <!-- 任务状态卡 -->
        <div class="block-head" style="margin-bottom: 8px">
          <span class="block-title">{{ detail.data.task.status_label }}</span>
          <span class="block-cnt">{{ detail.data.task.task_id }}</span>
        </div>
        <p class="cell-sub" style="margin-bottom: 12px">
          {{ detail.data.task.position_name }} · v{{ detail.data.task.model_version }}
          <template v-if="detail.data.task.created_at"> · 创建 {{ formatTime(detail.data.task.created_at) }}</template>
          <template v-if="detail.data.task.finished_at"> · 完成 {{ formatTime(detail.data.task.finished_at) }}</template>
        </p>

        <!-- RUNNING / QUEUED：进度条（离页不停任务，页面只能看到最后拉到的值） -->
        <div v-if="detail.data.task.status === 'RUNNING' || detail.data.task.status === 'QUEUED'" class="qk-progress">
          <div class="qk-bar">
            <div class="qk-bar-fill" :style="{ width: percent(detail.data.task) + '%' }"></div>
          </div>
          <div class="qk-line">
            {{ detail.data.task.progress?.done ?? 0 }}/{{ detail.data.task.progress?.total ?? 0 }} 档
            <template v-if="detail.data.task.progress?.current_item"> · {{ detail.data.task.progress.current_item }}</template>
          </div>
        </div>

        <!-- FAILED：error 全文（pre-wrap，不截断）+ retry 按钮 -->
        <div v-if="detail.data.task.status === 'FAILED'">
          <div class="banner">
            <span class="grow">
              <pre class="qk-errfull">{{ detail.data.task.error_msg || '未知错误' }}</pre>
            </span>
            <button class="btn danger" :disabled="retrying" @click="doRetry">重试生成</button>
          </div>
        </div>

        <!-- 已落库（v1 只做统计概览 + 题目表，SSOT §9.5 裁决5） -->
        <template v-if="detail.data.task.status === 'SUCCEEDED'">
          <details class="fold" open>
            <summary><span class="caret">▶</span> item × 难度覆盖统计</summary>
            <div class="fold-body">
              <table v-if="detail.data.coverage.length">
                <thead>
                  <tr><th style="width: 34%">std_name</th><th style="width: 18%">category</th><th class="num" style="width: 8%">easy</th><th class="num" style="width: 8%">medium</th><th class="num" style="width: 8%">hard</th><th class="num" style="width: 24%">合计</th></tr>
                </thead>
                <tbody>
                  <tr v-for="c in detail.data.coverage" :key="`${c.std_name}|${c.category}`">
                    <td v-clip><span class="cell-main">{{ c.std_name }}</span></td>
                    <td><span class="tag">{{ categoryLabel(c.category) }}</span></td>
                    <td class="num">{{ c.easy }}</td>
                    <td class="num">{{ c.medium }}</td>
                    <td class="num">{{ c.hard }}</td>
                    <td class="num">{{ c.easy + c.medium + c.hard }}</td>
                  </tr>
                </tbody>
              </table>
              <p v-else class="field-hint">无统计（该题库无 active 题目）</p>
            </div>
          </details>

          <details class="fold" open>
            <summary><span class="caret">▶</span> 题目表</summary>
            <div class="fold-body">
              <table v-if="questions.items.length">
                <thead>
                  <tr><th style="width: 18%">std_name</th><th style="width: 13%">difficulty</th><th style="width: 11%">qtype</th><th style="width: 10%">status</th><th style="width: 48%">stem 预览</th></tr>
                </thead>
                <tbody>
                  <tr v-for="q in questions.items" :key="q.question_id">
                    <td v-clip><span class="cell-main">{{ q.std_name }}</span></td>
                    <td><span class="tag">{{ q.difficulty || '—' }}</span></td>
                    <td class="cell-sub">{{ q.qtype }}</td>
                    <!-- 归档扩展：题目行 status 列（值仅 active/archived，直译；归档版详情后端已放开全量） -->
                    <td><span v-if="q.status === 'archived'" class="tag qk-archived-tag">已归档</span><span v-else class="tag">使用中</span></td>
                    <td v-clip class="cell-sub">{{ q.stem_preview }}</td>
                  </tr>
                </tbody>
              </table>
              <p v-else class="field-hint">该位置暂无题目</p>
              <UiPager
                v-model:page="qPage"
                v-model:page-size="qPageSize"
                :total="questions.total"
                @change="loadQuestions"
              />
            </div>
          </details>
        </template>

        <!-- 非 SUCCEEDED：历史任务行 + llm_trace 折叠（失败排障主场景） -->
        <template v-else>
          <details class="fold" open>
            <summary><span class="caret">▶</span> 历史任务行（{{ detail.data.history.length }}）</summary>
            <div class="fold-body">
              <table>
                <thead>
                  <tr><th style="width: 22%">status</th><th style="width: 20%">created_at</th><th style="width: 20%">finished_at</th><th style="width: 38%">error</th></tr>
                </thead>
                <tbody>
                  <tr v-for="h in detail.data.history" :key="h.task_id">
                    <td>
                      <span v-if="h.status === 'RUNNING'" class="tag warm">RUNNING</span>
                      <span v-else-if="h.status === 'QUEUED'" class="tag warm">QUEUED</span>
                      <span v-else-if="h.status === 'SUCCEEDED'" class="tag tag-solid">SUCCEEDED</span>
                      <span v-else class="tag tag-red">FAILED</span>
                    </td>
                    <td>{{ formatTime(h.created_at) }}</td>
                    <td>{{ formatTime(h.finished_at) }}</td>
                    <td v-clip class="cell-sub">{{ h.error_msg || '—' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </details>

          <details class="fold" open>
            <summary><span class="caret">▶</span> LLM 调用留痕（{{ detail.data.traces.length }} 次）</summary>
            <div class="fold-body">
              <template v-if="detail.data.traces.length">
                <details v-for="t in detail.data.traces" :key="t.trace_id" class="fold qk-trace">
                  <summary>
                    <span class="caret">▶</span>
                    {{ formatTime(t.created_at) }} · attempt {{ t.attempt }}
                    <span v-if="t.success" class="tag tag-solid">OK</span>
                    <span v-else class="tag tag-red">FAIL</span>
                  </summary>
                  <div class="fold-body">
                    <pre class="raw">{{ t.prompt || '—' }}</pre>
                    <pre v-if="t.response" class="raw">{{ t.response }}</pre>
                    <div v-if="t.error" class="banner" style="margin-top: 4px"><span>{{ t.error }}</span></div>
                  </div>
                </details>
              </template>
              <p v-else class="field-hint">时间窗内无 question_gen 调用留痕</p>
            </div>
          </details>
        </template>
      </template>
      <div v-else class="loading">LOADING…</div>
    </UiDrawer>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { adminQbank, errMsg } from '../../api'
import { UiDrawer, UiPager, toast } from '../../components/ui'
import { categoryLabel, formatTime } from '../../lib/labels'

// ---- 列表 ----
const loading = ref(false)
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)
const statusFilter = ref('')
const bankStatusFilter = ref('') // 归档扩展：全部 / 使用中(active) / 已归档(archived)

const STATUS_LABELS = { RUNNING: '生成中', QUEUED: '排队·生成中', SUCCEEDED: '已落库', FAILED: '生成失败' }

// ---- 详情抽屉 ----
const detail = reactive({ show: false, taskId: '', data: null })
const questions = reactive({ items: [], total: 0 })
const qPage = ref(1)
const qPageSize = ref(10)
const retrying = ref(false)

const drawerTitle = computed(() =>
  detail.data ? `题库任务 · ${detail.data.task.position_name}` : '题库任务')

function percent(t) {
  const p = t.progress || {}
  const tot = Number(p.total) || 0
  if (tot <= 0) return 0
  return Math.min(100, Math.round((Number(p.done) / tot) * 100))
}

async function load() {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (statusFilter.value) params.status_filter = statusFilter.value
    if (bankStatusFilter.value) params.bank_status = bankStatusFilter.value
    const { data } = await adminQbank.list(params)
    items.value = data.items
    total.value = data.total
  } catch (e) {
    toast(errMsg(e, '题库任务加载失败'), 'error')
  } finally {
    loading.value = false
  }
}

function resetAndLoad() {
  page.value = 1
  load()
  schedulePoll()
}

// ---- 3s 轮询：有 RUNNING/QUEUED 行时拉列表（任务与页面解耦，离页停轮询不停任务） ----
let pollTimer = null

function hasLiveRow() {
  return items.value.some((t) => t.status === 'RUNNING' || t.status === 'QUEUED')
}

function schedulePoll() {
  stopPoll()
  pollTimer = setInterval(async () => {
    if (!hasLiveRow()) { stopPoll(); return }
    try {
      const params = { page: page.value, page_size: pageSize.value }
      if (statusFilter.value) params.status_filter = statusFilter.value
      if (bankStatusFilter.value) params.bank_status = bankStatusFilter.value
      const { data } = await adminQbank.list(params)
      items.value = data.items
      total.value = data.total
      // 详情抽屉开着且正在看生成中任务 → 同步刷新详情（进度条行走）
      if (detail.show && detail.data && !['SUCCEEDED', 'FAILED'].includes(detail.data.task.status)) {
        refreshOpenDetailQuiet()
      }
    } catch { /* 瞬时失败下轮再试 */ }
  }, 3000)
}

function stopPoll() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

async function openDetail(t) {
  detail.taskId = t.task_id
  detail.data = null
  questions.items = []
  questions.total = 0
  qPage.value = 1
  detail.show = true
  await refreshOpenDetail()
}

async function refreshOpenDetail() {
  try {
    const { data } = await adminQbank.detail(detail.taskId)
    data.task.status_label = STATUS_LABELS[data.task.status] || data.task.status
    detail.data = data
    await loadQuestions()
  } catch (e) {
    if (e?.response?.status === 404) {
      detail.show = false
      toast('任务不存在（可能已被清理）', 'warn')
    } else {
      toast(errMsg(e, '详情加载失败'), 'error')
    }
  }
}

async function refreshOpenDetailQuiet() {
  try {
    const { data } = await adminQbank.detail(detail.taskId)
    data.task.status_label = STATUS_LABELS[data.task.status] || data.task.status
    // 轮转成功 → 详情切回 SUCCEEDED 布局：补拉题目表
    if (data.task.status === 'SUCCEEDED' && detail.data?.task.status !== 'SUCCEEDED') {
      detail.data = data
      await loadQuestions()
      toast('题库已生成完成')
      await load()
      return
    }
    if (data.task.status === 'FAILED' && detail.data?.task.status !== 'FAILED') {
      toast(data.task.error_msg || '题库生成失败', 'error')
      await load()
    }
    detail.data = data
  } catch { /* 下轮再试 */ }
}

async function loadQuestions() {
  try {
    const { data } = await adminQbank.questions(detail.taskId, { page: qPage.value, page_size: qPageSize.value })
    questions.items = data.items
    questions.total = data.total
  } catch (e) {
    toast(errMsg(e, '题目表加载失败'), 'error')
  }
}

// ---- retry：仅 FAILED 可点（按钮只在 FAILED 状态渲染）；成功后重拉列表转入轮询 ----
async function doRetry() {
  if (retrying.value) return
  retrying.value = true
  try {
    await adminQbank.retry(detail.taskId)
    toast('已重新排队生成')
    detail.show = false
    await load()
    const hit = items.value.find((t) => t.position_id === detail.data?.task.position_id)
    if (hit) openDetail(hit)
    schedulePoll()
  } catch (e) {
    toast(errMsg(e, '重试失败'), 'error')
  } finally {
    retrying.value = false
  }
}

onMounted(() => {
  load()
  schedulePoll() // 进页认领：列表含 RUNNING/QUEUED 行即开始轮询
})

onBeforeUnmount(stopPoll)
</script>

<style scoped>
.qk-progress { margin-bottom: 16px; }
.qk-bar { height: 6px; border-radius: 3px; background: rgba(38, 38, 42, 0.08); overflow: hidden; }
.qk-bar-fill { height: 100%; border-radius: 3px; background: var(--ink-1); transition: width 0.3s ease; }
.qk-line { font-size: 11px; color: var(--ink-3); margin-top: 4px; }
.qk-err { font-size: 12px; color: var(--danger); }
.qk-errfull { white-space: pre-wrap; word-break: break-all; font-size: 12px; line-height: 1.6; color: var(--danger); margin: 0; }
.qk-trace { margin-bottom: 8px; }
/* 归档扩展：已归档行弱化视觉（复用 .tag 形态，muted 配色） */
.qk-archived-tag { margin-left: 4px; color: var(--ink-3); border-style: dashed; }
.qk-archived-cnt { font-size: 10px; color: var(--ink-3); }
</style>
