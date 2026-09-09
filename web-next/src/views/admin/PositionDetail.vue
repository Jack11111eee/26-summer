<template>
  <div>
    <header class="topbar">
      <div>
        <div class="topbar-title">{{ positionName || '岗位详情' }}</div>
        <div class="topbar-meta">{{ jds.length }} JDS · {{ parsingCount }} PARSING</div>
      </div>
      <div class="topbar-actions">
        <button class="btn" @click="goBack">← 返回</button>
        <button class="btn" @click="goReview">模型审核</button>
        <button class="btn primary" @click="importState.show = true">＋ 导入 JD</button>
      </div>
    </header>

    <div v-if="loading && !loaded" class="loading">LOADING…</div>

    <template v-if="loaded">
      <section class="block n2">
        <div class="block-head">
          <span class="block-title">JD 清单</span>
          <span class="block-cnt">{{ jds.length }} 条</span>
        </div>
        <table>
          <thead>
            <tr>
              <th style="width: 34%">职位标题</th><th style="width: 16%">公司</th><th style="width: 10%">来源</th><th style="width: 12%">状态</th>
              <th style="width: 13%">创建时间</th><th style="width: 15%">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="j in jds" :key="j.jd_id">
              <td v-clip><span class="cell-main">{{ j.job_title || '（解析中…）' }}</span></td>
              <td v-clip>{{ j.company || '—' }}</td>
              <td>{{ j.source_type || '—' }}</td>
              <td>
                <span v-if="j.status === 'parsed'" class="tag tag-solid">PARSED</span>
                <span v-else-if="j.status === 'failed'" class="tag tag-red">FAILED</span>
                <span v-else-if="j.status === 'imported'" class="tag">IMPORTED</span>
                <span v-else class="tag warm">PARSING</span>
              </td>
              <td>{{ formatTime(j.created_at) }}</td>
              <td>
                <div class="row-actions">
                  <button class="row-btn" @click="openArchive(j)">工序留档</button>
                  <button v-if="j.status === 'failed'" class="row-btn row-btn-solid" :disabled="acting" @click="reparse(j)">重新解析</button>
                </div>
              </td>
            </tr>
            <tr v-if="!jds.length"><td colspan="6" class="empty-row">尚无 JD，点击右上角「＋ 导入 JD」</td></tr>
          </tbody>
        </table>
      </section>
    </template>

    <!-- 导入 modal：粘贴 / JSONL 文件 -->
    <UiModal
      v-if="importState.show"
      title="导入 JD"
      sub="导入后异步解析并自动归岗，无需选择岗位"
      wide
      @close="closeImport"
    >
      <div class="tabs">
        <button type="button" class="tab" :class="{ active: importState.mode === 'paste' }" @click="importState.mode = 'paste'">粘贴文本</button>
        <button type="button" class="tab" :class="{ active: importState.mode === 'file' }" @click="importState.mode = 'file'">JSONL 批量</button>
      </div>

      <template v-if="importState.mode === 'paste'">
        <div class="field">
          <label class="field-label">JD 原文</label>
          <textarea v-model="importState.jdText" class="textarea" rows="7" placeholder="粘贴 JD 全文…" />
        </div>
        <div class="field">
          <label class="field-label">公司（可选）</label>
          <input v-model="importState.company" class="input" type="text" />
        </div>
      </template>

      <template v-else>
        <div class="field">
          <label class="field-label">JSONL 文件</label>
          <input class="input" type="file" accept=".jsonl,.txt" @change="onFilePick" />
          <span class="field-hint">每行 {job_title?, company?, jd_text}；上限 500 行</span>
        </div>
        <p v-if="importState.fileName" class="field-hint">已选择：{{ importState.fileName }}</p>
      </template>

      <template #actions>
        <button class="btn primary" :disabled="!canImport || importing" @click="doImport">
          {{ importing ? '导入中…' : '导入' }}
        </button>
      </template>
    </UiModal>

    <!-- 工序留档 drawer -->
    <UiDrawer v-if="archive.show" :title="`工序留档 · ${archive.jd?.job_title || archive.jd?.jd_id || ''}`" @close="archive.show = false">
      <template v-if="archive.data">
        <div v-if="archive.data.status === 'failed'" class="banner">
          <span>解析失败：{{ archive.data.error_msg || '未知错误' }}</span>
        </div>
        <div v-else-if="archive.data.status === 'parsing'" class="banner info">
          <span>解析进行中……</span>
        </div>

        <details class="fold" open>
          <summary><span class="caret">▶</span> ① JD 原文</summary>
          <div class="fold-body"><pre class="raw">{{ archive.data.raw_text || '—' }}</pre></div>
        </details>
        <details class="fold">
          <summary><span class="caret">▶</span> ② 清洗结果</summary>
          <div class="fold-body"><pre class="raw">{{ archive.data.cleaned_text || '—' }}</pre></div>
        </details>
        <details class="fold">
          <summary><span class="caret">▶</span> ③ raw_items（LLM 抽取）</summary>
          <div class="fold-body">
            <ItemTable v-if="archive.rawItems.length" :items="archive.rawItems" />
            <p v-else class="field-hint">无数据</p>
          </div>
        </details>
        <details class="fold">
          <summary><span class="caret">▶</span> ④ std_items（归一后）</summary>
          <div class="fold-body">
            <ItemTable v-if="archive.stdItems.length" :items="archive.stdItems" />
            <p v-else class="field-hint">无数据</p>
          </div>
        </details>
        <div v-if="archive.data.low_confidence" class="banner info">
          <span>低置信度归一结果（人工核对本条 std_items）</span>
        </div>
      </template>
      <div v-else class="loading">LOADING…</div>
    </UiDrawer>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { adminPositions, errMsg } from '../../api'
