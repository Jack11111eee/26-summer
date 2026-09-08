<template>
  <div>
    <header class="topbar">
      <div>
        <div class="topbar-title">模型<span>聚合</span></div>
        <div class="topbar-meta">AGGREGATIONS · {{ total }} POSITIONS</div>
      </div>
      <div class="topbar-actions">
        <button class="btn" :disabled="loading" @click="resetAndLoad">刷新</button>
      </div>
    </header>

    <!-- KPI 四块（§8.6：草稿 / 已确认 / stalled / 聚合中） -->
    <div class="stats">
      <div class="stat" :class="{ hot: summary.draft_positions > 0 }">
        <div class="stat-label">草稿岗位</div>
        <div class="stat-num">{{ pad(summary.draft_positions) }}</div>
        <div class="stat-foot">待人工审核确认</div>
      </div>
      <div class="stat">
        <div class="stat-label">已确认岗位</div>
        <div class="stat-num">{{ pad(summary.confirmed_positions) }}</div>
        <div class="stat-foot">模型已生效</div>
      </div>
      <div class="stat" :class="{ hot: summary.stalled_positions > 0 }">
        <div class="stat-label">stalled 岗位</div>
        <div class="stat-num">{{ pad(summary.stalled_positions) }}</div>
        <div class="stat-foot">等级裁决失败滞留</div>
      </div>
      <div class="stat" :class="{ hot: summary.running_tasks > 0 }">
        <div class="stat-label">聚合中</div>
        <div class="stat-num">{{ pad(summary.running_tasks) }}</div>
        <div class="stat-foot">后台任务运行</div>
      </div>
    </div>

    <!-- 筛选（§8.6：模型状态 + 任务状态 + 岗位名搜索） -->
    <div class="filters">
      <select v-model="modelStatusFilter" class="select" @change="resetAndLoad">
        <option value="">全部模型</option>
        <option value="draft">草稿</option>
        <option value="confirmed">已确认</option>
        <option value="stalled">stalled</option>
      </select>
      <select v-model="taskStatusFilter" class="select" @change="resetAndLoad">
        <option value="">全部任务</option>
        <option value="RUNNING">聚合中</option>
        <option value="SUCCEEDED">已完成</option>
        <option value="FAILED">失败</option>
      </select>
      <input
        v-model="q"
        class="input search"
        type="text"
        placeholder="搜索岗位名…"
        @keyup.enter="resetAndLoad"
        @input="onSearchInput"
      />
    </div>

    <section class="block n2">
      <div class="block-head">
        <span class="block-title">聚合岗位</span>
        <span class="block-cnt">{{ total }} 个</span>
      </div>
      <table>
        <thead>
          <tr>
            <th style="width: 24%">position</th><th style="width: 8%" class="num">jd</th>
            <th style="width: 14%">model</th><th style="width: 30%">task / progress</th>
            <th style="width: 8%" class="num">items</th><th style="width: 16%">finished_at</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="r in items"
            :key="r.position_id"
            style="cursor: pointer"
            @click="goReview(r)"
          >
            <td v-clip><span class="cell-main">{{ r.position_name }}</span></td>
            <td class="num">{{ r.jd_count }}</td>
            <td>
              <template v-if="r.model">
                <span class="tag">{{ 'v' + r.model.version }}</span>
                <span v-if="r.model.status === 'draft'" class="tag warm">草稿</span>
                <span v-else-if="r.model.status === 'confirmed'" class="tag tag-solid">已确认</span>
                <span v-else class="tag tag-red">stalled</span>
              </template>
              <span v-else class="cell-sub">无模型（聚合中）</span>
            </td>
            <td>
              <!-- RUNNING：进度条 + 双计数 + 当前项（§8.4 前端联动形态） -->
              <div v-if="r.task?.status === 'RUNNING'">
                <div class="ag-bar">
                  <div class="ag-bar-fill" :style="{ width: percent(r) + '%' }"></div>
                </div>
                <div class="ag-line">
                  {{ r.task.progress?.done ?? 0 }}/{{ r.task.progress?.total ?? 0 }} 项 ·
                  裁决 {{ r.task.progress?.llm_done ?? 0 }}/{{ r.task.progress?.llm_total ?? 0 }}
                  <template v-if="r.task.progress?.current_item"> · {{ r.task.progress.current_item }}</template>
                </div>
              </div>
              <!-- FAILED：error 摘要 + stalled/无模型行内重聚合入口（受 409 守卫） -->
              <template v-else-if="r.task?.status === 'FAILED'">
                <div class="ag-err" v-clip>{{ r.task.error || '未知错误' }}</div>
                <div v-if="r.model?.status === 'stalled' || !r.model" class="row-actions" @click.stop>
                  <button class="row-btn" :disabled="acting" @click="reaggregate(r)">
                    {{ r.model?.status === 'stalled' ? '重新聚合（清 stall）' : '开始聚合' }}
                  </button>
                </div>
              </template>
              <template v-else-if="r.task">
                <span class="tag">{{ triggerLabel(r.task.trigger_source) }}</span>
                <span class="cell-sub"> {{ r.task.status === 'SUCCEEDED' ? '完成' : r.task.status }}</span>
              </template>
              <span v-else class="cell-sub">—</span>
            </td>
            <td class="num">{{ r.model ? r.item_count : '—' }}</td>
            <td>{{ formatTime(r.task?.finished_at) }}</td>
          </tr>
          <tr v-if="!items.length && !loading">
            <td colspan="6" class="empty-row">暂无聚合岗位（导入 JD 并解析完成后自动聚合）</td>
          </tr>
        </tbody>
      </table>
      <UiPager v-model:page="page" v-model:page-size="pageSize" :total="total" @change="load" />
    </section>
  </div>
