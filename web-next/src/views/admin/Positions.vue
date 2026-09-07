<template>
  <div>
    <header class="topbar">
      <div>
        <div class="topbar-title">岗位<span>库</span></div>
        <div class="topbar-meta">{{ metaText }}</div>
      </div>
      <div class="topbar-actions">
        <button class="btn" :disabled="loading" @click="refreshAll">刷新</button>
        <button class="btn primary" @click="goImport">＋ 导入 JD</button>
      </div>
    </header>

    <div v-if="loading && !loaded" class="loading">LOADING…</div>

    <template v-if="loaded">
      <!-- KPI 素色块 -->
      <div class="stats">
        <div class="stat" :class="{ hot: todos.pending_positions > 0 }">
          <div class="stat-label">待审新岗位</div>
          <div class="stat-num">{{ pad(todos.pending_positions) }}</div>
          <div class="stat-foot">等待确认入编</div>
        </div>
        <div class="stat" :class="{ hot: todos.stalled_models > 0 }">
          <div class="stat-label">stalled 模型</div>
          <div class="stat-num">{{ pad(todos.stalled_models) }}</div>
          <div class="stat-foot">等级裁决失败滞留</div>
        </div>
        <div class="stat" :class="{ hot: todos.orphan_jds > 0 }">
          <div class="stat-label">待归属 JD</div>
          <div class="stat-num">{{ pad(todos.orphan_jds) }}</div>
          <div class="stat-foot">暂无岗位指向</div>
        </div>
        <div class="stat" :class="{ alert: todos.question_bank_not_ready > 0 }">
          <div class="stat-label">题库未就绪</div>
          <div class="stat-num">{{ pad(todos.question_bank_not_ready) }}</div>
          <div class="stat-foot">{{ qbankFootText }}</div>
        </div>
      </div>

      <!-- 模块一：待审新岗位 -->
      <section class="block n1">
        <div class="block-head">
          <span class="block-title">待审新岗位</span>
          <span class="block-cnt">{{ cntText(pending) }}</span>
        </div>
        <div class="filters">
          <input
            v-model="pending.q"
            class="input search"
            type="text"
            placeholder="搜索岗位名…"
            @input="onFilterInput(pending, adminPositions.listPending)"
          />
          <span v-if="pending.indexing" class="field-hint">建立筛选索引…</span>
        </div>
        <table>
          <thead>
            <tr><th style="width: 44%">position_name</th><th class="num" style="width: 12%">jd_count</th><th style="width: 22%">created_at</th><th style="width: 22%; text-align: right">action</th></tr>
          </thead>
          <tbody>
            <tr v-for="p in pendingView.items" :key="p.position_id">
              <td v-clip>
                <div class="cell-main">{{ p.name }}</div>
                <div class="cell-sub">归岗未命中 · LLM 判定为全新岗位</div>
              </td>
              <td class="num">{{ p.jd_count }}</td>
              <td>{{ formatTime(p.created_at) }}</td>
              <td>
                <div class="row-actions">
                  <button class="row-btn" :disabled="acting" @click="review(p, 'approve')">通过</button>
                  <button class="row-btn row-btn-danger" :disabled="acting" @click="review(p, 'reject')">拒绝</button>
                </div>
              </td>
            </tr>
            <tr v-if="!pendingView.items.length"><td colspan="4" class="empty-row">暂无待审岗位</td></tr>
          </tbody>
        </table>
        <UiPager
          v-if="pendingView.total > pending.pageSize"
          v-model:page="pending.page"
          v-model:page-size="pending.pageSize"
          :total="pendingView.total"
          @change="loadPending"
        />
      </section>

      <!-- 模块二：待归属 JD -->
      <section class="block n2">
        <div class="block-head">
          <span class="block-title">待归属 JD</span>
          <span class="block-cnt">{{ cntText(orphans) }}</span>
        </div>
        <div class="filters">
          <input
            v-model="orphans.q"
            class="input search"
            type="text"
            placeholder="搜索标题 / 公司…"
            @input="onFilterInput(orphans, adminPositions.listOrphanJds)"
          />
          <span v-if="orphans.indexing" class="field-hint">建立筛选索引…</span>
        </div>
        <table>
          <thead>
            <tr><th style="width: 38%">job_title</th><th style="width: 15%">company</th><th style="width: 10%">source</th><th style="width: 13%">created_at</th><th style="width: 24%">改归岗位</th></tr>
          </thead>
          <tbody>
            <tr v-for="j in orphansView.items" :key="j.jd_id">
              <td v-clip><span class="cell-main">{{ j.job_title || '（未识别标题）' }}</span></td>
              <td v-clip>{{ j.company || '—' }}</td>
              <td>{{ j.source_type || '—' }}</td>
              <td>{{ formatTime(j.created_at) }}</td>
              <td>
                <div class="row-actions" style="justify-content: flex-start">
                  <select
                    v-if="positionOptions.length"
                    class="select"
                    :value="reassignSel[j.jd_id] || ''"
                    @change="onReassign(j, $event)"
                  >
                    <option value="" disabled>选择岗位…</option>
                    <option v-for="o in positionOptions" :key="o.position_id" :value="o.position_id">{{ o.name }}</option>
                  </select>
                </div>
              </td>
            </tr>
            <tr v-if="!orphansView.items.length"><td colspan="5" class="empty-row">暂无待归属 JD</td></tr>
          </tbody>
        </table>
        <UiPager
          v-if="orphansView.total > orphans.pageSize"
          v-model:page="orphans.page"
          v-model:page-size="orphans.pageSize"
          :total="orphansView.total"
          @change="loadOrphans"
        />
      </section>

      <!-- 模块三：岗位清单 -->
      <section class="block n2">
        <div class="block-head">
          <span class="block-title">岗位清单</span>
          <span class="block-cnt">{{ cntText(positions) }}</span>
        </div>
        <div class="filters">
          <select
            v-model="positions.statusFilter"
            class="select"
            @change="onFilterSelect(positions, adminPositions.listPositions)"
          >
            <option value="">全部状态</option>
            <option value="active">上架 active</option>
            <option value="inactive">下架 inactive</option>
            <option value="pending_review">待审核</option>
          </select>
          <input
            v-model="positions.q"
            class="input search"
            type="text"
            placeholder="搜索岗位名…"
            @input="onFilterInput(positions, adminPositions.listPositions)"
          />
          <span v-if="positions.indexing" class="field-hint">建立筛选索引…</span>
        </div>
        <table>
          <thead>
            <tr><th style="width: 40%">position_name</th><th style="width: 16%">status</th><th class="num" style="width: 12%">jd_count</th><th style="width: 32%; text-align: right">action</th></tr>
          </thead>
          <tbody>
            <tr v-for="p in positionsView.items" :key="p.position_id">
              <td v-clip><span class="cell-main">{{ p.name }}</span></td>
              <td>
                <span v-if="p.status === 'active'" class="tag tag-solid">ACTIVE</span>
                <span v-else-if="p.status === 'inactive'" class="tag tag-red">INACTIVE</span>
                <span v-else class="tag">待审核</span>
              </td>
              <td class="num">{{ p.jd_count }}</td>
              <td>
                <div class="row-actions">
                  <button class="row-btn" @click="goDetail(p)">详情</button>
                  <button class="row-btn row-btn-solid" :disabled="p.status !== 'active'" @click="goReview(p)">模型审核</button>
                </div>
              </td>
            </tr>
            <tr v-if="!positionsView.items.length"><td colspan="4" class="empty-row">暂无岗位</td></tr>
          </tbody>
        </table>
        <UiPager
          v-model:page="positions.page"
          v-model:page-size="positions.pageSize"
          :total="positionsView.total"
          @change="loadPositions"
        />
      </section>
    </template>

    <!-- 拒绝岗位确认（删除性操作） -->
    <UiConfirm
      v-if="confirmState.show"
      title="拒绝新岗位"
      :message="`确认拒绝「${confirmState.position?.name}」？岗位将被撤销，其下 ${confirmState.position?.jd_count ?? 0} 条 JD 进入待归属队列。`"
      confirm-text="确认拒绝"
      danger
      @close="confirmState.show = false"
      @confirm="onConfirmReject"
    />
  </div>
