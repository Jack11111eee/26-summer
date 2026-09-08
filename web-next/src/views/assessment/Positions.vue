<template>
  <div class="page">
    <div class="page-head">
      <div class="open-head serif">
        <div class="kicker">ASSESSMENT · 选择岗位</div>
        <h1>开始你的胜任力测评</h1>
        <p>选择一个已上架的岗位进入测评。每场测评约 40 分钟，题目将根据你的回答动态推进。</p>
      </div>
    </div>

    <div class="page-inner" style="max-width: 860px">
      <div v-if="loading" class="empty">加载岗位中…</div>
      <div v-else-if="!positions.length" class="empty">
        <p class="serif">暂无可测评岗位</p>
        <p style="font-size: 13px">请稍后再来；岗位上架并完成模型确认后即可开测。</p>
      </div>
      <div v-else class="pos-grid">
        <div v-for="p in positions" :key="p.position_id" class="pos-card">
          <h3 class="serif">{{ p.name }}</h3>
          <div class="pos-meta">
            <span class="tb-badge">模型 v{{ p.version }}</span>
            <span class="tb-badge">{{ p.item_count }} 项能力</span>
          </div>
          <!-- 在途摘要（§12.6）：有 active_session 则提示继续 + 剩余时间（get-or-create 保证直达依旧语义等价） -->
          <template v-if="p.active_session">
            <p class="field-hint" style="color: var(--chip-amber-ink)">进行中 · 剩余约 {{ p.active_session.remaining_minutes }} 分钟，可回来继续</p>
            <button class="go" type="button" @click="goSession(p.active_session.session_id)">继续测评 · 回到中断处 →</button>
          </template>
          <template v-else>
            <p class="field-hint" style="color: var(--ink-3)">约 40 分钟 · 中途可暂停</p>
            <button class="go" type="button" @click="goAssess(p)">查看并开始 →</button>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
// 测评端首页：可测评岗位（active + confirmed 模型）卡片流。
import { onActivated, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { assessment, errMsg } from '../../api'
import { toast } from '../../components/ui'
import { useAuthStore } from '../../stores/auth'

defineOptions({ name: 'AssessmentPositions' }) // 壳内 keep-alive include 依名匹配（§5，2026-09-08）

const router = useRouter()
const auth = useAuthStore()
const positions = ref([])
const loading = ref(false)

function goAssess(p) {
  // 带进行中摘要标记（§12.6）：PositionAssess 按钮态显示「继续测评（从中断处继续）」；
  // 后端 get-or-create 已保证两种点击语义等价（无 query 时回退「开始测评」标注）
  router.push({
    path: `/assessment/positions/${p.position_id}`,
    query: p.active_session ? { resume: 1 } : {}
  })
}

// 在途摘要直达（Chat 页恢复链现成；PENDING_START/PAUSED 由其现有门卡处理）
function goSession(sessionId) {
  router.push(`/assessment/session/${sessionId}`)
}

// keep-alive 激活：静默重拉卡片流（booted 守卫防首屏双拉——onMounted 之后必触发一轮；
// 返回场景刷新在途摘要 remaining_minutes，§5，2026-09-08）
let booted = false
onActivated(async () => {
  if (!booted) { booted = true; return }
  try {
    const { data } = await assessment.listPositions()
    positions.value = data
  } catch { /* 静默：保持缓存视图，用户可手动刷新 */ }
})

onMounted(async () => {
  loading.value = true
  try {
    const { data } = await assessment.listPositions()
    positions.value = data
  } catch (e) {
    toast(errMsg(e, '岗位加载失败'), 'error')
  } finally {
    loading.value = false
  }
})
</script>
