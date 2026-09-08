<template>
  <div>
    <header class="topbar">
      <div>
        <div class="topbar-title">能力<span>词典</span></div>
        <div class="topbar-meta">{{ total }} ENTRIES · LLM PENDING {{ llmPendingCount }}</div>
      </div>
      <div class="topbar-actions">
        <button class="btn" :disabled="loading" @click="load">刷新</button>
        <button class="btn primary" @click="openCreate">＋ 新增标准名</button>
      </div>
    </header>

    <!-- 筛选行 -->
    <div class="filters">
      <select v-model="filters.category" class="select" @change="resetAndLoad">
        <option value="">全部类目</option>
        <option v-for="(label, key) in CATEGORY_LABELS" :key="key" :value="key">{{ label }}</option>
      </select>
      <select v-model="filters.created_by" class="select" @change="resetAndLoad">
        <option value="">全部来源</option>
        <option value="llm_pending">LLM 待确认</option>
        <option value="human">人工确认</option>
      </select>
      <select v-model="filters.status" class="select" @change="resetAndLoad">
        <option value="">全部状态</option>
        <option value="active">启用</option>
        <option value="disabled">停用</option>
      </select>
      <input
        v-model="filters.q"
        class="input search"
        type="text"
        placeholder="搜索标准名或别名…"
        @keyup.enter="resetAndLoad"
      />
      <button class="btn" @click="resetAndLoad">搜索</button>
    </div>

    <section class="block n2">
      <div class="block-head">
        <span class="block-title">词条清单</span>
        <span class="block-cnt">{{ total }} 条</span>
      </div>
      <table>
        <thead>
          <tr>
            <th style="width: 13%">std_name</th><th style="width: 8%">category</th><th style="width: 19%">definition</th>
            <th style="width: 14%">aliases</th><th style="width: 12%">exclusions</th><th style="width: 7%">source</th><th style="width: 7%">status</th>
            <th style="width: 20%; text-align: right">action</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="it in items" :key="`${it.std_name}|${it.category}`">
            <td v-clip><span class="cell-main">{{ it.std_name }}</span></td>
            <td><span class="tag">{{ categoryLabel(it.category) }}</span></td>
            <td v-clip class="cell-sub">{{ it.definition || '—' }}</td>
            <td>
              <span v-for="a in it.aliases || []" :key="a" class="tag" style="margin: 1px 2px 1px 0">{{ a }}</span>
              <span v-if="!it.aliases?.length" class="cell-sub">—</span>
            </td>
            <td>
              <span v-for="x in it.exclusions || []" :key="x" class="tag tag-red" style="margin: 1px 2px 1px 0">{{ x }}</span>
              <span v-if="!it.exclusions?.length" class="cell-sub">—</span>
            </td>
            <td>
              <span v-if="it.created_by === 'llm_pending'" class="tag warm">待确认</span>
              <span v-else class="tag tag-solid">已确认</span>
            </td>
            <td>
              <span v-if="it.status === 'active'" class="tag">启用</span>
              <span v-else class="tag tag-red">停用</span>
            </td>
            <td>
              <div class="row-actions">
                <button class="row-btn" @click="openEdit(it)">编辑</button>
                <button class="row-btn" @click="openMerge(it)">合并</button>
                <button class="row-btn row-btn-danger" @click="askRemove(it)">删除</button>
              </div>
            </td>
          </tr>
          <tr v-if="!items.length && !loading"><td colspan="8" class="empty-row">无匹配词条</td></tr>
        </tbody>
      </table>
      <UiPager v-model:page="page" v-model:page-size="pageSize" :total="total" @change="load" />
    </section>

    <!-- 新增 / 编辑（编辑即确认：created_by→human） -->
    <UiDrawer v-if="editState.show" :title="`${editState.mode === 'create' ? '新增' : '编辑'}词条`" @close="editState.show = false">
      <template v-if="editState.mode === 'create'">
        <div class="field">
          <label class="field-label">标准名</label>
          <input v-model="editState.std_name" class="input" :class="{ invalid: editState.err && !editState.std_name.trim() }" type="text" />
        </div>
        <div class="field">
          <label class="field-label">类目</label>
          <select v-model="editState.category" class="select">
            <option v-for="(label, key) in CATEGORY_LABELS" :key="key" :value="key">{{ label }}</option>
          </select>
        </div>
      </template>
      <template v-else>
        <p class="field-hint" style="margin-bottom: 14px">
          编辑保存即视为人工确认（来源 → 已确认）。
        </p>
      </template>

      <div class="field">
        <label class="field-label">定义</label>
        <textarea v-model="editState.definition" class="textarea" rows="3" placeholder="该标准名的判定口径…" />
      </div>
      <div class="field">
        <label class="field-label">别名（逗号分隔）</label>
        <input v-model="editState.aliasesStr" class="input" type="text" placeholder="别名1, 别名2" />
        <span v-if="editState.err" class="field-error">{{ editState.err }}</span>
      </div>
      <div class="field">
        <label class="field-label">排除项（逗号分隔）</label>
        <input v-model="editState.exclusionsStr" class="input" type="text" placeholder="易混淆项…" />
      </div>
      <div class="modal-actions" style="justify-content: flex-start">
        <button class="btn primary" :disabled="saving" @click="saveEdit">{{ saving ? '保存中…' : '保存' }}</button>
        <button class="btn" @click="editState.show = false">取消</button>
      </div>
    </UiDrawer>

    <!-- 合并 -->
    <UiModal
      v-if="mergeState.show"
      title="合并词条"
      :sub="`将「${mergeState.from?.std_name}」并入下方目标词条`"
      @close="mergeState.show = false"
      @confirm="doMerge"
    >
      <div class="field">
        <label class="field-label">目标词条（同 ${categoryLabel(mergeState.from?.category)} 类目内筛选）</label>
        <input v-model="mergeState.q" class="input" type="text" placeholder="输入关键字过滤…" />
        <div style="max-height: 260px; overflow-y: auto; margin-top: 8px; border: 1px solid #e4e4e1; border-radius: 10px">
          <div
            v-for="c in mergeCandidates"
            :key="`${c.std_name}|${c.category}`"
            class="item-card"
            :class="{ sel: c.std_name === mergeState.to && c.category === mergeState.from?.category }"
            style="cursor: pointer; margin: 0; border-radius: 0; border-bottom: 1px solid #e4e4e1"
            @click="mergeState.to = c.std_name"
          >
            <span class="cell-main">{{ c.std_name }}</span>
            <span class="tag">{{ categoryLabel(c.category) }}</span>
          </div>
          <div v-if="!mergeCandidates.length" class="empty-row" style="padding: 14px">无候选</div>
        </div>
        <span v-if="mergeState.err" class="field-error">{{ mergeState.err }}</span>
      </div>
    </UiModal>

    <!-- 删除确认 -->
    <UiConfirm
      v-if="removeState.show"
      title="删除词条"
      :message="`确认删除「${removeState.it?.std_name}」？若仍被模型引用，将改为停用。`"
      confirm-text="删除"
      danger
      @close="removeState.show = false"
      @confirm="doRemove"
    />
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { adminDict, errMsg } from '../../api'
import { UiPager, UiDrawer, UiModal, UiConfirm, toast } from '../../components/ui'
import { CATEGORY_LABELS, categoryLabel } from '../../lib/labels'

