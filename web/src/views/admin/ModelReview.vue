<template>
  <AdminNav />
  <div class="page">
    <el-card shadow="never" class="panel">
      <!-- 页头 -->
      <div class="head">
        <div>
          <el-button text @click="$router.push(`/admin/positions/${positionId}`)">← 返回岗位详情</el-button>
          <h2 class="title">
            {{ model?.position_name || '模型审核' }}
            <span v-if="version" class="ver">v{{ version }}</span>
            <el-tag v-if="status" :type="statusType" size="small" class="ml8">{{ statusLabel }}</el-tag>
          </h2>
        </div>
        <div>
          <el-button :loading="aggregating" @click="onAggregate">{{ aggregateLabel }}</el-button>
          <template v-if="editable">
            <el-button type="primary" :loading="saving" @click="onSave">保存草稿</el-button>
            <el-button type="success" :disabled="status === 'stalled'" :loading="confirming" @click="onConfirm">
              确认模型
            </el-button>
          </template>
        </div>
      </div>

      <!-- 聚合进度（SSOT §8.4：进度条+双计数+当前项，任务生命周期与页面解耦） -->
      <div v-if="aggregating" class="agg-progress">
        <el-progress
          :percentage="aggPercent"
          :stroke-width="10"
          :status="aggStalled ? 'warning' : undefined"
        />
        <div class="agg-line">
          {{ progress.done ?? 0 }}/{{ progress.total ?? 0 }} 项 · 冲突裁决
          {{ progress.llm_done ?? 0 }}/{{ progress.llm_total ?? 0 }}
          <template v-if="progress.current_item"> · 当前：{{ progress.current_item }}</template>
        </div>
      </div>

      <!-- stalled 警示条 -->
      <el-alert
        v-if="status === 'stalled'"
        type="error"
        title="等级裁决失败滞留"
        description="部分能力项的等级由 LLM 裁决失败。可点击「重试 LLM」再次尝试，或直接编辑各项等级后保存草稿。"
        :closable="false"
        class="mb12"
      >
        <template #default>
          <el-button size="small" type="danger" plain :loading="retrying" @click="onRetry">重试 LLM</el-button>
          <span class="ml8 tip-text">手动定级：直接编辑各项等级后「保存草稿」</span>
        </template>
      </el-alert>

      <!-- 加载 / 空状态 -->
      <div v-if="loading" v-loading="true" class="empty-box" />
      <template v-else-if="!model">
        <el-empty description="该岗位暂无聚合模型">
          <el-button type="primary" :loading="aggregating" @click="onAggregate">{{ aggregateLabel }}</el-button>
        </el-empty>
        <!-- 聚合进行中空态也展示进度（首聚合往往从空态触发） -->
        <div v-if="aggregating" class="agg-progress">
          <el-progress
            :percentage="aggPercent"
            :stroke-width="10"
            :status="aggStalled ? 'warning' : undefined"
          />
          <div class="agg-line">
            {{ progress.done ?? 0 }}/{{ progress.total ?? 0 }} 项 · 冲突裁决
            {{ progress.llm_done ?? 0 }}/{{ progress.llm_total ?? 0 }}
            <template v-if="progress.current_item"> · 当前：{{ progress.current_item }}</template>
          </div>
        </div>
      </template>

      <!-- 主体：左右双栏 -->
      <div v-else class="cols">
        <!-- 左：证据面板 -->
        <div class="col-left">
          <template v-if="selected">
            <h3 class="sec-title">证据 · {{ selected.std_name }}</h3>
            <div class="occ">
              <el-tag size="small" effect="plain">出现率 r={{ pct(selected.occurrence?.r) }}%</el-tag>
              <el-tag size="small" effect="plain" class="ml8">必备率 req={{ pct(selected.occurrence?.req) }}%</el-tag>
              <!-- 条件 req 三组成数（SSOT §8.1 2026-09-07）：required JD 数 / 出现 JD 数 / 岗位 JD 总数；
                   旧模型无 occ 键时不显示（防御性处理） -->
              <el-tag v-if="selected.occurrence?.occ != null" size="small" effect="plain" class="ml8">
                必备/出现/总数 {{ Math.round((selected.occurrence?.req ?? 0) * (selected.occurrence?.occ ?? 0)) }}/{{ selected.occurrence.occ }}/{{ model?.jd_count ?? '—' }}
              </el-tag>
            </div>
            <div v-if="selected.level_reason" class="reason">
              <div class="reason-label">LLM 定级理由</div>
              <div class="reason-text">{{ selected.level_reason }}</div>
            </div>
            <div v-if="(selected.evidence || []).length" class="ev-list">
              <div v-for="(ev, i) in selected.evidence" :key="i" class="ev-item">
                <div class="ev-head">
                  <span class="ev-jd">{{ ev.jd_id }}</span>
                  <el-tag v-if="ev.level" size="small" type="info" effect="plain">Lv{{ ev.level }}</el-tag>
                </div>
                <div class="ev-text" v-html="highlight(ev.text, selected.std_name)"></div>
              </div>
            </div>
            <el-empty v-else description="暂无证据" :image-size="60" />
          </template>
          <el-empty v-else description="点击右侧能力项查看证据" :image-size="80" />
        </div>

        <!-- 右：模型树 -->
        <div class="col-right">
          <!-- Σ 校验指示 -->
          <div class="sigma">
            <span>权重合计 Σ = {{ sigmaPct }}%</span>
            <el-tag v-if="sigmaOk" type="success" size="small" class="ml8">✓ 100%</el-tag>
            <el-tag v-else type="danger" size="small" class="ml8">需为 100%（容差 0.5%）</el-tag>
          </div>

          <div v-for="cat in categoryOrder" :key="cat" class="cat-group">
            <template v-if="groups[cat]?.length">
              <div class="cat-head">{{ categoryLabel(cat) }}（{{ groups[cat].length }}）</div>
              <div
                v-for="item in pagedItems(cat)"
                :key="item._key"
                class="item-card"
                :class="{ active: selected === item }"
                @click="selected = item"
              >
                <!-- 第一行：标准名 + 删除 -->
                <div class="item-row">
                  <el-input
                    v-model="item.std_name"
                    size="small"
                    :disabled="readonly"
                    placeholder="能力标准名"
                    class="name-input"
                    @click.stop
                  />
                  <el-popconfirm v-if="!readonly" title="删除该能力项？" @confirm="onRemove(item)">
                    <template #reference>
                      <el-button size="small" text type="danger" @click.stop>✕</el-button>
                    </template>
                  </el-popconfirm>
                </div>
                <!-- 第二行：等级 / 重要性 / 权重 / 年限 / gate -->
                <div class="item-row meta-row" @click.stop>
                  <template v-if="item.gate === 1">
                    <el-tag size="small" type="warning" effect="plain">门槛项</el-tag>
                  </template>
                  <template v-else>
                    <span class="lbl">等级</span>
                    <el-select v-model="item.required_level" size="small" :disabled="readonly" class="w80">
                      <el-option v-for="l in [1, 2, 3, 4, 5]" :key="l" :label="`Lv${l}`" :value="l" />
                    </el-select>
                  </template>
                  <span class="lbl">重要性</span>
                  <el-select v-model="item.importance" size="small" :disabled="readonly" class="w96">
                    <el-option label="必备" value="required" />
                    <el-option label="优先" value="preferred" />
                    <el-option label="加分" value="plus" />
                  </el-select>
                  <span class="lbl">权重%</span>
                  <el-input-number
                    v-model="item._weightPct"
                    size="small"
                    :min="0"
                    :max="100"
                    :precision="2"
                    :step="1"
                    :disabled="readonly"
                    controls-position="right"
                    class="w110"
                  />
                  <template v-if="item.category === 'experience'">
                    <span class="lbl">年限</span>
                    <el-input-number
                      v-model="item.years"
                      size="small"
                      :min="0"
                      :precision="1"
                      :disabled="readonly"
                      controls-position="right"
                      class="w90"
                    />
                  </template>
                </div>
              </div>
              <el-pagination
                class="pager"
                v-model:current-page="catPages[cat]"
                v-model:page-size="catPageSize"
                :total="groups[cat].length"
                :page-sizes="[10, 20, 50, 100]"
                layout="total, sizes, prev, pager, next, jumper"
                @size-change="onSizeChange"
              />
            </template>
          </div>

          <el-button v-if="!readonly" class="add-btn" @click="addVisible = true">+ 添加能力项</el-button>
        </div>
      </div>
    </el-card>

    <!-- 新增能力项弹窗 -->
    <el-dialog v-model="addVisible" title="添加能力项" width="420px">
      <el-form label-width="80px">
        <el-form-item label="标准名">
          <el-input v-model="addForm.std_name" placeholder="如：Python 开发" />
        </el-form-item>
        <el-form-item label="类目">
          <el-select v-model="addForm.category" class="full">
            <el-option v-for="c in categoryOrder" :key="c" :label="categoryLabel(c)" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="等级">
          <el-select v-model="addForm.required_level" class="full">
            <el-option v-for="l in [1, 2, 3, 4, 5]" :key="l" :label="`Lv${l}`" :value="l" />
          </el-select>
        </el-form-item>
        <el-form-item label="重要性">
          <el-select v-model="addForm.importance" class="full">
            <el-option label="必备" value="required" />
            <el-option label="优先" value="preferred" />
            <el-option label="加分" value="plus" />
          </el-select>
        </el-form-item>
        <el-form-item label="权重%">
          <el-input-number v-model="addForm.weightPct" :min="0" :max="100" :precision="2" controls-position="right" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addVisible = false">取消</el-button>
        <el-button type="primary" @click="onAdd">添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import AdminNav from '../../components/AdminNav.vue'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../../api'