</template>

<script setup>
// 岗位库：三块列表 + 筛选。
// 数据模式（A′ 懒加载）：进页照常服务端分页（首屏成本与改造前一致）；
// 首次使用筛选/搜索时才全量拉取轻行建本地索引（page_size=100 循环，本地 SQLite
// 数百 ms），此后筛选/搜索/翻页均在内存完成、零请求；操作（审核/改归）后就地
// 重拉对应块保持筛选视图一致；「刷新」重置筛选回服务端模式。
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { adminPositions, errMsg } from '../../api'
import { UiPager, UiConfirm, toast } from '../../components/ui'
import { formatTime } from '../../lib/labels'

const router = useRouter()

const loading = ref(false)
const loaded = ref(false)
const acting = ref(false)
const confirmState = reactive({ show: false, position: null })

const todos = reactive({ pending_positions: 0, stalled_models: 0, orphan_jds: 0, question_bank_not_ready: 0, question_bank_failed: [] })
// mode: 'server' 服务端分页 | 'local' 本地索引（筛选激活后）
function mkBlock() {
  return reactive({ items: [], total: 0, page: 1, pageSize: 10, q: '', statusFilter: '', mode: 'server', all: [], indexing: false })
}
const pending = mkBlock()
const orphans = mkBlock()
const positions = mkBlock()
const positionOptions = ref([])
const reassignSel = reactive({})