const loading = ref(false)
const saving = ref(false)

const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)
const llmPendingCount = ref(0)

const filters = reactive({ category: '', created_by: '', status: '', q: '' })

const editState = reactive({
  show: false, mode: 'create', std_name: '', category: 'hard_skill',
  definition: '', aliasesStr: '', exclusionsStr: '', err: '',
  original: null
})
const mergeState = reactive({ show: false, from: null, to: '', q: '', err: '', pool: [] })
const removeState = reactive({ show: false, it: null })

const mergeCandidates = computed(() => {
  const from = mergeState.from
  if (!from) return []
  const q = mergeState.q.trim().toLowerCase()
  return mergeState.pool.filter(
    (c) => c.category === from.category
      && c.std_name !== from.std_name
      && (!q || c.std_name.toLowerCase().includes(q) || (c.aliases || []).some((a) => a.toLowerCase().includes(q)))
  )
})

async function load() {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (filters.category) params.category = filters.category
    if (filters.created_by) params.created_by = filters.created_by
    if (filters.status) params.status = filters.status
    if (filters.q.trim()) params.q = filters.q.trim()
    const { data } = await adminDict.list(params)
    items.value = data.items
    total.value = data.total
  } catch (e) {
    toast(errMsg(e, '词典加载失败'), 'error')
  } finally {
    loading.value = false
  }
}