const route = useRoute()
const positionId = route.params.id

const loading = ref(false)
const saving = ref(false)
const confirming = ref(false)
const aggregating = ref(false)
const retrying = ref(false)

const modelId = ref(null)
const version = ref(null)
const status = ref('')
const model = ref(null) // {position_name, jd_count, category_weights, items}
const selected = ref(null)

const addVisible = ref(false)
const addForm = reactive({ std_name: '', category: 'hard_skill', required_level: 3, importance: 'required', weightPct: 0 })

const categoryOrder = ['hard_skill', 'soft_skill', 'experience', 'qualification']

// 分块分页：各类目独立页码，共用一个 page size（纯前端切片，数据仍整份本地编辑）
const catPages = reactive({ hard_skill: 1, soft_skill: 1, experience: 1, qualification: 1 })
const catPageSize = ref(20)

let pollTimer = null
// 心跳判停（SSOT §8.4）：记录上次进度签名，连续 ~100 轮（约 5 分钟）不变报停滞
// 但继续轮询（替换旧 3 分钟硬超时停轮询+误报「聚合超时」）
let lastHeartbeat = ''
let sameBeatRounds = 0
const HEARTBEAT_STALL_ROUNDS = 100

// 聚合任务进度行（SSOT §8.4 progress 端点）
const progress = ref({})
const aggStalled = ref(false)

