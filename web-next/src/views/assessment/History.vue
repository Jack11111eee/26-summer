<template>
  <div class="page">
    <!-- 删除确认（§12.1 软删除：三态行均可删，文案如实——in_progress 即用户主动作废） -->
    <UiConfirm
      v-if="delTarget"
      title="删除测评记录"
      :message="delTarget.status === 'in_progress'
        ? '删除将作废本场测评，进度不可恢复。确认删除？'
        : '删除后该记录不再显示，报告不可再访问。确认删除？'"
      confirm-text="删除"
      danger
      @close="delTarget = null"
      @confirm="confirmDelete"
    />

    <div class="page-head">
      <div class="open-head serif">
        <div class="kicker">ASSESSMENT · 测评历史</div>
        <h1>我的测评记录</h1>
        <p>全部过往场次。进行中的场次可回到中断处继续；已完成的场次可查看报告或回看模型。</p>
      </div>
    </div>

    <div class="page-inner hist-inner">
      <!-- 状态过滤 -->
      <div class="hist-filter">
        <button
          v-for="f in STATUS_FILTERS"
          :key="f.value"
          class="filter-btn"
          :class="{ active: statusFilter === f.value }"
          type="button"
          @click="onFilter(f.value)"
        >{{ f.label }}</button>
      </div>

      <div v-if="loading" class="empty">加载历史记录中…</div>
      <div v-else-if="!items.length" class="empty">
        <p class="serif">暂无测评记录</p>
        <p style="font-size: 13px">从「岗位选择」开始你的第一场测评。</p>
      </div>

      <template v-else>
        <div v-for="it in items" :key="it.session_id" class="hist-card">
          <div class="hist-row-main">
            <div class="hist-title-row">
              <h3 class="serif">{{ it.position_name || '岗位' }}</h3>
              <span class="tb-badge">模型 v{{ it.model_version }}</span>
              <span v-if="it.status === 'in_progress'" class="chip">进行中</span>
              <span v-else-if="it.status === 'completed'" class="chip chip-done">已完成</span>
              <span v-else class="chip amber">已作废</span>
              <span v-if="it.status === 'in_progress' && it.phase === 'PENDING_START'" class="tb-badge">未开始</span>
              <span v-else-if="it.status === 'in_progress' && it.phase === 'PAUSED'" class="tb-badge">已暂停</span>
            </div>
            <p class="field-hint">
              {{ formatTime(it.created_at) }} · 已答 {{ it.answered_count }} 题<template v-if="remainingOf(it) != null"> · 剩余约 {{ remainingOf(it) }} 分钟</template>
            </p>
          </div>
          <div class="hist-actions">
            <!-- in_progress：继续直达 Chat（PAUSED/PENDING_START 由 Chat 页现有门卡处理） -->
            <button v-if="it.status === 'in_progress'" class="btn-accent hist-btn" @click="router.push(`/assessment/session/${it.session_id}`)">继续测评 →</button>
            <!-- completed：报告 + 模型两入口（Report bootstrap 自愈无报告与 FAILED 重入队）；
                 评估模型走 preview=1 只读预览态——不再作开考入口（2026-09-08 改） -->
            <template v-else-if="it.status === 'completed'">
              <button class="btn-accent hist-btn" @click="router.push(`/assessment/report/${it.session_id}`)">查看报告</button>
              <button class="btn-ghost hist-btn" @click="router.push(`/assessment/positions/${it.position_id}?preview=1`)">评估模型</button>
            </template>
            <!-- abandoned：仅作废标记，无入口 -->
            <span v-else class="field-hint" style="align-self: center">超时未归，已作废</span>
            <!-- 删除（§12.1 软删除，三态行均挂）：in_progress 删除即用户主动作废 -->
            <button class="hist-del" type="button" :disabled="deleting" @click="delTarget = it">删除</button>
          </div>
        </div>

        <UiPager
          v-model:page="page"
          v-model:page-size="pageSize"
          :total="total"
          @change="load"
        />
      </template>
    </div>
  </div>
</template>

<script setup>
// 测评历史页（§12.1/§12.6）：本人会话列表（服务端分页 + status 过滤），三态行入口——
// in_progress 继续直达 Chat（恢复链现成）；completed 报告/模型两入口（评估模型
// preview=1 只读预览，2026-09-08）；abandoned 只读；三态行均挂「删除」（软删除）。
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { assessment, errMsg } from '../../api'
import { toast, UiConfirm, UiPager } from '../../components/ui'
import { formatTime } from '../../lib/labels'

const router = useRouter()
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)
const statusFilter = ref('')
const loading = ref(false)
// 删除确认（UiConfirm 形态——同 Chat.vue 退出确认先例）：待删行快照 + 请求中锁
const delTarget = ref(null)
const deleting = ref(false)

const STATUS_FILTERS = [
  { value: '', label: '全部' },
  { value: 'in_progress', label: '进行中' },
  { value: 'completed', label: '已完成' },
  { value: 'abandoned', label: '已作废' }
]

function remainingOf(it) {
  if (it.status !== 'in_progress' || it.session_elapsed_seconds == null) return null
  return Math.max(0, Math.round((40 * 60 - it.session_elapsed_seconds) / 60))
}

function onFilter(v) {
  if (statusFilter.value === v) return
  statusFilter.value = v
  page.value = 1
  load()
}

async function load() {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (statusFilter.value) params.status = statusFilter.value
    const { data } = await assessment.listSessions(params)
    items.value = data.items
    total.value = data.total
  } catch (e) {
    toast(errMsg(e, '历史加载失败'), 'error')
  } finally {
    loading.value = false
  }
}

async function confirmDelete() {
  const target = delTarget.value
  if (!target || deleting.value) return
  deleting.value = true
  try {
    await assessment.deleteSession(target.session_id)
    toast('已删除该测评记录')
    delTarget.value = null
    // 被删行所在页可能清空（如末页仅 1 行）——page 收缩由 UiPager 钳制，此处直接按现页重拉
    await load()
  } catch (e) {
    toast(errMsg(e, '删除失败，请稍后再试'), 'error')
  } finally {
    deleting.value = false
  }
}

onMounted(load)
</script>
