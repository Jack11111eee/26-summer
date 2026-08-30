<template>
  <div class="nav">
    <div class="nav-inner">
      <span class="brand">胜任力测评</span>
      <div class="right">
        <span class="username">{{ auth.user?.username }}</span>
        <el-button size="small" @click="onLogout">退出</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()

function onLogout() {
  auth.logout()
  router.push('/login')
}
</script>

<style scoped>
.nav {
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  position: sticky;
  top: 0;
  z-index: 100;
}
.nav-inner {
  max-width: 1280px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  height: 56px;
}
.brand {
  font-weight: 600;
  color: #303133;
}
.right {
  display: flex;
  align-items: center;
  gap: 10px;
}
.username {
  color: #606266;
  font-size: 14px;
}
</style>
