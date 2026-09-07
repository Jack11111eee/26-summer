<template>
  <div>
    <header class="topbar">
      <div>
        <div class="topbar-title">{{ meta?.model?.position_name || '模型审核' }}<span> · 能力模型</span></div>
        <div class="topbar-meta">
          <template v-if="meta">
            MODEL v{{ meta.version }} · {{ meta.status?.toUpperCase() }} · {{ items.length }} 项
          </template>
          <template v-else>NO MODEL · 待聚合</template>
        </div>
      </div>
      <div class="topbar-actions">
        <button class="btn" @click="goBack">← 返回</button>
        <button class="btn" @click="goVersions">版本历史</button>
        <button
          v-if="meta"
          class="btn"
          :disabled="aggregating || !editable || saving"
          @click="startAggregate"
        >{{ reaggregateLabel }}</button>
        <button
          v-if="meta && editable"
          class="btn"
          :disabled="saving || !weightsOk"
          @click="saveDraft"
        >{{ saving ? '保存中…' : '保存草稿' }}</button>
        <button
          v-if="meta && editable"
          class="btn primary"
          :disabled="saving || !weightsOk"
          @click="confirmState.show = true"
        >确认模型</button>
      </div>
    </header>

    <!-- 聚合进度（SSOT §8.4：进度条+双计数+当前项，任务生命周期与页面解耦） -->
    <div v-if="aggregating" class="agg-progress">
      <div class="agg-bar" :class="{ stall: aggStalled }">
        <div class="agg-bar-fill" :style="{ width: aggPercent + '%' }"></div>
      </div>
      <div class="agg-line">
        {{ progress.done ?? 0 }}/{{ progress.total ?? 0 }} 项 · 冲突裁决
        {{ progress.llm_done ?? 0 }}/{{ progress.llm_total ?? 0 }}
        <template v-if="progress.current_item"> · 当前：{{ progress.current_item }}</template>
      </div>
    </div>

    <!-- stalled 横幅 -->
    <div v-if="meta?.status === 'stalled'" class="banner">
      <span class="grow">等级裁决失败滞留（stalled）——LLM 无法为部分能力项定级。</span>
      <button class="btn danger" :disabled="acting" @click="retryLevel">重试 LLM 聚合</button>
    </div>

    <div v-if="loading && !meta" class="loading">LOADING…</div>

    <!-- 空态：无模型 → 引导聚合 -->
    <section v-if="!loading && !meta" class="block card" style="text-align: center; padding: 44px 20px">
      <p style="font-size: 14px; font-weight: 600; margin-bottom: 6px">该岗位暂无胜任力模型</p>
      <p class="cell-sub" style="margin-bottom: 18px">导入足量 JD 后聚合生成草稿，经人工审核确认。</p>
      <button class="btn primary" :disabled="aggregating" @click="startAggregate">
        {{ aggregating ? '聚合中…（约需数十秒）' : '开始聚合' }}
      </button>
    </section>

    <template v-if="meta">
      <div class="cols">
        <!-- 左：evidence 证据面板 -->
        <aside class="col-side block card">
          <div class="block-head" style="margin-bottom: 10px">
            <span class="block-title">证据留档</span>
          </div>
          <template v-if="selected">
            <p class="cell-main" style="margin-bottom: 2px">{{ selected.std_name }}</p>
            <div style="margin-bottom: 10px">
              <span class="tag">{{ categoryLabel(selected.category) }}</span>
              <span v-if="selected.gate" class="tag tag-red">gate 门槛项</span>
            </div>
            <div v-if="occText(selected)" class="field-hint" style="margin-bottom: 8px">
              出现率：{{ occText(selected) }}
            </div>
            <p v-if="selected.level_reason" class="cell-sub" style="margin-bottom: 12px; line-height: 1.7">
              {{ selected.level_reason }}
            </p>
            <div v-for="(ev, i) in selectedEvidence" :key="i" class="cell-sub" style="padding: 6px 0; border-top: 1px solid rgba(38,38,42,.06); line-height: 1.65" v-html="ev"></div>
          </template>
          <p v-else class="cell-sub">在右侧选择一个能力项查看其 JD 证据摘录。</p>
        </aside>

        <!-- 右：四类目编辑区 -->
        <div>
          <section v-for="cat in CATEGORY_ORDER" :key="cat.key" class="block n2" style="margin-bottom: 14px">
            <div class="block-head">
              <span class="block-title">{{ cat.label }}</span>
              <span class="block-cnt">{{ catItems(cat.key).length }} 项 · Σ{{ catSigma(cat.key) }}</span>
              <button
                v-if="editable"
                class="block-more"
                style="border: 0; background: none; cursor: pointer"
                @click="openAdd(cat.key)"
              >＋ 新增</button>
              <span v-if="catPageSize(cat.key) < catItems(cat.key).length && catItems(cat.key).length > PAGE_SIZE" class="block-more" style="cursor: default">
                {{ catPageNo(cat.key) }}/{{ catMaxPage(cat.key) }} 页
              </span>
            </div>

            <template v-if="editable">
              <div v-for="it in pagedCatItems(cat.key)" :key="it._k" class="item-card" :class="{ sel: it === selected }" @click="selected = it">
                <input v-model="it.std_name" class="input name-input" :disabled="it.gate && it._lockName" placeholder="标准名" @click.stop />
                <select v-model="it.required_level" class="select mini.select">
                  <option v-if="it.gate" :value="null">—</option>
                  <option v-for="n in 5" :key="n" :value="n">Lv{{ n }}</option>
                </select>
                <select v-model="it.importance" class="select mini.select">
                  <option v-for="(label, value) in IMPORTANCE_LABELS" :key="value" :value="value">{{ label }}</option>
                </select>
                <div style="display: flex; align-items: center; gap: 4px">
                  <input
                    v-model.number="it._pct"
                    class="input mini"
                    style="width: 68px; text-align: right"
                    type="number" min="0" max="100" step="0.1"
                  />
                  <span class="field-hint">%</span>
                </div>
                <template v-if="it.category === 'experience'">
                  <div style="display: flex; align-items: center; gap: 4px">
                    <input v-model.number="it.years" class="input mini" style="width: 60px; text-align: right" type="number" min="0" step="0.5" />
                    <span class="field-hint">年</span>
                  </div>
                </template>
                <span v-if="it.gate" class="tag tag-red">gate</span>
                <button class="row-btn row-btn-danger" style="opacity: 1" @click.stop="removeItem(it)">删除</button>
              </div>
            </template>

            <template v-else>
              <table>
                <thead>
                  <tr><th style="width: 52%">std_name</th><th class="num" style="width: 10%">level</th><th style="width: 14%">importance</th><th class="num" style="width: 12%">weight</th><th class="num" style="width: 12%">years</th></tr>
                </thead>
                <tbody>
                  <tr v-for="it in catItems(cat.key)" :key="it._k" style="cursor: pointer" @click="selected = selected === it ? null : it" :class="{ selrow: selected === it }">
                    <td v-clip><span class="cell-main">{{ it.std_name }}</span> <span v-if="it.gate" class="tag tag-red">gate</span></td>
                    <td class="num">{{ it.required_level ? `Lv${it.required_level}` : '—' }}</td>
                    <td>{{ importanceLabel(it.importance) }}</td>
                    <td class="num">{{ pct(it.weight) }}</td>
                    <td class="num">{{ it.years ?? '—' }}</td>
                  </tr>
                  <tr v-if="!catItems(cat.key).length"><td :colspan="5" class="empty-row">暂无项</td></tr>
                </tbody>
              </table>
            </template>

            <!-- 类目内容前端分页 -->
            <UiPager
              v-if="editable && catItems(cat.key).length > PAGE_SIZE"
              v-model:page="catPages[cat.key].page"
              :page-size="PAGE_SIZE"
              :total="catItems(cat.key).length"
            />
          </section>

          <!-- Σ 校验条（仅编辑态） -->
          <div v-if="editable" class="sigma" :class="weightsOk ? 'ok' : 'bad'">
            <span>Σ 权重</span>
            <span class="num">{{ sigmaText }}</span>
            <span class="field-hint">{{ weightsHint }}</span>
            <span class="grow"></span>
            <button class="btn" :disabled="saving || !weightsOk" @click="saveDraft">{{ saving ? '保存中…' : '保存草稿' }}</button>
          </div>
        </div>
      </div>
    </template>

    <!-- 新增能力项 modal -->
    <UiModal
      v-if="addState.show"
      title="新增能力项"
      :sub="`加入类目「${categoryLabel(addState.category)}」`"
      @close="addState.show = false"
      @confirm="applyAdd"
    >
      <div class="field">
        <label class="field-label">标准名</label>
        <input v-model="addState.std_name" class="input" :class="{ invalid: addState.err }" type="text" placeholder="优先与能力词典对齐" />
        <span v-if="addState.err" class="field-error">{{ addState.err }}</span>
      </div>
      <div class="field">
        <label class="field-label">等级（可留空）</label>
        <select v-model="addState.required_level" class="select">
          <option :value="null">—</option>
          <option v-for="n in 5" :key="n" :value="n">Lv{{ n }}</option>
        </select>
      </div>
      <div class="field">
        <label class="field-label">权重 %</label>
        <input v-model.number="addState.pct" class="input" type="number" min="0" max="100" step="0.1" />
      </div>
    </UiModal>

    <!-- 确认模型 modal -->
    <UiModal
      v-if="confirmState.show"
      title="确认模型"
      sub="确认后进入题库生成（异步）"
      @close="confirmState.show = false"
      @confirm="doConfirm"
    >
      <p style="font-size: 13px; line-height: 1.8">
        确认将当前草稿（v{{ meta?.version }}，{{ items.length }} 项）定为该岗位的胜任力模型。
        确认后模型不可再编辑，系统将自动生成对应题库；生成期间该岗位暂不可开考。
      </p>
    </UiModal>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { adminModels, adminPositions, errMsg } from '../../api'
