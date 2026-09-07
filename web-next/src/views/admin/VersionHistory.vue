<template>
  <div>
    <header class="topbar">
      <div>
        <div class="topbar-title">版本<span>历史</span></div>
        <div class="topbar-meta">{{ versions.length }} VERSIONS {{ positionName ? `· ${positionName}` : '' }}</div>
      </div>
      <div class="topbar-actions">
        <button class="btn" @click="goBack">← 返回</button>
      </div>
    </header>

    <div v-if="loading && !loaded" class="loading">LOADING…</div>

    <template v-if="loaded">
      <section class="block n2">
        <div class="block-head">
          <span class="block-title">模型版本</span>
        </div>
        <table>
          <thead>
            <tr><th>version</th><th>status</th><th>confirmed_by</th><th>confirmed_at</th><th>created_at</th><th style="text-align:right">action</th></tr>
          </thead>
          <tbody>
            <tr v-for="v in versions" :key="v.model_id">
              <td><span class="cell-main">v{{ v.version }}</span></td>
              <td>
                <span v-if="v.status === 'confirmed'" class="tag tag-solid">CONFIRMED</span>
                <span v-else-if="v.status === 'stalled'" class="tag tag-red">STALLED</span>
                <span v-else class="tag">DRAFT</span>
              </td>
              <td>{{ v.confirmed_by || '—' }}</td>
              <td>{{ formatTime(v.confirmed_at) }}</td>
              <td>{{ formatTime(v.created_at) }}</td>
              <td>
                <div class="row-actions">
                  <button
                    class="row-btn"
                    :class="{ 'row-btn-solid': v.model_id === baseId || v.model_id === compId }"
                    :disabled="!canCompare"
                    @click="pickBase(v)"
                  >设为基准</button>
                  <button
                    class="row-btn"
                    :disabled="v.model_id === baseId || !canCompare"
                    @click="pickComp(v)"
                  >设为对比</button>
                </div>
              </td>
            </tr>
            <tr v-if="!versions.length"><td colspan="6" class="empty-row">暂无版本</td></tr>
          </tbody>
        </table>
      </section>

      <!-- diff 面板 -->
      <section v-if="baseId && compId" class="block card">
        <div class="block-head">
          <span class="block-title">版本对比</span>
          <span class="block-cnt">v{{ compVersionNo }} 对比 v{{ baseVersionNo }}</span>
          <span class="block-cnt">{{ changes.length }} 处变更</span>
          <button class="block-more" style="border: 0; background: none; cursor: pointer" @click="swap">⇅ 交换</button>
        </div>

        <div v-if="diffLoading" class="loading">LOADING…</div>
        <template v-else>
          <div v-if="!changes.length" class="empty-row" style="padding: 24px 0; text-align: center; color: var(--ink-3)">两版本能力项完全一致</div>
          <div
            v-for="(c, i) in changes"
            :key="i"
            class="item-card"
            :style="{ borderLeft: `3px solid ${c.change === 'added' ? '#4c5b3f' : c.change === 'removed' ? '#a4463b' : '#8a5a00'}` }"
          >
            <div style="display: flex; gap: 10px; align-items: baseline; flex: 1; flex-wrap: wrap">
              <span class="cell-main">{{ c.std_name }}</span>
              <span class="tag">{{ categoryLabel(c.category) }}</span>
              <span v-if="c.change === 'added'" class="tag tag-solid">新增</span>
              <span v-else-if="c.change === 'removed'" class="tag tag-red">移除</span>
              <span v-else class="tag warm">字段变更</span>
            </div>
            <div v-if="c.change === 'field'" class="cell-sub" style="width: 100%">
              <div v-for="(d, j) in c.diffs" :key="j">
                {{ d.label }}：<span style="color: var(--ink-3)">{{ fmtDiffVal(d.field, d.old) }}</span>
                → <b>{{ fmtDiffVal(d.field, d.new) }}</b>
              </div>
            </div>
            <div v-else-if="c.change === 'added'" class="cell-sub" style="width: 100%">
              Lv{{ c.new?.required_level || '—' }} · {{ importanceLabel(c.new?.importance) }} · {{ pct(c.new?.weight) }}
            </div>
            <div v-else class="cell-sub" style="width: 100%">
              Lv{{ c.old?.required_level || '—' }} · {{ importanceLabel(c.old?.importance) }} · {{ pct(c.old?.weight) }}
            </div>
          </div>
        </template>
      </section>

      <p v-else class="field-hint" style="padding: 8px 2px">
        在上方版本表中选择两个版本（基准 + 对比）查看逐项 diff。
      </p>
    </template>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { adminModels, adminPositions, errMsg } from '../../api'
import { toast } from '../../components/ui'
import { categoryLabel, importanceLabel, pct, formatTime } from '../../lib/labels'

const route = useRoute()
const router = useRouter()
const positionId = route.params.id

const loading = ref(false)
const loaded = ref(false)
const versions = ref([])
const positionName = ref('')

const baseId = ref('')
const compId = ref('')
const changes = ref([])
const diffLoading = ref(false)

const canCompare = computed(() => versions.value.length >= 2)

const baseVersionNo = computed(() => versions.value.find((v) => v.model_id === baseId.value)?.version ?? '?')
const compVersionNo = computed(() => versions.value.find((v) => v.model_id === compId.value)?.version ?? '?')

async function init() {
  loading.value = true
  try {
    const [vRes, oRes] = await Promise.all([
      adminModels.listVersions(positionId),
      adminPositions.positionOptions()
    ])
    versions.value = vRes.data
    positionName.value = oRes.data.find((o) => o.position_id === positionId)?.name || ''
    loaded.value = true
  } catch (e) {
    toast(errMsg(e, '版本历史加载失败'), 'error')
  } finally {
    loading.value = false
  }
}

let diffToken = 0
async function loadDiff() {
  if (!baseId.value || !compId.value) return
  diffLoading.value = true
  changes.value = []
  const token = ++diffToken
  try {
    const { data } = await adminModels.diffModels(compId.value, baseId.value)
    if (token === diffToken) changes.value = data.changes || []
  } catch (e) {
    if (token === diffToken) toast(errMsg(e, 'diff 加载失败'), 'error')
  } finally {
    if (token === diffToken) diffLoading.value = false
  }
}

function pickBase(v) {
  if (v.model_id === compId.value) {
    toast('基准与对比不能是同一版本', 'warn')
    return
  }
  baseId.value = v.model_id
  loadDiff()
}

function pickComp(v) {
  if (v.model_id === baseId.value) {
    toast('基准与对比不能是同一版本', 'warn')
    return
  }
  compId.value = v.model_id
  loadDiff()
}

function swap() {
  ;[baseId.value, compId.value] = [compId.value, baseId.value]
  loadDiff()
}

const FIELD_FMT = {
  weight: (v) => pct(v),
  gate: (v) => (v ? '是' : '否'),
  required_level: (v) => (v ? `Lv${v}` : '—'),
  importance: (v) => importanceLabel(v),
  years: (v) => (v != null ? `${v} 年` : '—')
}
function fmtDiffVal(field, v) {
  return (FIELD_FMT[field] || ((x) => x ?? '—'))(v)
}

function goBack() {
  router.push(`/admin/positions/${positionId}/review`)
}

onBeforeUnmount(() => { diffToken++ })
init()
</script>
