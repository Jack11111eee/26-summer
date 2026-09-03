<template>
  <div class="grail">
    <!-- 通栏头 -->
    <header class="grail-head">
      <div class="gh-brand">
        <div class="gh-mark">测</div>
        <span class="gh-name">胜任力测评</span>
      </div>
      <div class="gh-divider"></div>
      <div class="gh-crumb">测评端 / <b>测评报告</b></div>
      <div class="gh-actions">
        <span class="gh-user">{{ auth.user?.username }}</span>
        <button class="btn btn-sm" @click="$router.push('/assessment/positions')">返回岗位列表</button>
      </div>
    </header>

    <!-- 三栏体 -->
    <div class="grail-body">
      <!-- 左栏：导航 -->
      <aside class="rail-left">
        <div class="rl-section">导航</div>
        <a class="nav-item" @click="$router.push('/assessment/positions')">
          <span class="icon">←</span> 返回岗位列表
        </a>
        <a class="nav-item active">
          <span class="icon">◈</span> 测评报告
        </a>
        <div class="rl-user">
          <div class="avatar">{{ (auth.user?.username || '？')[0] }}</div>
          <div>
            <div class="user-name">{{ auth.user?.username }}</div>
            <div class="user-role">候选人</div>
          </div>
        </div>
      </aside>

      <!-- 中栏：五段式报告 -->
      <main class="rail-center">
        <div class="rc-head">
          <div class="rc-title">测评报告</div>
          <div class="rc-meta">
            <span v-if="report">{{ report.position_name }}</span>
            <span v-if="report">完成于 {{ fmtTime(report.created_at) }}</span>
            <span class="mono">会话 {{ sessionId }}</span>
          </div>
        </div>

        <!-- 生成中 / 失败态 -->
        <div v-if="phase !== 'ready'" class="rr-card center-box" v-loading="phase === 'generating'"
             element-loading-text="报告生成中，请稍候...">
          <template v-if="phase === 'failed'">
            <div class="fail-text">报告生成超时或失败，请重试</div>
            <button class="btn btn-primary" @click="bootstrap">重新生成</button>
          </template>
        </div>

        <template v-else>
          <!-- ① 总分 + 门槛标签 -->
          <div class="rc-section">总分与门槛 <span class="cnt">SECTION 1/5</span></div>
          <div class="sigma" :class="{ bad: !report.gate_passed }">
            <div class="total-num num">{{ report.total_score }}</div>
            <div class="bar"><i :style="{ width: Math.min(report.total_score, 100) + '%' }"></i></div>
            <span class="tag" :class="report.gate_passed ? 'tag-green' : 'tag-red'">
              {{ report.gate_passed ? '门槛全部通过' : '有门槛未通过' }}
            </span>
          </div>
          <div v-if="report.gate_details?.length" class="table-wrap">
            <table>
              <thead>
                <tr><th>门槛项</th><th>是否通过</th><th>原因</th></tr>
              </thead>
              <tbody>
                <tr v-for="g in report.gate_details" :key="g.item_id">
                  <td class="cell-main">{{ g.std_name }}</td>
                  <td>
                    <span class="tag" :class="g.passed ? 'tag-green' : 'tag-red'">
                      {{ g.passed ? '通过' : '未通过' }}
                    </span>
                  </td>
                  <td class="cell-sub">{{ g.reason }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- ② 雷达图 required vs actual -->
          <div class="rc-section">能力雷达 <span class="cnt">SECTION 2/5</span></div>
          <div class="rr-card">
            <div v-if="report.radar_data?.indicators?.length" ref="radarEl" class="radar-box"></div>
            <div v-else class="aside-note">暂无可绘制的能力项数据</div>
          </div>

          <!-- ③ 逐项明细表 -->
          <div class="rc-section">逐项明细 <span class="cnt">SECTION 3/5 · {{ report.item_details?.length || 0 }} 项</span></div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>能力项</th><th>类目</th><th>要求</th><th>实际</th>
                  <th>差距</th><th>权重</th><th>得分</th><th>理由</th><th></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="it in report.item_details" :key="it.item_id">
                  <td>
                    <div class="cell-main">{{ it.std_name }}</div>
                    <div v-if="it.gate" class="cell-sub">门槛项</div>
                    <div v-else-if="it.no_data" class="cell-sub">未出题/未作答</div>
                  </td>
                  <td><span class="tag tag-grey">{{ it.category }}</span></td>
                  <td class="num">{{ it.required_level ?? '—' }}</td>
                  <td class="num">{{ it.actual_level ?? '—' }}</td>
                  <td class="num" :class="gapClass(it)">{{ fmtGap(it) }}</td>
                  <td class="num">{{ fmtWeight(it.weight) }}</td>
                  <td class="num">{{ it.score }}</td>
                  <td class="reason-cell">
                    <span v-if="it.gate" class="cell-sub">{{ it.gate_reason }}</span>
                    <span v-else class="cell-sub">{{ itemReason(it.item_id) || '—' }}</span>
                  </td>
                  <td>
                    <button
                      v-if="!it.gate && !it.no_data"
                      class="btn btn-sm btn-ghost"
                      :disabled="submittedItems.has(it.item_id)"
                      @click="openFeedback(it)"
                    >{{ submittedItems.has(it.item_id) ? '已提交' : '异议' }}</button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- ④ 优势与短板 -->
          <div class="rc-section">优势与短板 <span class="cnt">SECTION 4/5</span></div>
          <div class="sw-grid">
            <div class="rr-card sw-card sw-good">
              <div class="rr-title">优势</div>
              <div class="sw-text">{{ report.strengths_text || '（无）' }}</div>
            </div>
            <div class="rr-card sw-card sw-bad">
              <div class="rr-title">短板</div>
              <div class="sw-text">{{ report.weaknesses_text || '（无）' }}</div>
            </div>
          </div>
          <div v-if="report.suggestions_text" class="rr-card sugg-card">
            <div class="rr-title">发展建议</div>
            <div class="sw-text">{{ report.suggestions_text }}</div>
          </div>

          <!-- ⑤ 逐题回顾 -->
          <div class="rc-section">逐题回顾 <span class="cnt">SECTION 5/5 · {{ report.question_reviews?.length || 0 }} 题</span></div>
          <el-collapse v-if="report.question_reviews?.length" class="review-collapse">
            <el-collapse-item v-for="(q, i) in report.question_reviews" :key="q.question_id" :name="i">
              <template #title>
                <span class="q-title">
                  <span class="q-seq mono">Q{{ i + 1 }}</span>
                  <span class="q-std">{{ q.std_name }}</span>
                  <span class="tag" :class="scoreTagClass(q.score_live)">过程 {{ q.score_live ?? '—' }}</span>
                  <span class="tag" :class="scoreTagClass(q.score_final)">终局 {{ q.score_final ?? '—' }}</span>
                </span>
              </template>
              <div class="q-body">
                <div class="q-block">
                  <div class="rr-title">题面</div>
                  <div>{{ q.stem }}</div>
                </div>
                <div class="q-block">
                  <div class="rr-title">我的回答</div>
                  <div class="quote">{{ q.answer || '（无回答记录）' }}</div>
                </div>
                <div v-if="q.evidence_quote" class="q-block">
                  <div class="rr-title">评分证据</div>
                  <div class="quote">{{ q.evidence_quote }}</div>
                </div>
                <div v-if="q.reason" class="q-block">
                  <div class="rr-title">评分理由</div>
                  <div>{{ q.reason }}</div>
                </div>
              </div>
            </el-collapse-item>
          </el-collapse>
          <div v-else class="rr-card aside-note">本题评分数据尚未落库</div>
        </template>
      </main>

      <!-- 右栏：操作 -->
      <aside class="rail-right">
        <div class="rr-card">
          <div class="rr-title">操作</div>
          <div class="op-list">
            <button class="btn" :disabled="phase !== 'ready'" @click="onExport">导出 PDF</button>
            <button class="btn" :disabled="phase !== 'ready'" @click="scrollToItems">提交反馈</button>
            <button class="btn" @click="$router.push('/assessment/positions')">重新测评</button>
          </div>
        </div>
        <div class="rr-card" v-if="report">
          <div class="rr-title">报告信息</div>
          <div class="info-row"><span>报告编号</span><span class="mono">{{ report.report_id }}</span></div>
          <div class="info-row"><span>岗位</span><span>{{ report.position_name }}</span></div>
          <div class="info-row"><span>总分</span><span class="num">{{ report.total_score }}</span></div>
          <div class="info-row">
            <span>门槛</span>
            <span class="tag" :class="report.gate_passed ? 'tag-green' : 'tag-red'">
              {{ report.gate_passed ? '通过' : '未通过' }}
            </span>
          </div>
        </div>
        <div class="aside-note">对某能力项评分有疑问，可在逐项明细中点「异议」提交反馈，管理员会尽快处理。</div>
      </aside>
    </div>

    <!-- 异议对话框 -->
    <el-dialog v-model="fbVisible" title="提交异议" width="480px">
      <template v-if="fbItem">
        <div class="fb-info">
          <div class="info-row"><span>能力项</span><b>{{ fbItem.std_name }}</b></div>
          <div class="info-row"><span>要求等级</span><span class="num">{{ fbItem.required_level ?? '—' }}</span></div>
          <div class="info-row"><span>实际等级</span><span class="num">{{ fbItem.actual_level ?? '—' }}</span></div>
          <div class="info-row"><span>当前理由</span><span class="cell-sub">{{ itemReason(fbItem.item_id) || '—' }}</span></div>
        </div>
        <el-input
          v-model="fbText"
          type="textarea"
          :rows="4"
          placeholder="请说明您对该项评分的异议理由..."
        />
      </template>
      <template #footer>
        <button class="btn" @click="fbVisible = false">取消</button>
        <button class="btn btn-primary" :disabled="!fbText.trim() || fbSubmitting" @click="submitFeedback">
          {{ fbSubmitting ? '提交中...' : '提交异议' }}
        </button>
      </template>
    </el-dialog>

    <!-- 通栏脚 -->
    <footer class="grail-foot">
      <span>CF · 测评端</span>
      <div class="f-right"><span>候选人</span></div>
    </footer>
  </div>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import { assessment } from '../../api'
import { useAuthStore } from '../../stores/auth'

const route = useRoute()
const auth = useAuthStore()
const sessionId = route.params.session_id

const phase = ref('generating') // generating | ready | failed
const report = ref(null)
const radarEl = ref(null)
let radarChart = null
let pollTimer = null
let pollCount = 0
const MAX_POLLS = 40 // 40 × 3s = 2 分钟

// ---------- 异议 ----------
const fbVisible = ref(false)
const fbItem = ref(null)
const fbText = ref('')
const fbSubmitting = ref(false)
const submittedItems = reactive(new Set())

function openFeedback(item) {
  fbItem.value = item
  fbText.value = ''
  fbVisible.value = true
}

async function submitFeedback() {
  fbSubmitting.value = true
  try {
    await assessment.submitFeedback(report.value.report_id, fbItem.value.item_id, fbText.value.trim())
    submittedItems.add(fbItem.value.item_id)
    fbVisible.value = false
    ElMessage.success('异议已提交，管理员会尽快处理')
  } catch (e) {
    // WR-01：后端 409 detail 为 {error_code, message} 结构时取可读 message，避免 [object Object]
    const d = e.response?.data?.detail
    ElMessage.error(d?.message || d || '提交失败，请稍后重试')
  } finally {
    fbSubmitting.value = false
  }
}

// ---------- 展示辅助 ----------
function fmtTime(iso) {
  if (!iso) return ''
  return iso.replace('T', ' ').slice(0, 16)
}
function fmtGap(it) {
  if (it.gap == null) return '—'
  return it.gap > 0 ? `+${it.gap}` : `${it.gap}`
}
function gapClass(it) {
  if (it.gap == null) return ''
  return it.gap >= 0 ? 'gap-ok' : 'gap-bad'
}
function fmtWeight(w) {
  return w == null ? '—' : `${Math.round(w * 100)}%`
}
function scoreTagClass(s) {
  if (s == null) return 'tag-grey'
  if (s >= 4) return 'tag-green'
  if (s >= 3) return 'tag-amber'
  return 'tag-red'
}

// 明细行理由：question_reviews 未携带 item_id（07 §10.5 契约），按 std_name 反查首条带理由题目
function itemReason(itemId) {
  const reviews = report.value?.question_reviews || []
  const item = report.value?.item_details?.find((d) => d.item_id === itemId)
  if (!item) return ''
  const hit = reviews.find((q) => q.std_name === item.std_name && q.reason)
  return hit?.reason || ''
}

function scrollToItems() {
  document.querySelectorAll('.rc-section')[2]?.scrollIntoView({ behavior: 'smooth' })
}

function onExport() {
  window.print()
}

// ---------- 雷达图 ----------
function renderRadar() {
  if (!radarEl.value || !report.value?.radar_data?.indicators?.length) return
  if (!radarChart) radarChart = echarts.init(radarEl.value)
  const rd = report.value.radar_data
  radarChart.setOption({
    tooltip: {},
    legend: {
      data: ['要求等级', '实际等级'],
      bottom: 0,
      textStyle: { color: '#6f6e69', fontSize: 12 }
    },
    radar: {
      indicator: rd.indicators,
      radius: '65%',
      axisName: { color: '#37352f', fontSize: 12 },
      splitArea: { areaStyle: { color: ['#ffffff', '#f7f6f3'] } },
      splitLine: { lineStyle: { color: '#e9e9e7' } },
      axisLine: { lineStyle: { color: '#e9e9e7' } }
    },
    series: [{
      type: 'radar',
      data: [
        {
          value: rd.required,
          name: '要求等级',
          lineStyle: { color: '#9b9a97' },
          itemStyle: { color: '#9b9a97' },
          areaStyle: { color: 'rgba(155,154,151,0.15)' }
        },
        {
          value: rd.actual,
          name: '实际等级',
          lineStyle: { color: '#337ea9' },
          itemStyle: { color: '#337ea9' },
          areaStyle: { color: 'rgba(51,126,169,0.15)' }
        }
      ]
    }]
  })
}

function onResize() {
  radarChart?.resize()
}

// ---------- 异步生成 + 轮询（M3 模式） ----------
async function bootstrap() {
  stopPolling()
  phase.value = 'generating'
  // 1. 先查是否已有报告
  try {
    const { data } = await assessment.getReportBySession(sessionId)
    await onReportReady(data)
    return
  } catch (e) {
    if (e.response?.status !== 404) {
      phase.value = 'failed'
      return
    }
  }
  // 2. 触发异步生成
  try {
    await assessment.generateReport(sessionId)
  } catch (e) {
    if (e.response?.status !== 404) {
      // WR-01：409 detail 为 {error_code, message} 结构时取可读 message
      const d = e.response?.data?.detail
      ElMessage.error(d?.message || d || '触发报告生成失败')
    }
  }
  // 3. 轮询
  pollCount = 0
  pollTimer = setInterval(poll, 3000)
}

async function poll() {
  pollCount += 1
  try {
    const { data } = await assessment.getReportBySession(sessionId)
    stopPolling()
    await onReportReady(data)
  } catch (e) {
    if (e.response?.status !== 404) {
      stopPolling()
      phase.value = 'failed'
    } else if (pollCount >= MAX_POLLS) {
      stopPolling()
      phase.value = 'failed'
    }
  }
}

async function onReportReady(data) {
  report.value = data
  phase.value = 'ready'
  await nextTick()
  renderRadar()
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

onMounted(() => {
  bootstrap()
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  stopPolling()
  window.removeEventListener('resize', onResize)
  radarChart?.dispose()
  radarChart = null
})
</script>

<style scoped>
.gh-user {
  font-size: 13px;
  color: var(--ink-2);
  align-self: center;
}
.center-box {
  min-height: 320px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
}
.fail-text { color: var(--ink-2); font-size: 14px; }

/* 总分大字（spark-num 样式：mono 粗体读数） */
.total-num {
  font-family: var(--mono);
  font-size: 28px;
  font-weight: 700;
  color: var(--ink-1);
  min-width: 72px;
  text-align: center;
}

/* 雷达图容器 */
.radar-box {
  height: 400px;
  margin: 20px 0;
}

/* gap 颜色 */
.gap-ok { color: var(--green); font-weight: 600; }
.gap-bad { color: var(--red); font-weight: 600; }

.reason-cell { max-width: 260px; }

/* 优势/短板卡片 */
.sw-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.sw-card { border-top: 3px solid transparent; }
.sw-good { border-top-color: var(--green); }
.sw-bad { border-top-color: var(--red); }
.sw-text { font-size: 13px; line-height: 1.7; color: var(--ink-1); }
.sugg-card { margin-top: 12px; border-top: 3px solid var(--blue); }

/* 逐题回顾 */
.review-collapse {
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
  background: var(--panel);
}
.q-title {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
}
.q-seq { color: var(--ink-3); }
.q-std { font-weight: 500; margin-right: auto; }
.q-body { padding: 4px 8px 8px; }
.q-block { margin-bottom: 12px; }

/* 右栏操作 */
.op-list { display: flex; flex-direction: column; gap: 8px; }
.op-list .btn { justify-content: center; }
.info-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 4px 0;
  font-size: 13px;
  color: var(--ink-2);
}
.info-row b { color: var(--ink-1); font-weight: 600; }

.fb-info { margin-bottom: 12px; }

/* 左栏导航项可点 */
.nav-item { cursor: pointer; }

@media print {
  .rail-left, .rail-right, .grail-head, .grail-foot { display: none; }
}
</style>
