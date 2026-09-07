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
          <p class="field-hint" style="color: var(--ink-3)">约 40 分钟 · 中途可暂停</p>
          <button class="go" type="button" @click="goAssess(p)">查看并开始 →</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
// 测评端首页：可测评岗位（active + confirmed 模型）卡片流。
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { assessment, errMsg } from '../../api'
import { toast } from '../../components/ui'
import { useAuthStore } from '../../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const positions = ref([])
const loading = ref(false)

function goAssess(p) {
  router.push(`/assessment/positions/${p.position_id}`)
}

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
