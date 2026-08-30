<template>
  <CandidateNav />
  <div class="page">
    <div class="panel">
      <!-- 页头 -->
      <div class="head">
        <h2 class="title">选择测评岗位</h2>
      </div>

      <!-- 岗位卡片网格 -->
      <div v-loading="loading">
        <div v-if="positions.length" class="grid">
          <el-card v-for="p in positions" :key="p.position_id" shadow="hover" class="card">
            <div class="card-name">{{ p.name }}</div>
            <div class="card-meta">
              <el-tag size="small" effect="plain">模型 v{{ p.version }}</el-tag>
              <span class="card-count">{{ p.item_count }} 个能力项</span>
            </div>
            <el-button
              type="primary"
              class="card-btn"
              @click="$router.push(`/assessment/positions/${p.position_id}`)"
            >
              开始测评
            </el-button>
          </el-card>
        </div>
        <el-card v-else-if="!loading" shadow="never" class="empty-card">
          <el-empty description="暂无开放测评的岗位" />
        </el-card>
      </div>
    </div>
  </div>
</template>

<script setup>
import CandidateNav from '../../components/CandidateNav.vue'
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import api from '../../api'
import { useAuthStore } from '../../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const positions = ref([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/assessment/positions')
    positions.value = data
  } finally {
    loading.value = false
  }
}


onMounted(load)
</script>

<style scoped>
.page {
  padding: 24px;
}
.panel {
  max-width: 960px;
  margin: 0 auto;
}
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.title {
  margin: 0;
  color: #303133;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
}
.card {
  border-radius: 12px;
}
.card-name {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 10px;
}
.card-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
}
.card-count {
  color: #909399;
  font-size: 13px;
}
.card-btn {
  width: 100%;
}
.empty-card {
  border-radius: 12px;
}
</style>