// 进度条百分比（total=0 防除零 → 0%）
const aggPercent = computed(() => {
  const total = Number(progress.value?.total) || 0
  const done = Number(progress.value?.done) || 0
  if (total <= 0) return 0
  return Math.min(100, Math.round((done / total) * 100))
})

const readonly = computed(() => status.value === 'confirmed')
const editable = computed(() => status.value === 'draft' || status.value === 'stalled')

// 按类目分组（保持 items 原顺序）
const groups = computed(() => {
  const g = {}
  for (const c of categoryOrder) g[c] = []
  for (const it of model.value?.items || []) {
    ;(g[it.category] || (g[it.category] = [])).push(it)
  }
  return g
})

// 当前页切片（页码超界时收敛到最大页，仅取值不改状态）
function pagedItems(cat) {
  const list = groups.value[cat] || []
  const maxPage = Math.max(1, Math.ceil(list.length / catPageSize.value))
  const page = Math.min(catPages[cat], maxPage)
  return list.slice((page - 1) * catPageSize.value, page * catPageSize.value)
}

// size 变化时各类目页码重置为 1
function onSizeChange() {
  for (const c of categoryOrder) catPages[c] = 1
}

// 列表收缩（删除/重载）导致页码超界时收敛到最大页
watch(
  () => groups.value,
  (g) => {
    for (const c of categoryOrder) {
      const maxPage = Math.max(1, Math.ceil((g[c]?.length || 0) / catPageSize.value))
      if (catPages[c] > maxPage) catPages[c] = maxPage
    }
  }
)

