<template>
  <div class="page">
    <div class="report-body">
      <span class="back-link" @click="goBack">← 返回测评历史</span>

      <!-- 生成中 / 失败 -->
      <div v-if="phase === 'generating'" class="generating">
        <p class="serif">正在生成你的测评报告…</p>
        <!-- §十九：前台轮询到点只停本页刷新，后台仍在生成——提示切换，不伪称失败 -->
        <p v-if="!pollStopped" class="field-hint">通常需要数十秒；生成完成后本页会自动展示。</p>
        <p v-else class="field-hint">报告仍在生成中（后台任务未超时，服务端看门狗兜底 60 分钟，并非失败）。本页已暂停自动刷新，可稍后回到本页查看；生成完成后会自动展示结果。</p>
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

      <!-- 报告正文（§三 固定顺序：顶部结果摘要 → Radar → Summary → Review → Details） -->
      <template v-if="phase === 'ready' && report">
        <div class="open-head serif" style="margin-bottom: 8px">
          <div class="kicker">REPORT · {{ report.position_name || '' }}</div>
          <h1>你的胜任力画像</h1>
          <p>基于本场访谈全部作答与资格核验生成。若有异议，可在明细项上提交反馈。</p>
        </div>

        <div class="rep-actions">
          <button class="btn-ghost" @click="printReport">打印 / 导出 PDF</button>
          <button class="btn-ghost btn-theme" @click="toggleTheme">{{ isDark ? '日间' : '夜间' }}</button>
        </div>

        <!-- ① 顶部结果摘要（§三：综合结果 + 状态 + 覆盖一行 + 报告编号降为辅助信息） -->
        <section id="rep-hero" class="rep rep-hero">
          <div class="rep-hero-main">
            <div class="rep-total">
              <!-- 无综合分：不画 0，给原因（§十六：未测项不得用 0 代替） -->
              <div v-if="hasScore" class="rep-score">{{ fmtScore(report.total_score) }}<small> / 100</small></div>
              <div v-else class="rep-no-score serif">未能形成综合分<span>本场直接观测不足，详见下方明细</span></div>
              <div class="rep-chips">
                <span v-if="report.report_status" class="tb-badge">{{ statusLabel(report.report_status) }}</span>
                <span v-if="report.provisional" class="chip amber">暂定稿（部分观测不足）</span>
                <span v-if="report.version != null" class="tb-badge">报告 v{{ report.version }}</span>
              </div>
            </div>
            <div class="rep-meta-grid">
              <div class="rep-meta-item"><i>岗位</i><b>{{ report.position_name || '—' }}</b></div>
              <div class="rep-meta-item"><i>已完成题数</i><b>{{ (report.question_reviews || []).length }}</b></div>
              <div class="rep-meta-item">
                <i>能力覆盖</i>
                <b v-if="coverage">观测 {{ coverage.observed_count ?? 0 }} · 补算 {{ coverage.imputed_count ?? 0 }} · 无观测 {{ noDataCount }}</b>
                <b v-else>—</b>
              </div>
              <div class="rep-meta-item rep-meta-id"><i>报告编号</i><b>{{ report.report_id }}</b></div>
            </div>
          </div>

          <!-- 资格核验折叠（§四：原生 details 默认折叠，49 项不撑满首屏） -->
          <details v-if="(report.gate_details || []).length" class="gate-fold">
            <summary>
              <span class="gate-fold-title">
                资格核验 {{ report.gate_details.length }} 项：通过 {{ gateSummary.passed }} · 未通过 {{ gateSummary.failed }}
                <span class="gate-fold-afford">展开查看逐条依据</span>
              </span>
            </summary>
            <!-- 关键异常提示：第一条未通过（§四：组级不给 AND 结论，只提示单项） -->
            <div v-if="gateSummary.firstFailed" class="gate-alert">
              存在未通过项：{{ gateSummary.firstFailed.std_name }} —— {{ gateSummary.firstFailed.reason || '未提供或不达标' }}
            </div>
            <div v-for="grp in gateGroups" :key="grp.key" class="gate-group">
              <div class="gate-group-head">{{ grp.label }}（{{ grp.items.length }} 项 · 通过 {{ grp.passedCount }}）</div>
              <div v-for="g in grp.items" :key="g.item_id" class="gate-row">
                <span class="gate-mark" :class="g.passed ? 'ok' : 'no'">{{ g.passed ? '✓' : '✗' }}</span>
                <span class="gate-name">{{ g.std_name }}</span>
                <span class="chip" :class="g.passed ? '' : 'amber'">{{ g.passed ? '通过' : '未通过' }}</span>
                <span class="gate-reason">{{ g.reason || '—' }}</span>
              </div>
            </div>
          </details>
          <p v-else class="field-hint">无资格核验项。</p>
        </section>

        <hr class="divider" />

        <!-- ② 雷达（§十七 Radar：只画直接观测的实际多边形；<3 轴不强行画） -->
        <section id="rep-radar" class="rep">
          <div class="rep-kicker">RADAR</div>
          <div class="rep-title serif">要求 vs 你的表现</div>
          <div v-if="radarIndicators.length >= 3" class="radar-box">
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
              <!-- 实际表现（仅直接观测项进入轴，补算/未测项见明细表） -->
              <polygon :points="actualPoints" :fill="actualFill" stroke="var(--accent)" stroke-width="1.6" />
              <!-- 顶点标签（title 提供完整名称，§十七：截断后可区分） -->
              <text
                v-for="(p, i) in axisPoints"
                :key="`lab-${i}`"
                :x="p.x + (p.x > CX + 4 ? 6 : p.x < CX - 4 ? -6 : 0)"
                :y="p.y + (p.y > CY + 4 ? 12 : p.y < CY - 4 ? -6 : 4)"
                :text-anchor="p.x > CX + 4 ? 'start' : p.x < CX - 4 ? 'end' : 'middle'"
              ><title>{{ radarIndicators[i]?.fullName }}</title>{{ radarIndicators[i]?.label }}</text>
            </svg>
          </div>
          <p v-else class="field-hint radar-fallback">直接观测的能力项不足 3 项，无法绘制雷达图，请逐项查看下方明细。</p>
          <div v-if="radarIndicators.length >= 3" class="radar-legend">
            <span><i style="background: var(--ink-3)"></i>岗位要求</span>
            <span><i style="background: var(--accent)"></i>你的表现（仅直接观测项）</span>
          </div>
          <p v-if="radarTruncated" class="field-hint radar-note">直接观测项超过 {{ MAX_AXES }} 个，图中展示前 {{ MAX_AXES }} 项，完整清单见明细。</p>
        </section>

        <!-- 异议横幅（SSOT §22.2 管理端深链，置于页首结果摘要之后）：仅 ?feedback_id= 进入
             且详情拉取成功时渲染；候选人访问同 URL 时详情端点 403 → fbDetail 为 null，页面其余照常 -->
        <div v-if="fbDetail" class="fb-banner">
          <div class="fb-banner-head">
            <span class="fb-banner-title">候选人异议</span>
            <span v-if="fbDetail.status === 'pending'" class="chip amber">待处理</span>
            <span v-else-if="fbDetail.status === 'reviewed'" class="tb-badge">已处理</span>
            <span v-else class="chip amber">BAD CASE</span>
            <span class="fb-banner-meta">{{ fbDetail.username || '未知用户' }} · {{ formatTime(fbDetail.created_at) }} · {{ fbDetail.std_name }}</span>
          </div>
          <div class="fb-banner-text">{{ fbDetail.feedback_text }}</div>
          <div v-if="fbDetail.review_note" class="fb-banner-note">处理备注：{{ fbDetail.review_note }}（{{ formatTime(fbDetail.reviewed_at) }}）</div>
        </div>

        <!-- ③ 优势 / 短板 -->
        <section id="rep-summary" class="rep">
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

        <!-- ④ 逐题回顾 -->
        <section id="rep-review" v-if="(report.question_reviews || []).length" class="rep">
          <div class="rep-kicker">REVIEW</div>
          <div class="rep-title serif">逐题回顾</div>

          <details
            v-for="(q, i) in report.question_reviews"
            :key="q.question_id || i"
            class="rep-fold"
            :class="{ 'fb-hit': isFeedbackItem(q) }"
            :open="isFeedbackItem(q)"
          >
            <!-- §十八：真实题号（后端透传 seq），无 seq 的旧报告回退序号；标题带能力与终评状态 -->
            <summary>
              <span class="no">{{ pad2(q.seq ?? i + 1) }}</span> {{ brief(q.stem, 34) }}
              <span class="fold-state"><span v-if="q.std_name">{{ q.std_name }} · </span>{{ scoreStateLabel(q) }}</span>
            </summary>
            <div class="body">
              <dl>
                <dt>题目</dt><dd>{{ q.stem }}</dd>
                <dt>我的回答</dt><dd>{{ q.answer || '（未作答）' }}</dd>
                <dt v-if="q.evidence_quote">证据摘录</dt><dd v-if="q.evidence_quote">{{ q.evidence_quote }}</dd>
                <dt>评分依据</dt><dd>{{ q.reason || '—' }}</dd>
                <!-- §十八：过程分是导航参考值，不进入最终计算 -->
                <dt>过程参考值 → 终局结果</dt>
                <dd>
                  {{ q.score_live ?? '—' }} → {{ q.score_final ?? '—' }}
                  <div class="field-hint" style="margin-top: 2px">过程参考值仅用于测评导航，不进入最终分数计算。</div>
                </dd>
              </dl>
            </div>
          </details>
        </section>

        <!-- ⑤ 逐项明细（§三：长明细放最后） -->
        <section id="rep-details" class="rep">
          <div class="rep-kicker">DETAILS</div>
          <div class="rep-title serif">能力项明细</div>

          <table class="rep-table">
            <thead>
              <tr><th>能力项</th><th>要求</th><th>表现</th><th>差距</th><th class="num">权重</th><th class="num">得分</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr
                v-for="it in report.item_details || []"
                :key="it.item_id"
                :class="{ 'fb-hit': isFeedbackItem(it) }"
                :data-item-row="it.item_id"
              >
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
                <td>
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
// 报告页：bootstrap（GET by-session；404→POST 触发→3s 轮询，上限 40）→ 展示。
// 页面顺序（临时讨论稿 §三，2026-09-09）：顶部结果摘要（含资格核验折叠）→ Radar →
// Summary → Review → Details——长明细放最后，资格 49 项默认折叠不撑满首屏。
// 雷达为手写 SVG（required 虚线轮廓 vs actual 填充，§十七：仅直接观测项进轴），
// 无外部图表依赖。
// 轮询健康度（临时讨论稿 §十九，2026-09-09）：到上限只停本页刷新不伪称失败、
// 防请求重叠（pollBusy）、防过期响应覆盖新状态（pollGen 代数核对）、401/403 停轮询给真实原因。
// 打印（§十九）：printReport 先记录 open 态、临时全开 details、window.print 返回后恢复；
// beforeprint/afterprint 事件兜底（浏览器菜单打印路径）。
// 异议深链（SSOT §22.2）：?feedback_id= 管理端进入拉详情画横幅，明细行/逐题回顾同词条高亮（候选人 403 静默降级）。
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { assessment, admin, errMsg } from '../../api'
import { toast } from '../../components/ui'
import { useTheme } from '../../lib/theme'
import { pct, formatTime, SCORE_STATE_LABELS } from '../../lib/labels'