import { UiModal, UiPager, toast } from '../../components/ui'
import { CATEGORY_LABELS, IMPORTANCE_LABELS, categoryLabel, importanceLabel, pct } from '../../lib/labels'

const route = useRoute()
const router = useRouter()
const positionId = route.params.id

const PAGE_SIZE = 10
const CATEGORY_ORDER = [
  { key: 'hard_skill', label: '硬技能' },
  { key: 'soft_skill', label: '软技能' },
  { key: 'experience', label: '经验' },
  { key: 'qualification', label: '资格' }
]

const loading = ref(false)
const acting = ref(false)
const saving = ref(false)
const aggregating = ref(false)

const meta = ref(null)          // {model_id, version, status, model}
const items = ref([])           // 编辑中的项（含 _pct/_k 视图键）
const selected = ref(null)

const catPages = reactive(
  Object.fromEntries(CATEGORY_ORDER.map((c) => [c.key, { page: 1 }]))
)

const addState = reactive({ show: false, category: 'hard_skill', std_name: '', required_level: null, pct: 0, err: '' })
const confirmState = reactive({ show: false })

const editable = computed(() => ['draft', 'stalled'].includes(meta.value?.status))

const reaggregateLabel = computed(() =>
  meta.value?.status === 'stalled' ? '重新聚合（清 stall）' : '重新聚合'
)

