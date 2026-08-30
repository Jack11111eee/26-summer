<template>
  <div class="page">
    <el-card shadow="never" class="panel">
      <h2 class="title">P1 岗位库（管理端）</h2>
      <el-empty description="建设中：岗位审核、JD 导入等功能将在后续迭代提供" />
      <div class="actions">
        <el-button @click="onLogout">退出登录</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth'

// 占位页：M1 仅验证守卫与角色跳转，页面内容后续任务填充
const router = useRouter()
const auth = useAuthStore()

function onLogout() {
  auth.logout()
  router.push('/login')
}
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

.title {
  margin: 0 0 16px;
  color: #303133;
}

.actions {
  display: flex;
  justify-content: center;
  margin-top: 16px;
}
</style>