const route = useRoute()
const router = useRouter()
const { theme, toggle: toggleTheme } = useTheme()
const isDark = computed(() => theme.value === 'dark')

const sessionId = route.params.session_id

const phase = ref('loading') // loading | generating | ready | failed
const report = ref(null)
const failText = ref('')
const feedbackDone = ref(new Set())

// ---- 管理端异议详情深链（SSOT §22.2）：?feedback_id= 进入时拉横幅数据 + 定位 ----
// detail 端点 admin-only：候选人访问同 URL 得 403 → fbDetail 留 null 静默降级（页面其余照常）。
// 另一道保险：后端返回的 session_id 与本页 URL 不符（跨报告拼 query）也不渲染。
const fbDetail = ref(null)
const fbDetailId = String(route.query.feedback_id || '')
if (fbDetailId) {
  admin.feedback.getDetail(fbDetailId)
    .then(({ data }) => { if (data.session_id === sessionId) fbDetail.value = data })
    .catch(() => { /* 非管理员/已删 → 静默降级 */ })
}

// 被异议词条命中判定：明细行/逐题回顾（question_reviews 每题带 item_id）同一把尺子
function isFeedbackItem(row) {
  return !!fbDetail.value && row.item_id === fbDetail.value.item_id
}

async function locateFeedbackItem() {
  // 等 DOM 挂好（bootstrap 完成后 nextTick + rAF，取行高亮稳定后）再滚动定位
  await nextTick()
  requestAnimationFrame(() => {
    const el = document.querySelector(`tr[data-item-row="${fbDetail.value.item_id}"]`)
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  })
}