// ---- Σ 权重 ----
const sigmaPct = computed(() => items.value.reduce((s, it) => s + (Number(it._pct) || 0), 0))
const sigmaText = computed(() => `${(Math.round(sigmaPct.value * 10) / 10).toFixed(1)}%`)
// 纯 gate 全零模型可 Σ=0 合法；否则须 100% ±0.5%（后端容差同口径）
const weightsOk = computed(() => {
  const allGate = items.value.length > 0 && items.value.every((it) => it.gate && !(Number(it._pct) > 0))
  if (allGate) return true
  if (!items.value.length) return false
  return Math.abs(sigmaPct.value - 100) <= 0.5
})
const weightsHint = computed(() => {
  if (!items.value.length) return '尚无能力项'
  return weightsOk.value ? '校验通过（保存时尾差并入最大项）' : '须为 100% ± 0.5%'
})

// ---- 类目视图 ----
function catItems(cat) {
  return items.value.filter((it) => it.category === cat)
}
function pagedCatItems(cat) {
  const all = catItems(cat)
  const start = (catPages[cat].page - 1) * PAGE_SIZE
  return all.slice(start, start + PAGE_SIZE)
}
function catMaxPage(cat) {
  return Math.max(1, Math.ceil(catItems(cat).length / PAGE_SIZE))
}
function catPageNo(cat) {
  return Math.min(catPages[cat].page, catMaxPage(cat))
}
function catPageSize(cat) {
  return Math.min(catPages[cat].page * PAGE_SIZE, catItems(cat).length)
}
function catSigma(cat) {
  const s = catItems(cat).reduce((acc, it) => acc + (Number(it._pct) || 0), 0)
  return `${(Math.round(s * 10) / 10).toFixed(1)}%`
}

