<template>
  <div>
    <header class="topbar">
      <div>
        <div class="topbar-title">岗位<span>库</span></div>
        <div class="topbar-meta">{{ metaText }}</div>
      </div>
      <div class="topbar-actions">
        <button class="btn" :disabled="loading" @click="reloadAll">刷新</button>
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
          <span class="block-cnt">{{ pending.total }} 条</span>
        </div>
        <table>
          <thead>
            <tr><th style="width: 44%">position_name</th><th class="num" style="width: 12%">jd_count</th><th style="width: 22%">created_at</th><th style="width: 22%; text-align: right">action</th></tr>
          </thead>
          <tbody>
            <tr v-for="p in pending.items" :key="p.position_id">
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
            <tr v-if="!pending.items.length"><td colspan="4" class="empty-row">暂无待审岗位</td></tr>
          </tbody>
        </table>
        <UiPager
          v-if="pending.total > pending.pageSize"
          v-model:page="pending.page"
          v-model:page-size="pending.pageSize"
          :total="pending.total"
          @change="loadPending"
        />
      </section>

      <!-- 模块二：待归属 JD -->
      <section class="block n2">
        <div class="block-head">
          <span class="block-title">待归属 JD</span>
          <span class="block-cnt">{{ orphans.total }} 条</span>
        </div>
        <table>
          <thead>
            <tr><th style="width: 38%">job_title</th><th style="width: 15%">company</th><th style="width: 10%">source</th><th style="width: 13%">created_at</th><th style="width: 24%">改归岗位</th></tr>
          </thead>
          <tbody>
            <tr v-for="j in orphans.items" :key="j.jd_id">
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
            <tr v-if="!orphans.items.length"><td colspan="5" class="empty-row">暂无待归属 JD</td></tr>
          </tbody>
        </table>
        <UiPager
          v-if="orphans.total > orphans.pageSize"
          v-model:page="orphans.page"
          v-model:page-size="orphans.pageSize"
          :total="orphans.total"
          @change="loadOrphans"
        />
      </section>

      <!-- 模块三：岗位清单 -->
      <section class="block n2">
        <div class="block-head">
          <span class="block-title">岗位清单</span>
          <span class="block-cnt">{{ positions.total }} 个岗位</span>
        </div>
        <table>
          <thead>
            <tr><th style="width: 40%">position_name</th><th style="width: 16%">status</th><th class="num" style="width: 12%">jd_count</th><th style="width: 32%; text-align: right">action</th></tr>
          </thead>
          <tbody>
            <tr v-for="p in positions.items" :key="p.position_id">
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
            <tr v-if="!positions.items.length"><td colspan="4" class="empty-row">暂无岗位</td></tr>
          </tbody>
        </table>
        <UiPager
          v-model:page="positions.page"
          v-model:page-size="positions.pageSize"
          :total="positions.total"
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
const pending = reactive({ items: [], total: 0, page: 1, pageSize: 10 })
const orphans = reactive({ items: [], total: 0, page: 1, pageSize: 10 })
const positions = reactive({ items: [], total: 0, page: 1, pageSize: 10 })
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

async function loadTodos() {
  const { data } = await adminPositions.getTodos()
  Object.assign(todos, data)
}

async function loadPending() {
  const { data } = await adminPositions.listPending({ page: pending.page, page_size: pending.pageSize })
  pending.items = data.items
  pending.total = data.total
}

async function loadOrphans() {
  const { data } = await adminPositions.listOrphanJds({ page: orphans.page, page_size: orphans.pageSize })
  orphans.items = data.items
  orphans.total = data.total
}

async function loadPositions() {
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

// 审核：approve → active；reject → 撤销岗位（其下 JD 归 NULL）
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
    await Promise.all([loadTodos(), loadPending(), loadOrphans(), loadPositions(), loadOptions()])
  } catch (e) {
    toast(errMsg(e, '审核失败'), 'error')
  } finally {
    acting.value = false
  }
}

async function onReassign(j, e) {
  const target = e.target.value
  if (!target) return
  try {
    await adminPositions.reassignJd(j.jd_id, target)
    toast('JD 已改归')
    delete reassignSel[j.jd_id]
    e.target.value = ''
    await Promise.all([loadTodos(), loadOrphans()])
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

reloadAll()
</script>