// Σ 实时合计（百分比）
const sigmaPct = computed(() => {
  const sum = (model.value?.items || []).reduce((acc, it) => acc + (Number(it._weightPct) || 0), 0)
  return sum.toFixed(1)
})
const sigmaOk = computed(() => Math.abs(Number(sigmaPct.value) - 100) <= 0.5)

const statusLabel = computed(() => ({ draft: '草稿', stalled: '裁决滞留', confirmed: '已确认' }[status.value] || status.value))
const statusType = computed(() => ({ draft: 'info', stalled: 'danger', confirmed: 'success' }[status.value] || 'info'))
// 未聚合过（404 空态）→「开始聚合」；已有模型 →「重新聚合」
const aggregateLabel = computed(() => (model.value ? '重新聚合' : '开始聚合'))

function categoryLabel(c) {
  return { hard_skill: '硬技能', soft_skill: '软技能', experience: '经验', qualification: '门槛' }[c] || c
}

function pct(v) {
  if (v === null || v === undefined) return '—'
  const n = Number(v)
  return n <= 1 ? (n * 100).toFixed(0) : n.toFixed(0)
}

// 简单转义后高亮能力名
function highlight(text, name) {
  if (!text) return ''
  const esc = (s) => s.replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]))
  let out = esc(text)
  if (name) {
    const escName = esc(name).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    out = out.replace(new RegExp(escName, 'g'), (m) => `<mark>${m}</mark>`)
  }
  return out
}

// 给每个 item 挂 _key / _weightPct 辅助字段
function decorate(items) {
  return (items || []).map((it, i) => ({
    ...it,
    _key: `${it.std_name}_${i}_${Math.random().toString(36).slice(2, 8)}`,
    // 不做精度量化（显示精度交给输入框 precision），否则 Σ 与保存回写会引入舍入失真
    _weightPct: (it.weight ?? 0) * 100
  }))
}

async function loadModel({ silent = false } = {}) {
  if (!silent) loading.value = true
  try {
    const { data } = await api.get(`/admin/positions/${positionId}/model`)
    modelId.value = data.model_id
    version.value = data.version
    status.value = data.status
    model.value = { ...data.model, items: decorate(data.model?.items) }
    // 选中项刷新后保持
    if (selected.value) {
      selected.value =
        model.value.items.find((it) => it.std_name === selected.value.std_name) || model.value.items[0] || null
    } else {
      selected.value = model.value.items[0] || null
    }
    return true
  } catch (e) {
    if (e.response?.status === 404) {
      model.value = null
      status.value = ''
      return false
    }
    ElMessage.error(e.response?.data?.detail || '加载模型失败')
    return false
  } finally {
    loading.value = false
  }
}