// ---- 证据面板 ----
const selectedEvidence = computed(() => {
  const it = selected.value
  if (!it) return []
  const name = it.std_name || ''
  // 摘录文本先转义再高亮（XSS 防护：evidence 来自 LLM 产物）
  return (it.evidence || []).map((raw) => {
    const safe = String(raw)
      .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    if (!name) return safe
    const safeName = name.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    return safe.split(safeName).join(`<mark>${safeName}</mark>`)
  })
})

function occText(it) {
  const o = it.occurrence || {}
  if (o.r == null && o.req == null) return ''
  const rate = `${Math.round((o.r || 0) * 100)}% 岗位出现`
  // 条件 req 三组成数（SSOT §8.1）：required JD 数 = round(req × occ) / 出现 JD 数 = occ / 岗位 JD 总数 = 模型 jd_count；
  // 旧模型 occurrence 无 occ 键 → 降级只显示出现率（不出 NaN/undefined）
  if (o.occ == null) return rate
  const jdTotal = meta.value?.model?.jd_count
  return `${rate} · 必备 ${Math.round((o.req ?? 0) * o.occ)} / 出现 ${o.occ} / 岗位 ${jdTotal == null ? '—' : jdTotal}`
}

// ---- 数据 ----
let seq = 0
function normalizeItems(itemsIn) {
  return itemsIn.map((it) => ({
    ...it,
    _k: `it_${++seq}`,
    _pct: Math.round((it.weight || 0) * 10000) / 100,
    _lockName: false
  }))
}

async function loadModel() {
  loading.value = true
  try {
    const { data } = await adminModels.getModel(positionId)
    meta.value = data
    items.value = normalizeItems(data.model?.items || [])
    selected.value = items.value[0] || null
  } catch (e) {
    if (e?.response?.status === 404) {
      meta.value = null
      items.value = []
    } else {
      toast(errMsg(e, '模型加载失败'), 'error')
    }
  } finally {
    loading.value = false
  }
}

// ---- 聚合（progress 端点轮询，SSOT §8.4） ----
let aggTimer = null
const progress = ref({})       // 聚合任务进度行（progress 端点）
const aggStalled = ref(false)  // 心跳疑似停滞（只改观感，不停轮询）
// 心跳判停：(done, llm_done, current_item) 签名连续 ~100 轮（3s×100≈5 分钟）不变
// → toast 疑似停滞但继续轮询（不设硬超时——任务生命周期与页面解耦，死了有 FAILED 兜底）
let lastHeartbeat = ''
let sameBeatRounds = 0
const HEARTBEAT_STALL_ROUNDS = 100

// 进度条百分比（total=0 防除零 → 0%）
const aggPercent = computed(() => {
  const total = Number(progress.value?.total) || 0
  const done = Number(progress.value?.done) || 0
  if (total <= 0) return 0
  return Math.min(100, Math.round((done / total) * 100))
})