const metaText = computed(() => `${positions.total} POSITIONS · ${todos.orphan_jds} ORPHAN JDS`)

const qbankFootText = computed(() => {
  const f = todos.question_bank_failed || []
  return f.length ? (f[0].error_msg || '最新生成任务失败') : '确认后异步生成'
})

function pad(n) {
  return n == null ? '—' : String(n).padStart(2, '0')
}

// ---- 本地过滤视图（mode=local 时启用）----
function matches(b, it) {
  if (b === positions) {
    if (b.statusFilter && it.status !== b.statusFilter) return false
  }
  if (b.q) {
    const q = b.q.trim().toLowerCase()
    if (!q) return true
    const hay = b === orphans
      ? `${it.job_title || ''} ${it.company || ''}`
      : it.name || ''
    if (!hay.toLowerCase().includes(q)) return false
  }
  return true
}

function localView(b) {
  const filtered = b.all.filter((it) => matches(b, it))
  const start = (b.page - 1) * b.pageSize
  return { items: filtered.slice(start, start + b.pageSize), total: filtered.length }
}

const pendingView = computed(() => (pending.mode === 'local' ? localView(pending) : { items: pending.items, total: pending.total }))
const orphansView = computed(() => (orphans.mode === 'local' ? localView(orphans) : { items: orphans.items, total: orphans.total }))
const positionsView = computed(() => (positions.mode === 'local' ? localView(positions) : { items: positions.items, total: positions.total }))

function cntText(b) {
  if (b.mode === 'local') return `${localViewTotal(b)} / ${b.all.length} 条`
  return `${b.total} 条`
}
function localViewTotal(b) {
  return b.all.filter((it) => matches(b, it)).length
}

// ---- 懒加载全量索引 ----
// 首页带 total → 算页数 → 并发拉余页（后端单请求 ~0.7s，串行 10 页≈8s 不可接受）
async function ensureIndex(b, fetcher, force = false) {
  if (b.mode === 'local' && !force) return
  b.indexing = true
  try {
    const { data: first } = await fetcher({ page: 1, page_size: 100 })
    const pages = Math.ceil(first.total / 100)
    const rest = []
    for (let p = 2; p <= Math.min(pages, 50); p++) rest.push(fetcher({ page: p, page_size: 100 })) // 上限防呆 5000 行
    const settles = await Promise.allSettled(rest)
    const all = [...first.items]
    for (const s of settles) if (s.status === 'fulfilled') all.push(...s.value.data.items)
    b.all = all
    b.page = 1
    b.mode = 'local'
    b.total = all.length // 本地模式下 total 即全量长度
    if (all.length < first.total) toast('部分数据未能加载，筛选结果可能不全', 'warn')
  } catch (e) {
    toast(errMsg(e, '筛选索引建立失败'), 'error')
  } finally {
    b.indexing = false
  }
}

// 输入即时过滤：若无索引先建（一次），此后纯内存
function onFilterInput(b, fetcher) {
  b.page = 1
  if (b.mode === 'server' && (b.q.trim() || b.statusFilter)) ensureIndex(b, fetcher)
  if (b.mode === 'local') { /* computed 视图即时重算 */ }
}