</template>

<script setup>
// 模型聚合页（SSOT §8.6，2026-09-08）：跨岗位的聚合任务与模型产物总览。
// 行源「有模型或有任务行」的 active 岗位；点行跳既有审核页（零新详情页）；
// 3s 轮询含 RUNNING 行时启停（进页认领 / 离页停表不停任务，§5 keep-alive 范式）。
import { onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { adminModels, errMsg } from '../../api'
import { UiPager, toast } from '../../components/ui'
import { formatTime } from '../../lib/labels'

defineOptions({ name: 'AdminModelAggregation' }) // 壳内 keep-alive include 依名匹配（§5，2026-09-08）

const router = useRouter()

const loading = ref(false)
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)
const summary = ref({ draft_positions: 0, confirmed_positions: 0, stalled_positions: 0, running_tasks: 0 })
const modelStatusFilter = ref('')
const taskStatusFilter = ref('')
const q = ref('')
const acting = ref(false)

const TRIGGER_LABELS = { manual: '手动', retry: '重试', 'auto:jd-parse': '自动' }

function pad(n) {
  return n == null ? '—' : String(n).padStart(2, '0')
}

function triggerLabel(v) {
  return TRIGGER_LABELS[v] || v || '—'
}

function percent(r) {
  const p = r.task?.progress || {}
  const tot = Number(p.total) || 0
  if (tot <= 0) return 0
  return Math.min(100, Math.round((Number(p.done) / tot) * 100))
}

async function load() {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (modelStatusFilter.value) params.model_status = modelStatusFilter.value
    if (taskStatusFilter.value) params.task_status = taskStatusFilter.value
    if (q.value.trim()) params.q = q.value.trim()
    const { data } = await adminModels.listAggregations(params)
    items.value = data.items
    total.value = data.total
    summary.value = data.summary
  } catch (e) {
    toast(errMsg(e, '聚合列表加载失败'), 'error')
  } finally {
    loading.value = false
  }
}

function resetAndLoad() {
  page.value = 1
  load()
  schedulePoll()
}

// 搜索防抖 400ms（岗位名子串，服务端 LIKE）
let searchTimer = null
function onSearchInput() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(resetAndLoad, 400)
}

// ---- 3s 轮询：有 RUNNING 行时拉列表（任务与页面解耦，离页停表不停任务） ----
let pollTimer = null

function hasLiveRow() {
  return items.value.some((r) => r.task?.status === 'RUNNING')
}

function schedulePoll() {
  stopPoll()
  pollTimer = setInterval(async () => {
    if (!hasLiveRow()) { stopPoll(); return }
    try {
      const params = { page: page.value, page_size: pageSize.value }
      if (modelStatusFilter.value) params.model_status = modelStatusFilter.value
      if (taskStatusFilter.value) params.task_status = taskStatusFilter.value
      if (q.value.trim()) params.q = q.value.trim()
      const { data } = await adminModels.listAggregations(params)
      items.value = data.items
      total.value = data.total
      summary.value = data.summary
      // RUNNING → 终态轮转时提示（完成后行内 model 出现）
    } catch { /* 瞬时失败下轮再试 */ }
  }, 3000)
}

function stopPoll() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

// ---- 行内快捷重聚合（仅 stalled 行 / FAILED 且无模型行；409 守卫在后端） ----
async function reaggregate(r) {
  if (acting.value) return
  acting.value = true
  try {
    if (r.model?.status === 'stalled') {
      await adminModels.retryLevel(r.position_id)
      toast('已重试 LLM 聚合，进行中…')
    } else {
      await adminModels.aggregate(r.position_id)
      toast('已触发聚合，进行中…')
    }
    await load()
    schedulePoll()
  } catch (e) {
    toast(errMsg(e, '聚合触发失败'), 'error')
    await load()
  } finally {
    acting.value = false
  }
}

function goReview(r) {
  router.push(`/admin/positions/${r.position_id}/review`)
}

onMounted(() => {
  load()
  schedulePoll() // 进页认领：列表含 RUNNING 行即开始轮询
})

// keep-alive（§5，2026-09-08）：激活 = 静默刷新保筛选保页码 + 复轮询（booted 守卫防
// 首屏双拉）；失活 = 停表（keep-alive 下路由切换不触发 unmount，不停表则后台常跑）
let booted = false
onActivated(() => {
  if (!booted) { booted = true; return }
  load()
  schedulePoll()
})
onDeactivated(stopPoll)

onBeforeUnmount(() => {
  stopPoll()
  if (searchTimer) clearTimeout(searchTimer)
})
</script>

<style scoped>
.ag-bar { height: 6px; border-radius: 3px; background: rgba(38, 38, 42, 0.08); overflow: hidden; }
.ag-bar-fill { height: 100%; border-radius: 3px; background: var(--ink-1); transition: width 0.3s ease; }
.ag-line { font-size: 11px; color: var(--ink-3); margin-top: 4px; }
.ag-err { font-size: 12px; color: var(--danger); }
</style>