// 报告就绪与详情到位两条异步线任一后到都会补触发一次（详情先到/后到、轮询转正等多种时序）
let fbLocated = false
watch([phase, fbDetail], () => {
  if (fbLocated || phase.value !== 'ready' || !fbDetail.value) return
  fbLocated = true
  locateFeedbackItem()
})

const fbState = reactive({ show: false, item: null, text: '', err: '', submitting: false })

const POLL_MS = 3000
const MAX_POLLS = 40
let pollTimer = null
let polls = 0
let pollBusy = false // in-flight 守卫：上一 tick 未返回则跳过本次，防请求重叠
let pollGen = 0 // 轮询代数：每次 startPoll 递增，过期代次的响应直接丢弃
const pollStopped = ref(false) // 前台已停止轮询（后台仍在生成）：generating 分支据它显示补充提示

// ---- 雷达几何（§十七 Radar：轴 = 直接观测项，补算/未测不进轴——见下 radarEntries）----
const RADAR_W = 460
const RADAR_H = 380
const CX = RADAR_W / 2
const CY = (RADAR_H - 20) / 2
const R = 140
const MAX_AXES = 10

// 轴选取（§十七）：只取非补算且实际有等级的项——雷达只表达「实际测量到的能力」；
// 补算/未测项保留在明细表。截前 MAX_AXES 标注截断。
// 注意：indicators/required 一组同源推导（seriesPoints 读 report 直原数组会错位），
// 这里改为在 computed 内对同一 entries 派生三个数组，保证同置换。
const radarEntries = computed(() => {
  const inds = report.value?.radar_data?.indicators || []
  const required = report.value?.radar_data?.required || []
  const actual = report.value?.radar_data?.actual || []
  return inds
    .map((it, i) => ({ name: it.name, imputed: !!it.imputed, required: required[i], actual: actual[i] }))
    .filter((e) => !e.imputed && e.actual != null)
})
const radarTruncated = computed(() => radarEntries.value.length > MAX_AXES)
const radarIndicators = computed(() =>
  radarEntries.value.slice(0, MAX_AXES).map((e) => ({ label: brief(e.name, 8), fullName: e.name }))
)
const axisPoints = computed(() =>
  radarIndicators.value.map((_, i) => {
    const n = radarIndicators.value.length || 1
    const angle = -Math.PI / 2 + (2 * Math.PI * i) / n
    return { x: CX + R * Math.cos(angle), y: CY + R * Math.sin(angle) }
  })
)
const actualFill = 'var(--accent-soft)'

