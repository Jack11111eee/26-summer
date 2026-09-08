<template>
  <div class="page">
    <div class="report-body">
      <span class="back-link" @click="goBack">← 返回测评历史</span>

      <!-- 生成中 / 失败 -->
      <div v-if="phase === 'generating'" class="generating">
        <p class="serif">正在生成你的测评报告…</p>
        <p class="field-hint">通常需要数十秒；生成完成后本页会自动展示。</p>
        <span class="dot" style="margin: 18px auto 0; display: block; width: 7px; height: 7px"></span>
      </div>

      <div v-else-if="phase === 'failed'" class="generating">
        <p class="serif">报告生成失败</p>
        <p class="field-hint">{{ failText }}</p>
        <button class="btn-ghost" style="margin-top: 8px" @click="regenerate">重新生成</button>
      </div>

      <div v-else-if="phase === 'loading'" class="generating">
        <p class="serif">正在打开报告…</p>
      </div>

      <!-- 报告正文 -->
      <template v-if="phase === 'ready' && report">
        <div class="open-head serif" style="margin-bottom: 8px">
          <div class="kicker">REPORT · {{ report.position_name || '' }}</div>
          <h1>你的胜任力画像</h1>
          <p>基于本场访谈全部作答与资格核验生成。若有异议，可在明细项上提交反馈。</p>
        </div>

        <div class="rep-actions">
          <span v-if="report.report_status" class="tb-badge">{{ statusLabel(report.report_status) }}</span>
          <span v-if="report.provisional" class="chip amber">暂定稿（部分观测不足）</span>
          <button class="btn-ghost" @click="printReport">打印 / 导出 PDF</button>
          <button class="btn-ghost btn-theme" @click="toggleTheme">{{ isDark ? '日间' : '夜间' }}</button>
        </div>

        <!-- ① 总分 + 门槛 -->
        <section class="rep">
          <div class="rep-total">
            <div class="rep-score">{{ fmtScore(report.total_score) }}<small> / 100</small></div>
            <div class="rep-chips">
              <span v-if="report.gate_passed" class="tb-badge">门槛全部通过</span>
              <span v-else class="chip amber">存在未过门槛项</span>
              <span class="tb-badge">{{ report.report_id }}</span>
            </div>
          </div>

          <table v-if="(report.gate_details || []).length" class="rep-table">
            <thead>
              <tr><th>门槛项</th><th>结果</th><th>说明</th></tr>
            </thead>
            <tbody>
              <template v-for="(grp, i) in gateGroups" :key="i">
                <!-- 同 facet 多 item 折叠为一行（SSOT §16.1 报告折叠）；无 facet 的项各占一行 -->
                <tr v-if="grp.items.length > 1">
                  <td>
                    <b>{{ facetLabel(grp.key) }}</b>
                    <div class="gate-sub" v-for="g in grp.items" :key="g.item_id">
                      <span :class="g.passed ? 'ok' : 'no'">{{ g.passed ? '✓' : '✗' }}</span> {{ g.std_name }}
                    </div>
                  </td>
                  <td>
                    <span v-if="grp.allPassed" class="chip">通过</span>
                    <span v-else class="chip amber">未通过</span>
                  </td>
                  <td class="cell-sub" style="color: var(--ink-3)">{{ grp.reasons.join('；') }}</td>
                </tr>
                <tr v-else v-for="g in grp.items" :key="g.item_id">
                  <td>{{ g.std_name }}</td>
                  <td>
                    <span v-if="g.passed" class="chip">通过</span>
                    <span v-else class="chip amber">未通过</span>
                  </td>
                  <td class="cell-sub" style="color: var(--ink-3)">{{ g.reason }}</td>
                </tr>
              </template>
            </tbody>
          </table>
        </section>

        <hr class="divider" />

        <!-- ② 雷达 -->
        <section v-if="radarIndicators.length" class="rep">
          <div class="rep-kicker">RADAR</div>
          <div class="rep-title serif">要求 vs 你的表现</div>
          <div class="radar-box">
            <svg :width="RADAR_W" :height="RADAR_H" :viewBox="`0 0 ${RADAR_W} ${RADAR_H}`" role="img" aria-label="能力雷达图">
              <!-- 网格环 -->
              <polygon
                v-for="ring in [1, 2, 3, 4]"
                :key="`ring-${ring}`"
                :points="ringPoints(ring / 4)"
                fill="none"
                stroke="var(--line)"
                stroke-width="1"
              />
              <!-- 轴 -->
              <line
                v-for="(p, i) in axisPoints"
                :key="`axis-${i}`"
                :x1="CX" :y1="CY" :x2="p.x" :y2="p.y"
                stroke="var(--line)"
                stroke-width="1"
              />
              <!-- 要求轮廓 -->
              <polygon :points="requiredPoints" fill="none" stroke="var(--ink-3)" stroke-width="1.6" stroke-dasharray="5 4" />
              <!-- 实际表现 -->
              <polygon :points="actualPoints" :fill="actualFill" stroke="var(--accent)" stroke-width="1.6" />
              <!-- 顶点标签 -->
              <text
                v-for="(p, i) in axisPoints"
                :key="`lab-${i}`"
                :x="p.x + (p.x > CX + 4 ? 6 : p.x < CX - 4 ? -6 : 0)"
                :y="p.y + (p.y > CY + 4 ? 12 : p.y < CY - 4 ? -6 : 4)"
                :text-anchor="p.x > CX + 4 ? 'start' : p.x < CX - 4 ? 'end' : 'middle'"
              >{{ radarIndicators[i]?.label }}</text>
            </svg>
          </div>
          <div class="radar-legend">
            <span><i style="background: var(--ink-3)"></i>岗位要求</span>
            <span><i style="background: var(--accent)"></i>你的表现{{ hasImputed ? '（虚项为补算）' : '' }}</span>
          </div>
        </section>

        <!-- ③ 逐项明细 -->
        <section class="rep">
          <div class="rep-kicker">DETAILS</div>
          <div class="rep-title serif">能力项明细</div>

          <table class="rep-table">
            <thead>
              <tr><th>能力项</th><th>要求</th><th>表现</th><th>差距</th><th class="num">权重</th><th class="num">得分</th><th style="text-align:right">action</th></tr>
            </thead>
            <tbody>
              <tr v-for="it in report.item_details || []" :key="it.item_id">
                <td>
                  {{ it.std_name }}
                  <span v-if="it.gate" class="chip amber" style="margin-left: 4px">门槛</span>
                  <span v-if="it.imputed" class="tb-badge" style="margin-left: 4px">补算</span>
                  <span v-if="it.no_data" class="tb-badge" style="margin-left: 4px">无观测</span>
                </td>
                <td>{{ it.required_level ? `Lv${it.required_level}` : '—' }}</td>
                <td>{{ it.actual_level ? `Lv${it.actual_level}` : '—' }}</td>
                <td>
                  <span v-if="it.gap == null">—</span>
                  <span v-else-if="it.gap >= 0" class="gap-pos">+{{ it.gap }}</span>
                  <span v-else class="gap-neg">{{ it.gap }}</span>
                </td>
                <td class="num">{{ pct(it.weight) }}</td>
                <td class="num">{{ fmtScore(it.score) }}</td>
                <td style="text-align: right">
                  <button class="fb-btn" :disabled="feedbackDone.has(it.item_id)" @click="openFeedback(it)">
                    {{ feedbackDone.has(it.item_id) ? '已反馈' : '异议' }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>

          <!-- 覆盖率条 -->
          <div v-if="coverage" class="coverage-bar">
            <span>观测 <b>{{ coverage.observed_count ?? 0 }}</b></span>
            <span>可测 <b>{{ coverage.total_measureable ?? 0 }}</b></span>
            <span>补算 <b>{{ coverage.imputed_count ?? 0 }}</b></span>
            <span>覆盖率 <b>{{ Math.round((coverage.coverage_ratio ?? 0) * 100) }}%</b></span>
            <span v-if="missingReasonText" style="flex-basis: 100%; color: var(--ink-3)">{{ missingReasonText }}</span>
          </div>
        </section>

        <!-- ④ 优势 / 短板 -->
        <section class="rep">
          <div class="rep-kicker">SUMMARY</div>
          <div class="rep-title serif">优势与短板</div>

          <div class="rep-duo">
            <div class="paper-card">
              <h4>优势项</h4>
              <ul>
                <li v-for="s in report.strengths || []" :key="s.item_id">
                  <span>{{ s.std_name }}</span>
                  <span class="w">{{ s.gap != null && s.gap >= 0 ? `+${s.gap}` : s.gap }} · {{ pct(s.weight) }}</span>
                </li>
                <li v-if="!(report.strengths || []).length" class="field-hint">（无明显优势项）</li>
              </ul>
            </div>
            <div class="paper-card">
              <h4>短板项</h4>
              <ul>
                <li v-for="w in report.weaknesses || []" :key="w.item_id">
                  <span>{{ w.std_name }}</span>
                  <span class="w">{{ w.gap }} · {{ pct(w.weight) }}</span>
                </li>
                <li v-if="!(report.weaknesses || []).length" class="field-hint">（无明显短板项）</li>
              </ul>
            </div>
          </div>

          <div v-if="report.strengths_text" class="rep-quote serif">{{ report.strengths_text }}</div>
          <div v-if="report.weaknesses_text" class="rep-quote serif">{{ report.weaknesses_text }}</div>
          <div v-if="report.suggestions_text" class="rep-quote serif" style="border-left-color: var(--accent)">{{ report.suggestions_text }}</div>
        </section>

        <!-- ⑤ 逐题回顾 -->
        <section v-if="(report.question_reviews || []).length" class="rep">
          <div class="rep-kicker">REVIEW</div>
          <div class="rep-title serif">逐题回顾</div>

          <details v-for="(q, i) in report.question_reviews" :key="q.question_id || i" class="rep-fold">
            <summary><span class="no">{{ pad2(i + 1) }}</span> {{ brief(q.stem, 34) }}</summary>
            <div class="body">
              <dl>
                <dt>题目</dt><dd>{{ q.stem }}</dd>
                <dt>我的回答</dt><dd>{{ q.answer || '（未作答）' }}</dd>
                <dt v-if="q.evidence_quote">证据摘录</dt><dd v-if="q.evidence_quote">{{ q.evidence_quote }}</dd>
                <dt>评分依据</dt><dd>{{ q.reason || '—' }}</dd>
                <dt>过程分 → 终评分</dt>
                <dd>{{ q.score_live ?? '—' }} → {{ q.score_final ?? '—' }}<span v-if="q.std_name">（{{ q.std_name }}）</span></dd>
              </dl>
            </div>
          </details>
        </section>
      </template>
    </div>

    <!-- 异议 modal -->
    <div v-if="fbState.show" class="overlay" @click.self="fbState.show = false">
      <div class="modal">
        <div class="modal-title">提交异议</div>
        <div class="modal-sub">针对「{{ fbState.item?.std_name }}」的评分提出你的补充说明</div>
        <div class="field">
          <textarea v-model="fbState.text" class="textarea" rows="4" placeholder="例如：该题我的实际经历是……（补充事实性说明）" />
          <span v-if="fbState.err" class="field-error">{{ fbState.err }}</span>
          <span class="field-hint">异议将进入人工复核队列，不直接改变分数。</span>
        </div>
        <div class="modal-actions">
          <button class="btn-ghost" @click="fbState.show = false">取消</button>
          <button class="send" style="border: 0; cursor: pointer" :disabled="fbState.submitting || !fbState.text.trim()" @click="submitFeedback">
            {{ fbState.submitting ? '提交中…' : '提交' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
// 报告页：bootstrap（GET by-session；404→POST 触发→3s 轮询，上限 40）→ 五段渲染。
// 雷达为手写 SVG（required 虚线轮廓 vs actual 填充），无外部图表依赖。
import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { assessment, errMsg } from '../../api'
import { toast } from '../../components/ui'
import { useTheme } from '../../lib/theme'
import { pct, SCORE_STATE_LABELS } from '../../lib/labels'

const route = useRoute()
const router = useRouter()
const { theme, toggle: toggleTheme } = useTheme()
const isDark = computed(() => theme.value === 'dark')

const sessionId = route.params.session_id

const phase = ref('loading') // loading | generating | ready | failed
const report = ref(null)
const failText = ref('')
const feedbackDone = ref(new Set())

const fbState = reactive({ show: false, item: null, text: '', err: '', submitting: false })

const POLL_MS = 3000
const MAX_POLLS = 40
let pollTimer = null
let polls = 0

// ---- 雷达几何 ----
const RADAR_W = 460
const RADAR_H = 380
const CX = RADAR_W / 2
const CY = (RADAR_H - 20) / 2
const R = 140
const MAX_AXES = 10

const radarIndicators = computed(() => {
  const inds = (report.value?.radar_data?.indicators || []).slice(0, MAX_AXES)
  return inds.map((it) => ({ ...it, label: brief(it.name, 8) }))
})
const axisPoints = computed(() =>
  radarIndicators.value.map((_, i) => {
    const n = radarIndicators.value.length || 1
    const angle = -Math.PI / 2 + (2 * Math.PI * i) / n
    return { x: CX + R * Math.cos(angle), y: CY + R * Math.sin(angle) }
  })
)
const hasImputed = computed(() => (report.value?.radar_data?.indicators || []).some((it) => it.imputed))
const actualFill = 'var(--accent-soft)'

function ringPoints(frac) {
  return axisPoints.value
    .map((p) => `${CX + (p.x - CX) * frac},${CY + (p.y - CY) * frac}`)
    .join(' ')
}
function seriesPoints(key) {
  const series = report.value?.radar_data?.[key] || []
  const n = Math.min(series.length, radarIndicators.value.length)
  const pts = []
  for (let i = 0; i < n; i++) {
    const v = Math.max(0, Math.min(5, Number(series[i]) || 0)) / 5
    const p = axisPoints.value[i] || { x: CX, y: CY }
    pts.push(`${CX + (p.x - CX) * v},${CY + (p.y - CY) * v}`)
  }
  return pts.join(' ')
}
const requiredPoints = computed(() => ringFromSeries('required'))
const actualPoints = computed(() => ringFromSeries('actual'))
function ringFromSeries(key) {
  return seriesPoints(key)
}

// ---- 文案 ----
function fmtScore(v) {
  if (v == null) return '—'
  return String(Math.round(Number(v) * 10) / 10)
}
function pad2(n) {
  return String(n).padStart(2, '0')
}
function brief(s, n) {
  const t = String(s ?? '').trim().replace(/\s+/g, ' ')
  return t.length > n ? `${t.slice(0, n)}…` : t
}
function statusLabel(s) {
  return { GENERATING: '生成中', PROVISIONAL: '暂定稿', READY: '已就绪', PUBLISHED: '已发布', FAILED: '生成失败' }[s] || s
}

const coverage = computed(() => report.value?.coverage || null)

// ---- gate 段 facet 折叠（SSOT §16.1）----
const FACET_LABELS = {
  education_degree: '学历要求',
  school_tier: '院校档次',
  english_level: '英语等级',
  number_range: '数值条件',
  major_group: '专业与资格项'
}
function facetLabel(key) {
  return FACET_LABELS[key] || '资格核验'
}
const gateGroups = computed(() => {
  const details = report.value?.gate_details || []
  const buckets = new Map()
  const order = []
  for (const g of details) {
    const key = g.facet_key || null
    if (!buckets.has(key)) {
      buckets.set(key, { key, items: [], reasons: [] })
      order.push(key)
    }
    const b = buckets.get(key)
    b.items.push(g)
    b.reasons.push(g.reason || '')
  }
  return order.map((k) => {
    const b = buckets.get(k)
    return { ...b, allPassed: b.items.every((g) => g.passed) }
  })
})
const missingReasonText = computed(() => {
  const mr = coverage.value?.missing_reasons
  if (!mr) return ''
  if (Array.isArray(mr)) {
    return mr.map((m) => SCORE_STATE_LABELS[m] || m).join('；')
  }
  if (typeof mr === 'object') {
    return Object.entries(mr)
      .map(([k, c]) => `${SCORE_STATE_LABELS[k] || k} × ${c}`)
      .join('；')
  }
  return String(mr)
})

// ---- 引导与轮询 ----
function stopPoll() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

async function bootstrap() {
  stopPoll()
  phase.value = 'loading'
  failText.value = ''
  try {
    const { data } = await assessment.getReportBySession(sessionId)
    if (data.report_status === 'GENERATING') {
      phase.value = 'generating'
      startPoll()
      return
    }
    if (data.report_status === 'FAILED') {
      phase.value = 'failed'
      failText.value = data.error || '生成失败（可点击重新生成）'
      return
    }
    report.value = data
    phase.value = 'ready'
  } catch (e) {
    if (e?.response?.status === 404) {
      // 未生成：触发（202）后轮询
      try {
        await assessment.generateReport(sessionId)
        phase.value = 'generating'
        startPoll()
      } catch (err) {
        const code = err?.response?.data?.detail?.error_code
        if (code === 'REPORT_GENERATING') {
          phase.value = 'generating'
          startPoll()
        } else if (code === 'REPORT_ALREADY_GENERATED') {
          // 极端时序：并发已生成 → 直接重取
          bootstrap()
        } else if (err?.response?.status === 409 && code === 'SESSION_NOT_COMPLETED') {
          phase.value = 'failed'
          failText.value = '会话尚未完成，暂不能生成报告'
        } else {
          phase.value = 'failed'
          failText.value = errMsg(err, '报告触发失败')
        }
      }
    } else {
      phase.value = 'failed'
      failText.value = errMsg(e, '报告加载失败')
    }
  }
}

// 重新生成：POST 才能触发后端超龄 GENERATING 接管 / FAILED 重生成（bootstrap 只 GET，会原样读回旧状态）。
async function regenerate() {
  stopPoll()
  try {
    await assessment.generateReport(sessionId)
    phase.value = 'generating'
    startPoll()
  } catch (err) {
    const code = err?.response?.data?.detail?.error_code
    if (err?.response?.status === 409 && code === 'REPORT_GENERATING') {
      // 真实在途（未超龄）→ 与在途状态合并，进入轮询
      phase.value = 'generating'
      startPoll()
    } else if (code === 'REPORT_ALREADY_GENERATED') {
      // 极端时序：并发已生成 → 直接重取
      bootstrap()
    } else if (err?.response?.status === 409 && code === 'SESSION_NOT_COMPLETED') {
      phase.value = 'failed'
      failText.value = '会话尚未完成，暂不能生成报告'
    } else {
      phase.value = 'failed'
      failText.value = errMsg(err, '重新生成失败')
    }
  }
}

function startPoll() {
  polls = 0
  pollTimer = setInterval(async () => {
    polls++
    if (polls > MAX_POLLS) {
      stopPoll()
      phase.value = 'failed'
      failText.value = '生成超时（超过 2 分钟），可点击重新生成'
      return
    }
    try {
      const { data } = await assessment.getReportBySession(sessionId)
      if (data.report_status === 'GENERATING') return
      stopPoll()
      if (data.report_status === 'FAILED') {
        phase.value = 'failed'
        failText.value = data.error || '生成失败'
        return
      }
      report.value = data
      phase.value = 'ready'
    } catch { /* 404（尚未写行）→ 继续轮询 */ }
  }, POLL_MS)
}

// ---- 异议 ----
function openFeedback(item) {
  fbState.item = item
  fbState.text = ''
  fbState.err = ''
  fbState.show = true
}

async function submitFeedback() {
  const text = fbState.text.trim()
  if (!text) {
    fbState.err = '请填写异议内容'
    return
  }
  fbState.submitting = true
  fbState.err = ''
  try {
    await assessment.submitFeedback(report.value.report_id, fbState.item.item_id, text)
    feedbackDone.value.add(fbState.item.item_id)
    fbState.show = false
    toast('异议已提交，将进入人工复核')
  } catch (e) {
    fbState.err = errMsg(e, '提交失败')
  } finally {
    fbState.submitting = false
  }
}

// ---- 操作 ----
function goBack() {
  // §12.6：完成测评后的「返回」落历史页（刚完成这场 + 全部过往，语义顺）
  router.push('/assessment/history')
}
function printReport() {
  window.print()
}

onBeforeUnmount(stopPoll)
bootstrap()
</script>