async function startAggregate() {
  if (aggregating.value) return
  aggregating.value = true
  toast('已触发聚合，进行中…')
  try {
    await adminModels.aggregate(positionId)
  } catch (e) {
    aggregating.value = false
    toast(errMsg(e, '聚合触发失败'), 'error')
    return
  }
  startAggPoll()
}

// 轮询 progress 端点（取代模型 404→200 二态轮询）：404 = 任务行尚未插（启动中）
// 继续轮询；SUCCEEDED → 停轮询拉模型；FAILED → 停轮询报错并拉模型（stalled 模型
// 200，页面照常展示 stalled 态与恢复入口）；RUNNING → 更新进度条。
function startAggPoll() {
  stopAggPoll()
  lastHeartbeat = ''
  sameBeatRounds = 0
  aggStalled.value = false
  progress.value = {}
  aggTimer = setInterval(async () => {
    let task
    try {
      const { data } = await adminModels.getAggregateProgress(positionId)
      task = data
    } catch {
      return // 404（启动中）或瞬时错误：下一轮再看
    }
    progress.value = task

    const beat = `${task.done}|${task.llm_done}|${task.current_item}`
    if (beat === lastHeartbeat) sameBeatRounds += 1
    else { sameBeatRounds = 0; lastHeartbeat = beat }
    aggStalled.value = sameBeatRounds >= HEARTBEAT_STALL_ROUNDS
    if (aggStalled.value && sameBeatRounds === HEARTBEAT_STALL_ROUNDS) {
      toast('聚合进度疑似停滞（约 5 分钟无变化），继续等待中…', 'warn')
    }

    if (task.status === 'SUCCEEDED') {
      stopAggPoll()
      aggregating.value = false
      await loadModel()
      toast(`聚合完成：v${meta.value?.version} · ${items.value.length} 项`)
    } else if (task.status === 'FAILED') {
      stopAggPoll()
      aggregating.value = false
      toast(task.error || '聚合失败', 'error')
      await loadModel() // stalled 模型 200，展示恢复入口
    }
  }, 3000)
}
function stopAggPoll() {
  if (aggTimer) { clearInterval(aggTimer); aggTimer = null }
}

// 进页面认领：仅最新任务行为 RUNNING 才接续进度显示并恢复轮询；
// SUCCEEDED/FAILED/404 都不认领、不弹旧失败 toast
async function claimRunning() {
  try {
    const { data } = await adminModels.getAggregateProgress(positionId)
    if (data.status === 'RUNNING') {
      aggregating.value = true
      startAggPoll()
    }
  } catch {
    // 404（无记录）或瞬时错误：不认领
  }
}

// ---- stalled 重试 ----
async function retryLevel() {
  acting.value = true
  try {
    await adminModels.retryLevel(positionId)
    toast('已重试 LLM 聚合')
    meta.value = null
    items.value = []
    // retry-level 端点已删除 stalled 模型并排队重跑，此处只接 progress 轮询
    // （不二次 POST aggregate，避免双触发竞态）
    aggregating.value = true
    startAggPoll()
  } catch (e) {
    toast(errMsg(e, '重试失败'), 'error')
  } finally {
    acting.value = false
  }
}

// ---- 编辑 ----
function openAdd(cat) {
  Object.assign(addState, { show: true, category: cat, std_name: '', required_level: null, pct: 0, err: '' })
}

function applyAdd() {
  const name = addState.std_name.trim()
  if (!name) {
    addState.err = '标准名必填'
    return
  }
  const dup = items.value.some((it) => it.std_name === name && it.category === addState.category)
  if (dup) {
    addState.err = `「${categoryLabel(addState.category)}」内已存在同名项`
    return
  }
  items.value.push({
    std_name: name,
    category: addState.category,
    required_level: addState.required_level,
    importance: 'preferred',
    weight: 0,
    years: null,
    gate: 0,
    level_reason: null,
    occurrence: {},
    evidence: [],
    _k: `it_${++seq}`,
    _pct: addState.pct || 0,
    _lockName: false
  })
  // 跳到新增项所在页
  const idx = catItems(addState.category).length - 1
  catPages[addState.category].page = Math.floor(idx / PAGE_SIZE) + 1
  addState.show = false
  toast('已新增（保存草稿后生效）')
}