// llm_pending 总数（页头 meta）
async function loadPendingCount() {
  try {
    const { data } = await adminDict.list({ page: 1, page_size: 1, created_by: 'llm_pending' })
    llmPendingCount.value = data.total
  } catch { /* ignore */ }
}

function resetAndLoad() {
  page.value = 1
  load()
}

// ---- 新增 / 编辑 ----
function parseList(str) {
  return str.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
}

function openCreate() {
  Object.assign(editState, {
    show: true, mode: 'create', std_name: '', category: 'hard_skill',
    definition: '', aliasesStr: '', exclusionsStr: '', err: '', original: null
  })
}

function openEdit(it) {
  Object.assign(editState, {
    show: true, mode: 'edit',
    std_name: it.std_name, category: it.category,
    definition: it.definition || '',
    aliasesStr: (it.aliases || []).join(', '),
    exclusionsStr: (it.exclusions || []).join(', '),
    err: '', original: it
  })
}

async function saveEdit() {
  if (saveGuard()) return
  saving.value = true
  editState.err = ''
  try {
    const body = {
      definition: editState.definition.trim(),
      aliases: parseList(editState.aliasesStr),
      exclusions: parseList(editState.exclusionsStr)
    }
    if (editState.mode === 'create') {
      await adminDict.create({
        std_name: editState.std_name.trim(), category: editState.category, ...body
      })
      toast('词条已新增')
    } else {
      // 编辑即确认（后端 created_by→human 语义）
      await adminDict.update(editState.original.std_name, editState.original.category, body)
      toast('词条已保存并确认')
    }
    editState.show = false
    await Promise.all([load(), loadPendingCount()])
  } catch (e) {
    editState.err = errMsg(e, '保存失败')
  } finally {
    saving.value = false
  }
}

function saveGuard() {
  if (editState.mode === 'create' && !editState.std_name.trim()) {
    editState.err = '标准名必填'
    return true
  }
  return false
}

// ---- 合并 ----
async function openMerge(it) {
  Object.assign(mergeState, { show: true, from: it, to: '', q: '', err: '', pool: [] })
  try {
    // 目标池：同类目全量（page_size 上限 100，超出仍可搜索过滤当前页——与联调版同口径）
    const { data } = await adminDict.list({ page: 1, page_size: 100, category: it.category })
    mergeState.pool = data.items
  } catch (e) {
    toast(errMsg(e, '候选加载失败'), 'error')
  }
}

async function doMerge() {
  if (!mergeState.to) {
    mergeState.err = '请选择目标词条'
    return
  }
  saving.value = true
  mergeState.err = ''
  try {
    const target = mergeState.pool.find(
      (c) => c.std_name === mergeState.to && c.category === mergeState.from.category
    )
    await adminDict.merge(
      { std_name: mergeState.from.std_name, category: mergeState.from.category },
      { std_name: target.std_name, category: target.category }
    )
    toast(`已将「${mergeState.from.std_name}」并入「${target.std_name}」`)
    mergeState.show = false
    await Promise.all([load(), loadPendingCount()])
  } catch (e) {
    mergeState.err = errMsg(e, '合并失败')
  } finally {
    saving.value = false
  }
}

// ---- 删除 ----
function askRemove(it) {
  removeState.it = it
  removeState.show = true
}

async function doRemove() {
  const it = removeState.it
  removeState.show = false
  try {
    const { data } = await adminDict.remove(it.std_name, it.category)
    if (data.status === 'disabled') {
      toast(`「${it.std_name}」已被模型引用，已停用未删除`)
    } else {
      toast(`「${it.std_name}」已删除`)
    }
    await Promise.all([load(), loadPendingCount()])
  } catch (e) {
    toast(errMsg(e, '删除失败'), 'error')
  }
}

load()
loadPendingCount()
</script>

<style scoped>
.item-card.sel { outline: 2px solid var(--ink-1); outline-offset: -1px; }
</style>
