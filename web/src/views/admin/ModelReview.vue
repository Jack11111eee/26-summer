<template>
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
          <el-button :loading="aggregating" @click="onAggregate">重新聚合</el-button>
          <template v-if="editable">
            <el-button type="primary" :loading="saving" @click="onSave">保存草稿</el-button>
            <el-button type="success" :disabled="status === 'stalled'" :loading="confirming" @click="onConfirm">
              确认模型
            </el-button>
          </template>
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
          <el-button type="primary" :loading="aggregating" @click="onAggregate">重新聚合</el-button>
        </el-empty>
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
                v-for="item in groups[cat]"
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
                    :precision="1"
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
          <el-input-number v-model="addForm.weightPct" :min="0" :max="100" :precision="1" controls-position="right" />
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
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
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

let pollTimer = null
let pollCount = 0

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

// Σ 实时合计（百分比）
const sigmaPct = computed(() => {
  const sum = (model.value?.items || []).reduce((acc, it) => acc + (Number(it._weightPct) || 0), 0)
  return sum.toFixed(1)
})
const sigmaOk = computed(() => Math.abs(Number(sigmaPct.value) - 100) <= 0.5)

const statusLabel = computed(() => ({ draft: '草稿', stalled: '裁决滞留', confirmed: '已确认' }[status.value] || status.value))
const statusType = computed(() => ({ draft: 'info', stalled: 'danger', confirmed: 'success' }[status.value] || 'info'))

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
    _weightPct: Number(((it.weight ?? 0) * 100).toFixed(1))
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

// 轮询直到拿到模型（draft/stalled/confirmed 均可）
function startPoll() {
  stopPoll()
  pollCount = 0
  pollTimer = setInterval(async () => {
    pollCount += 1
    const got = await loadModel({ silent: true })
    if (got || pollCount >= 60) {
      stopPoll()
      aggregating.value = false
      retrying.value = false
      if (!got) ElMessage.warning('聚合超时，请稍后手动刷新')
    }
  }, 3000)
}
function stopPoll() {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
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
    startPoll()
  } catch (e) {
    retrying.value = false
    ElMessage.error(e.response?.data?.detail || '重试失败')
  }
}

function buildPayload() {
  return {
    ...model.value,
    items: model.value.items.map(({ _key, _weightPct, ...it }) => ({
      ...it,
      weight: Number(((Number(_weightPct) || 0) / 100).toFixed(4))
    }))
  }
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
  addVisible.value = false
  addForm.std_name = ''
  addForm.weightPct = 0
}

onMounted(() => loadModel())
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
.full {
  width: 100%;
}
</style>