// 轮询 progress 端点（SSOT §8.4：取代模型 404→200 二态轮询）。
// 404 = BackgroundTasks 尚未起跑插行（「启动中」）→ 继续轮询不报错；
// SUCCEEDED → 停轮询拉模型；FAILED → 停轮询报 error 并拉模型（stalled 模型
// 200，页面照常展示 stalled 态与恢复入口）；心跳停滞报疑似但继续轮询。
function startPoll() {
  stopPoll()
  lastHeartbeat = ''
  sameBeatRounds = 0
  pollTimer = setInterval(async () => {
    let task
    try {
      const { data } = await api.get(`/admin/positions/${positionId}/aggregate/progress`)
      task = data
    } catch (e) {
      if (e.response?.status === 404) return // 启动中：行还没插，下一轮再看
      return // 瞬时网络错误：不中断轮询（下一轮再试）
    }
    progress.value = task

    // 心跳判停：(done, llm_done, current_item) 签名连续 N 轮不变 → 疑似停滞
    const beat = `${task.done}|${task.llm_done}|${task.current_item}`
    if (beat === lastHeartbeat) {
      sameBeatRounds += 1
    } else {
      sameBeatRounds = 0
      lastHeartbeat = beat
    }
    aggStalled.value = sameBeatRounds >= HEARTBEAT_STALL_ROUNDS
    if (aggStalled.value && sameBeatRounds === HEARTBEAT_STALL_ROUNDS) {
      ElMessage.warning('聚合进度疑似停滞（约 5 分钟无变化），继续等待中…')
    }

    if (task.status === 'SUCCEEDED') {
      stopPoll()
      aggregating.value = false
      retrying.value = false
      await loadModel({ silent: true })
    } else if (task.status === 'FAILED') {
      stopPoll()
      aggregating.value = false
      retrying.value = false
      ElMessage.error(task.error || '聚合失败')
      await loadModel({ silent: true }) // stalled 模型 200，展示恢复入口
    }
  }, 3000)
}
function stopPoll() {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
}

async function checkAndClaim() {
  // 进页面先查一次 progress：仅最新行为 RUNNING 才认领（任务生命周期与页面
  // 组件解耦——离开页面不中断不报错，重进来接着看）；SUCCEEDED/FAILED/404
  // 都不认领、不弹旧失败 toast（旧失败弹 toast 是本工单要修的误报之二）
  try {
    const { data } = await api.get(`/admin/positions/${positionId}/aggregate/progress`)
    if (data.status === 'RUNNING') {
      aggregating.value = true
      startPoll()
    }
  } catch {
    // 404（无记录）或瞬时错误：不认领
  }
}

async function onAggregate() {
  aggregating.value = true
  try {
    await api.post(`/admin/positions/${positionId}/aggregate`)
    ElMessage.info('已触发聚合，请稍候…')
    startPoll()
  } catch (e) {
    aggregating.value = false
    ElMessage.error(e.response?.data?.detail || '触发聚合失败')
  }
}

async function onRetry() {
  retrying.value = true
  try {
    await api.post(`/admin/positions/${positionId}/retry-level`, { action: 'retry' })
    ElMessage.info('已重试 LLM 定级；亦可手动编辑等级后保存草稿')
    aggregating.value = true // retry 路径走同一套 progress 轮询
    startPoll()
  } catch (e) {
    retrying.value = false
    ElMessage.error(e.response?.data?.detail || '重试失败')
  }
}

function buildPayload() {
  const items = model.value.items.map(({ _key, _weightPct, ...it }) => ({
    ...it,
    weight: Number(((Number(_weightPct) || 0) / 100).toFixed(4))
  }))
  // 4 位小数 round 尾差由权重最大项吸收，保证 Σ 严格 = 1（镜像后端 _compute_weights；
  // 全 0（纯 gate 模型）时跳过，避免把 1.0 压给 gate 项）
  if (items.length) {
    const drift = Number((1 - items.reduce((acc, it) => acc + it.weight, 0)).toFixed(4))
    const maxIt = items.reduce((a, b) => (b.weight > a.weight ? b : a))
    if (drift && maxIt.weight > 0) {
      maxIt.weight = Number((maxIt.weight + drift).toFixed(4))
    }
  }
  return { ...model.value, items }
}

