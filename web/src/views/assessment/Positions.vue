<template>
  <div class="grail">
    <!-- 通栏头 -->
    <header class="grail-head">
      <div class="gh-brand">
        <div class="gh-mark">测</div>
        <span class="gh-name">胜任力测评</span>
      </div>
      <div class="gh-divider"></div>
      <div class="gh-crumb">测评端 / <b>选择岗位</b></div>
      <div class="gh-actions">
        <span class="gh-user">{{ auth.user?.username }}</span>
        <button class="btn btn-sm" @click="onLogout">退出</button>
      </div>
    </header>

    <!-- 单栏主体（候选人端无需左导航） -->
    <div class="grail-body">
      <main class="rail-center">
        <div class="rc-head">
          <div class="rc-title">选择测评岗位</div>
          <div class="rc-meta">
            <span>{{ positions.length }} 个开放岗位</span>
          </div>
        </div>

        <div v-loading="loading">
          <div v-if="positions.length" class="grid">
            <div v-for="p in positions" :key="p.position_id" class="rr-card pos-card">
              <div class="pos-name">{{ p.name }}</div>
              <div class="pos-meta">
                <span class="tag tag-grey">模型 v{{ p.version }}</span>
                <span class="pos-count">{{ p.item_count }} 个能力项</span>
              </div>
              <button class="btn btn-primary pos-btn" @click="onStart(p)">开始测评</button>
            </div>
          </div>
          <div v-else-if="!loading" class="rr-card empty-card">
            <el-empty description="暂无开放测评的岗位" />
          </div>
        </div>
      </main>
    </div>

    <!-- 通栏脚 -->
    <footer class="grail-foot">
      <span>CF · 测评端</span>
      <div class="f-right"><span>候选人</span></div>
    </footer>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { assessment } from '../../api'
import { useAuthStore } from '../../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const positions = ref([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const { data } = await assessment.listPositions()
    positions.value = data
  } finally {
    loading.value = false
  }
}

// 点击岗位 -> 进入模型预览页（确认后再创建会话，见 PositionAssess.vue）
function onStart(p) {
  router.push(`/assessment/positions/${p.position_id}`)
}

function onLogout() {
  auth.logout()
  router.push('/login')
}

onMounted(load)
</script>

<style scoped>
/* 顶栏右侧用户区（复用 gh-actions 间距） */
.gh-user {
  font-size: 13px;
  color: var(--ink-2);
  align-self: center;
}
/* 岗位卡片网格 */
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
}
.pos-card {
  display: flex;
  flex-direction: column;
}
.pos-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--ink-1);
  margin-bottom: 10px;
}
.pos-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
}
.pos-count {
  color: var(--ink-3);
  font-size: 12px;
}
.pos-btn {
  width: 100%;
  justify-content: center;
}
.empty-card {
  padding: 24px;
}
</style>