function ringPoints(frac) {
  return axisPoints.value
    .map((p) => `${CX + (p.x - CX) * frac},${CY + (p.y - CY) * frac}`)
    .join(' ')
}
// 与 radarIndicators 同源派生的系列点（§十七：轴序与值序必须是同一置换）
function seriesPoints(key) {
  const entries = radarEntries.value.slice(0, MAX_AXES)
  const pts = []
  for (let i = 0; i < entries.length; i++) {
    const v = Math.max(0, Math.min(5, Number(entries[i][key]) || 0)) / 5
    const p = axisPoints.value[i] || { x: CX, y: CY }
    pts.push(`${CX + (p.x - CX) * v},${CY + (p.y - CY) * v}`)
  }
  return pts.join(' ')
}
const requiredPoints = computed(() => seriesPoints('required'))
const actualPoints = computed(() => seriesPoints('actual'))

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
// §十八：逐题回顾终评状态——非 SCORED 显示状态中文名（如「题库无效」）
function scoreStateLabel(q) {
  if (q.score_state && q.score_state !== 'SCORED') {
    return SCORE_STATE_LABELS[q.score_state] || q.score_state
  }
  return q.score_final != null ? `终评 ${q.score_final} 分` : '未评分'
}

// 有无综合分（§十六：缺失不得用 0 冒充——total_score 为 0 且无观测时视为无综合分）
const hasScore = computed(() => report.value?.total_score != null && (radarEntries.value.length > 0 || report.value.total_score > 0))

