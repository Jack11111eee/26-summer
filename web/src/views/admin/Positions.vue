<template>
  <div class="page">
    <el-card shadow="never" class="panel">
      <div class="head">
        <h2 class="title">岗位库</h2>
        <el-button @click="onLogout">退出登录</el-button>
      </div>
      <el-alert type="info" :closable="false" class="mb16"
        title="M1 阶段：岗位由 JD 解析自动归岗产生。点击岗位进入详情页，导入 JD 并查看解析链。" />
      <el-table :data="positions" v-loading="loading" stripe>
        <el-table-column prop="name" label="岗位名称" min-width="180" />
        <el-table-column label="状态" width="130">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'active' ? 'success' : 'warning'">
              {{ row.status === 'active' ? 'active' : '待审核' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="jd_count" label="JD 数" width="90" align="center" />
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain @click="$router.push(`/admin/positions/${row.position_id}`)">
              进入详情
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无岗位。请先到任意岗位详情页导入 JD（岗位将由解析自动创建）。" />
        </template>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
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
    const { data } = await api.get('/admin/positions')
    positions.value = data
  } finally {
    loading.value = false
  }
}

function onLogout() {
  auth.logout()
  router.push('/login')
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
  border-radius: 12px;
}
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.title {
  margin: 0;
  color: #303133;
}
.mb16 {
  margin-bottom: 16px;
}
</style>