function removeItem(it) {
  const i = items.value.indexOf(it)
  if (i !== -1) {
    items.value.splice(i, 1)
    if (selected.value === it) selected.value = items.value[0] || null
    // 当前页越界回退
    for (const c of CATEGORY_ORDER) {
      if (catPages[c.key].page > catMaxPage(c.key)) catPages[c.key].page = catMaxPage(c.key)
    }
  }
}

// 提交体：_pct → weight 分数（4 位小数），尾差并入最大权重项（Σ=1 对齐后端容差）
function buildPayload() {
  const out = items.value.map((it) => ({
    std_name: (it.std_name || '').trim(),
    category: it.category,
    weight: Math.round((Number(it._pct) || 0) / 100 * 10000) / 10000,
    required_level: it.gate ? it.required_level ?? null : it.required_level ?? null,
    importance: it.importance || null,
    years: it.years ?? null,
    gate: it.gate ? 1 : 0,
    level_reason: it.level_reason ?? null,
    occurrence: it.occurrence || {},
    evidence: it.evidence || []
  }))
  const total = out.reduce((s, it) => s + it.weight, 0)
  const allGate = out.length > 0 && out.every((it) => it.gate && it.weight === 0)
  if (out.length && !allGate && total > 0 && Math.abs(total - 1) > 1e-9) {
    const maxIdx = out.reduce((m, it, i) => (it.weight > out[m].weight ? i : m), 0)
    out[maxIdx].weight = Math.round((out[maxIdx].weight + (1 - total)) * 10000) / 10000
  }
  return out
}

async function saveDraft() {
  if (!weightsOk.value) return
  saving.value = true
  try {
    await adminModels.updateModel(meta.value.model_id, buildPayload())
    toast('草稿已保存')
    await loadModel()
  } catch (e) {
    toast(errMsg(e, '保存失败'), 'error')
  } finally {
    saving.value = false
  }
}

async function doConfirm() {
  confirmState.show = false
  saving.value = true
  try {
    // 与后端确认流对齐：先保存当前编辑（若有改动）再确认，减少「忘点保存」口误
    if (editable.value) {
      await adminModels.updateModel(meta.value.model_id, buildPayload())
    }
    const { data } = await adminModels.confirmModel(meta.value.model_id)
    toast(`模型已确认（v${data.version}），题库生成中`)
    await loadModel()
  } catch (e) {
    toast(errMsg(e, '确认失败'), 'error')
  } finally {
    saving.value = false
  }
}

function goBack() {
  router.push(`/admin/positions/${positionId}`)
}
function goVersions() {
  router.push(`/admin/positions/${positionId}/versions`)
}

// 先拉模型（判定空态/编辑态），再查 progress 认领 RUNNING 任务接续展示
loadModel().then(claimRunning)

// 任务生命周期与页面组件解耦：离开页面只停 UI 轮询，后端任务照跑
onBeforeUnmount(stopAggPoll)
</script>

<style scoped>
.item-card.sel { outline: 2px solid var(--ink-1); outline-offset: 1px; }
tr.selrow td { background: rgba(255, 255, 255, .75); }
select.mini.select { width: 92px; }
::v-deep(mark) { background: #ffe9b8; padding: 0 1px; border-radius: 2px; }
.agg-progress { margin-bottom: 20px; }
.agg-bar { height: 6px; border-radius: 3px; background: rgba(38,38,42,.08); overflow: hidden; }
.agg-bar-fill { height: 100%; border-radius: 3px; background: var(--ink-1); transition: width .3s ease; }
.agg-bar.stall .agg-bar-fill { background: #8a5a00; }
.agg-line { margin-top: 6px; font-size: 12px; color: var(--ink-3); }
</style>