const coverage = computed(() => report.value?.coverage || null)
const noDataCount = computed(
  () => (report.value?.item_details || []).filter((it) => it.no_data && !it.gate).length
)

// ---- gate 段折叠分组（§四：按 facet_key/category 分组，不算组级 AND 结论）----
const GATE_FACET_LABELS = {
  education_degree: '学历要求',
  school_tier: '院校档次',
  english_level: '英语等级',
  number_range: '数值条件',
  major_group: '专业与资格项',
  experience: '工作经验'
}
const gateSummary = computed(() => {
  const details = report.value?.gate_details || []
  const passed = details.filter((g) => g.passed).length
  return {
    total: details.length,
    passed,
    failed: details.length - passed,
    firstFailed: details.find((g) => !g.passed) || null
  }
})
// §四 旧报告兼容：gate_details 缺 category 时用同报告 item_details 按 item_id 补展示分类
const gateCategoryOf = (g, categoryById) => g.category || categoryById.get(g.item_id) || null
const gateGroups = computed(() => {
  const details = report.value?.gate_details || []
  const categoryById = new Map(
    (report.value?.item_details || []).map((it) => [it.item_id, it.category])
  )
  const groupOrder = [
    'education_degree', 'school_tier', 'english_level', 'major_group',
    'number_range', 'experience', 'other'
  ]
  const buckets = new Map()
  for (const g of details) {
    const cat = gateCategoryOf(g, categoryById)
    // 无 facet_key：经验类归「工作经验」，其余（qualification/未知）归「其他条件」
    let key = g.facet_key || (cat === 'experience' ? 'experience' : 'other')
    if (!buckets.has(key)) buckets.set(key, [])
    buckets.get(key).push(g)
  }
  // 固定顺序输出；未知 facet_key 追加尾部（不丢组）
  const known = groupOrder.filter((k) => buckets.has(k))
  const unknown = [...buckets.keys()].filter((k) => !groupOrder.includes(k))
  return [...known, ...unknown].map((k) => ({
    key: k,
    label: GATE_FACET_LABELS[k] || '其他条件',
    items: buckets.get(k),
    passedCount: buckets.get(k).filter((g) => g.passed).length
  }))
})

