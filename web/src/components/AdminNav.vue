<template>
  <div class="nav">
    <div class="nav-inner">
      <span class="brand">胜任力测评 · 管理端</span>
      <el-menu :default-active="activePath" mode="horizontal" router class="menu" :ellipsis="false">
        <el-menu-item index="/admin/positions">岗位库</el-menu-item>
        <el-menu-item index="/admin/dict">能力词典</el-menu-item>
        <el-menu-item index="/admin/users">用户管理</el-menu-item>
        <el-menu-item index="/admin/test-center">测试中心</el-menu-item>
      </el-menu>
      <div class="right">
        <span class="username">{{ auth.user?.username }}</span>
        <el-button size="small" @click="onLogout">退出</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

// 高亮当前一级菜单（/admin/positions/xxx 也归为岗位库）
const activePath = computed(() => {
  const p = route.path
  if (p.startsWith('/admin/dict')) return '/admin/dict'
  if (p.startsWith('/admin/users')) return '/admin/users'
  if (p.startsWith('/admin/test-center')) return '/admin/test-center'
  return '/admin/positions'
})

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
  padding: 0 24px;
}
.brand {
  font-weight: 600;
  color: #303133;
  margin-right: 32px;
  white-space: nowrap;
}
.menu {
  flex: 1;
  border-bottom: none;
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