function onFilterSelect(b, fetcher) {
  b.page = 1
  if (b.mode === 'server' && (b.q.trim() || b.statusFilter)) ensureIndex(b, fetcher)
}

// ---- 数据加载 ----
async function loadTodos() {
  const { data } = await adminPositions.getTodos()
  Object.assign(todos, data)
}

async function loadPending() {
  if (pending.mode === 'local') return // 本地模式下翻页零请求
  const { data } = await adminPositions.listPending({ page: pending.page, page_size: pending.pageSize })
  pending.items = data.items
  pending.total = data.total
}

async function loadOrphans() {
  if (orphans.mode === 'local') return
  const { data } = await adminPositions.listOrphanJds({ page: orphans.page, page_size: orphans.pageSize })
  orphans.items = data.items
  orphans.total = data.total
}

async function loadPositions() {
  if (positions.mode === 'local') return
  const { data } = await adminPositions.listPositions({ page: positions.page, page_size: positions.pageSize })
  positions.items = data.items
  positions.total = data.total
}

async function loadOptions() {
  const { data } = await adminPositions.positionOptions()
  positionOptions.value = data
}

async function reloadAll() {
  loading.value = true
  try {
    await Promise.all([loadTodos(), loadPending(), loadOrphans(), loadPositions(), loadOptions()])
    loaded.value = true
  } catch (e) {
    toast(errMsg(e, '加载失败'), 'error')
  } finally {
    loading.value = false
  }
}

// 刷新按钮：重置筛选模式、回到服务端分页
async function refreshAll() {
  for (const b of [pending, orphans, positions]) {
    b.q = ''
    b.statusFilter = ''
    b.page = 1
    b.mode = 'server'
    b.all = []
  }
  await reloadAll()
}

// 审核：approve → active；reject → 撤销岗位（其下 JD 归 NULL），有子表占用时 409
function review(p, action) {
  if (action === 'approve') {
    doReview(p, 'approve')
  } else {
    confirmState.position = p
    confirmState.show = true
  }
}

async function onConfirmReject() {
  const p = confirmState.position
  confirmState.show = false
  await doReview(p, 'reject')
}

async function doReview(p, action) {
  acting.value = true
  try {
    await adminPositions.reviewPosition(p.position_id, action)
    toast(action === 'approve' ? `已通过「${p.name}」` : `已拒绝「${p.name}」，其下 JD 进入待归属队列`)
    await reloadAllForWrite()
  } catch (e) {
    toast(errMsg(e, '审核失败'), 'error')
  } finally {
    acting.value = false
  }
}

// 写操作后：保持 active 筛选模式重拉——local 模式强制重建索引、server 模式重拉当前页
async function reloadAllForWrite() {
  const jobs = [loadTodos(), loadOptions()]
  if (pending.mode === 'local') jobs.push(ensureIndex(pending, adminPositions.listPending, true))
  else jobs.push(loadPending())
  if (orphans.mode === 'local') jobs.push(ensureIndex(orphans, adminPositions.listOrphanJds, true))
  else jobs.push(loadOrphans())
  if (positions.mode === 'local') jobs.push(ensureIndex(positions, adminPositions.listPositions, true))
  else jobs.push(loadPositions())
  await Promise.all(jobs)
}

async function onReassign(j, e) {
  const target = e.target.value
  if (!target) return
  try {
    await adminPositions.reassignJd(j.jd_id, target)
    toast('JD 已改归')
    delete reassignSel[j.jd_id]
    e.target.value = ''
    await reloadAllForWrite()
  } catch (err) {
    toast(errMsg(err, '改归失败'), 'error')
    e.target.value = ''
  }
}

function goDetail(p) {
  router.push(`/admin/positions/${p.position_id}`)
}
function goReview(p) {
  router.push(`/admin/positions/${p.position_id}/review`)
}
function goImport() {
  // 导入需在岗位详情页操作；无岗位时提示先（任何入口的）导入
  const first = positions.items[0] || positionOptions.value[0]
  if (first) {
    router.push(`/admin/positions/${first.position_id}`)
    toast('请在岗位详情页右上角「＋ 导入 JD」')
  } else {
    toast('当前没有任何岗位；首次导入请在任一已有岗位详情页进行', 'warn')
  }
}

// 顶栏「刷新」走 reset 语义（清筛选）；其余写操作保持筛选
defineExpose({ refreshAll })

reloadAll()
</script>