// §三 / 修复任务 3：missing_reasons 对象数组逐条渲染（原直接 SCORE_STATE_LABELS[m] 产出
// [object Object]）；字符串数组保持原逻辑；对象（reason→count）保持原逻辑。
const missingReasonText = computed(() => {
  const mr = coverage.value?.missing_reasons
  if (!mr) return ''
  if (Array.isArray(mr)) {
    return mr
      .map((m) => {
        if (m != null && typeof m === 'object') {
          const name = m.std_name || m.item_id || '未知项'
          const reason = SCORE_STATE_LABELS[m.reason] || m.reason
          return reason ? `${name}：${reason}` : String(name)
        }
        return SCORE_STATE_LABELS[m] || m
      })
      .join('；')
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
  pollStopped.value = false
  pollBusy = false
  const gen = ++pollGen
  pollTimer = setInterval(async () => {
    polls++
    if (polls > MAX_POLLS) {
      // §十九：前台采样到点只停本页刷新——后台任务未超时（服务端看门狗兜底），不伪称失败
      stopPoll()
      pollStopped.value = true
      return
    }
    if (pollBusy) return // §十九 防重叠：上一 tick 请求在途，跳过本次
    pollBusy = true
    try {
      const { data } = await assessment.getReportBySession(sessionId)
      // §十九 防过期覆盖：本代已被 stopPoll+重启（代数不匹配）或 phase 已离开 generating → 丢弃本次结果
      if (gen !== pollGen || phase.value !== 'generating') return
      if (data.report_status === 'GENERATING') return
      stopPoll()
      if (data.report_status === 'FAILED') {
        phase.value = 'failed'
        failText.value = data.error || '生成失败'
        return
      }
      report.value = data
      phase.value = 'ready'
    } catch (e) {
      // §十九 区分错误：401/403 停轮询并给真实原因（这才是真失败）；
      // 404（尚未写行）、无 response 的网络抖动、5xx → 继续轮询，是否失败以服务端任务状态为准
      if (e?.response?.status === 401 || e?.response?.status === 403) {
        stopPoll()
        phase.value = 'failed'
        failText.value = e?.response?.status === 401 ? '登录已失效，请重新登录后查看' : '当前账号无权限查看该报告'
        return
      }
    } finally {
      if (gen === pollGen) pollBusy = false // 旧代请求不碰新一代的守卫位
    }
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

// ---- 打印（§十九：不依赖用户当前展开态）----
// 记录页面上原本 open 的 details；打印前临时全开（保证 PDF 含全部折叠内容），
// print 返回后恢复。window.print 同步阻塞，返回即打印流结束；
// 兜底挂 beforeprint/afterprint（浏览器菜单打印路径不经过 printReport）。
let printOpenDetails = []
function expandAllDetails(root) {
  printOpenDetails = [...root.querySelectorAll('details')]
  printOpenDetails.forEach((d) => {
    if (d.open) d.dataset.printWasOpen = '1'
    d.open = true
  })
}
function restoreDetails() {
  printOpenDetails.forEach((d) => {
    if (!d.dataset.printWasOpen) d.open = false
    delete d.dataset.printWasOpen
  })
  printOpenDetails = []
}
function printReport() {
  expandAllDetails(document)
  window.print()
  restoreDetails()
}
// 菜单打印兜底：beforeprint 展开、afterprint 恢复（只做一次收口，防止与 printReport 双重恢复冲突）
function handleBeforePrint() {
  if (!printOpenDetails.length) expandAllDetails(document)
}
function handleAfterPrint() {
  restoreDetails()
}
onMounted(() => {
  window.addEventListener('beforeprint', handleBeforePrint)
  window.addEventListener('afterprint', handleAfterPrint)
})

onBeforeUnmount(() => {
  stopPoll()
  window.removeEventListener('beforeprint', handleBeforePrint)
  window.removeEventListener('afterprint', handleAfterPrint)
})
bootstrap()
</script>