import { UiModal, UiDrawer, toast } from '../../components/ui'
import ItemTable from '../../components/ItemTable.vue'
import { formatTime } from '../../lib/labels'

const route = useRoute()
const router = useRouter()
const positionId = route.params.id

const loading = ref(false)
const loaded = ref(false)
const acting = ref(false)
const importing = ref(false)

const jds = ref([])
const positionName = ref('')

const importState = reactive({
  show: false, mode: 'paste', jdText: '', company: '',
  file: null, fileName: ''
})

const archive = reactive({ show: false, jd: null, data: null, rawItems: [], stdItems: [] })

const parsingCount = computed(() => jds.value.filter((j) => ['imported', 'parsing'].includes(j.status)).length)
const canImport = computed(() =>
  importState.mode === 'paste'
    ? importState.jdText.trim().length > 0
    : !!importState.file
)

let pollTimer = null

async function loadName() {
  try {
    const { data } = await adminPositions.positionOptions()
    const hit = data.find((o) => o.position_id === positionId)
    if (hit) positionName.value = hit.name
  } catch { /* 名称加载失败不阻断列表 */ }
}

async function loadJds() {
  const { data } = await adminPositions.listJds(positionId)
  jds.value = data
}

async function init() {
  loading.value = true
  try {
    await Promise.all([loadName(), loadJds()])
    loaded.value = true
    schedulePoll()
  } catch (e) {
    toast(errMsg(e, '岗位 JD 加载失败'), 'error')
  } finally {
    loading.value = false
  }
}

// 存在解析中条目时 5s 轮询，全部落定即停
function schedulePoll() {
  stopPoll()
  pollTimer = setInterval(async () => {
    if (parsingCount.value === 0) { stopPoll(); return }
    try { await loadJds() } catch { /* 下轮再试 */ }
  }, 5000)
}
function stopPoll() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

// ---- 导入 ----
function closeImport() {
  importState.show = false
  importState.jdText = ''
  importState.company = ''
  importState.file = null
  importState.fileName = ''
}

function onFilePick(e) {
  const f = e.target.files?.[0]
  importState.file = f || null
  importState.fileName = f?.name || ''
}

async function doImport() {
  if (importing.value) return
  importing.value = true
  try {
    if (importState.mode === 'paste') {
      await adminPositions.importJd(importState.jdText.trim(), importState.company.trim() || undefined)
      toast('已导入，后台解析中')
    } else {
      const { data } = await adminPositions.importJdFile(importState.file)
      toast(`已导入 ${data.imported} 条，后台解析中`)
    }
    closeImport()
    await loadJds()
    schedulePoll()
  } catch (e) {
    toast(errMsg(e, '导入失败'), 'error')
  } finally {
    importing.value = false
  }
}

// ---- 工序留档 ----
async function openArchive(j) {
  archive.jd = j
  archive.data = null
  archive.rawItems = []
  archive.stdItems = []
  archive.show = true
  try {
    const { data } = await adminPositions.jdDetail(j.jd_id)
    archive.data = data
    archive.rawItems = data.raw_items || []
    archive.stdItems = data.std_items || []
  } catch (e) {
    toast(errMsg(e, '留档加载失败'), 'error')
    archive.show = false
  }
}

async function reparse(j) {
  acting.value = true
  try {
    await adminPositions.reparseJd(j.jd_id)
    toast('已重新触发解析')
    await loadJds()
    schedulePoll()
  } catch (e) {
    toast(errMsg(e, '重新解析失败'), 'error')
  } finally {
    acting.value = false
  }
}

function goBack() {
  router.push('/admin/positions')
}
function goReview() {
  router.push(`/admin/positions/${positionId}/review`)
}

onBeforeUnmount(stopPoll)
init()
</script>