async function onSave() {
  if (!sigmaOk.value) {
    ElMessage.warning(`权重合计为 ${sigmaPct.value}%，需在 100% ±0.5% 内才能保存`)
    return
  }
  saving.value = true
  try {
    await api.put(`/admin/models/${modelId.value}`, buildPayload())
    ElMessage.success('草稿已保存')
    await loadModel({ silent: true })
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function onConfirm() {
  try {
    await ElMessageBox.confirm('确认后模型将不可再编辑，是否继续？', '确认模型', {
      type: 'warning',
      confirmButtonText: '确认',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  confirming.value = true
  try {
    const { data } = await api.post(`/admin/models/${modelId.value}/confirm`)
    status.value = data.status
    ElMessage.success(`模型已确认（v${data.version}）`)
    await loadModel({ silent: true })
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '确认失败')
  } finally {
    confirming.value = false
  }
}

function onRemove(item) {
  const items = model.value.items
  const idx = items.indexOf(item)
  if (idx >= 0) items.splice(idx, 1)
  if (selected.value === item) selected.value = items[0] || null
}

function onAdd() {
  if (!addForm.std_name.trim()) {
    ElMessage.warning('请填写标准名')
    return
  }
  const item = {
    std_name: addForm.std_name.trim(),
    category: addForm.category,
    required_level: addForm.category === 'qualification' ? null : addForm.required_level,
    importance: addForm.importance,
    weight: 0,
    years: addForm.category === 'experience' ? 0 : null,
    gate: addForm.category === 'qualification' ? 1 : 0,
    level_reason: '',
    occurrence: { r: 0, req: 0 },
    evidence: [],
    _key: `new_${Math.random().toString(36).slice(2, 10)}`,
    _weightPct: Number(addForm.weightPct) || 0
  }
  model.value.items.push(item)
  selected.value = item
  // 跳到新 item 所在页（push 到类目末尾，即最后一页），保证用户能立刻看到
  catPages[item.category] = Math.max(1, Math.ceil((groups.value[item.category] || []).length / catPageSize.value))
  addVisible.value = false
  addForm.std_name = ''
  addForm.weightPct = 0
}

onMounted(() => {
  ;(async () => {
    await loadModel()
    await checkAndClaim()
  })()
})
onBeforeUnmount(stopPoll)
</script>

<style scoped>
.page {
  padding: 24px;
}
.panel {
  max-width: 1280px;
  margin: 0 auto;
  border-radius: 12px;
}
.head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
}
.title {
  margin: 4px 0 0;
  color: #303133;
}
.ver {
  font-size: 14px;
  color: #909399;
  margin-left: 8px;
}
.ml8 {
  margin-left: 8px;
}
.mb12 {
  margin-bottom: 12px;
}
.tip-text {
  font-size: 12px;
  color: #909399;
}
.agg-progress {
  margin-bottom: 12px;
}
.agg-line {
  margin-top: 6px;
  font-size: 13px;
  color: #606266;
}
.empty-box {
  height: 200px;
}
.cols {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}
.col-left {
  flex: 0 0 38%;
  border-right: 1px solid #ebeef5;
  padding-right: 16px;
  min-height: 300px;
}
.col-right {
  flex: 1;
  min-width: 0;
}
.sec-title {
  margin: 0 0 8px;
  font-size: 15px;
  color: #303133;
}
.occ {
  margin-bottom: 12px;
}
.reason {
  background: #f5f7fa;
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 12px;
}
.reason-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}
.reason-text {
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
}
.ev-item {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 8px;
}
.ev-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.ev-jd {
  font-size: 12px;
  color: #909399;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
}
.ev-text {
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
}
.ev-text :deep(mark) {
  background: #fff3cd;
  color: inherit;
  padding: 0 1px;
  border-radius: 2px;
}
.sigma {
  margin-bottom: 12px;
  font-size: 14px;
  color: #606266;
}
.cat-head {
  font-size: 13px;
  font-weight: 600;
  color: #909399;
  margin: 12px 0 8px;
}
.item-card {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: border-color 0.15s;
}
.item-card:hover {
  border-color: #c6e2ff;
}
.item-card.active {
  border-color: #409eff;
  box-shadow: 0 0 0 1px #409eff inset;
}
.item-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.item-row + .item-row {
  margin-top: 8px;
}
.name-input {
  flex: 1;
}
.meta-row {
  flex-wrap: wrap;
}
.lbl {
  font-size: 12px;
  color: #909399;
}
.w80 {
  width: 80px;
}
.w96 {
  width: 96px;
}
.w110 {
  width: 110px;
}
.w90 {
  width: 90px;
}
.add-btn {
  width: 100%;
  margin-top: 8px;
  border-style: dashed;
}
.pager {
  margin-top: 12px;
  justify-content: flex-end;
}
.full {
  width: 100%;
}
</style>
