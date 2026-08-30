<template>
  <div class="auth-page">
    <!-- 顶部品牌区 -->
    <header class="brand">
      <div class="brand-logo">
        <el-icon :size="28" color="#fff"><Aim /></el-icon>
      </div>
      <div>
        <h1 class="brand-title">岗位胜任力测评系统</h1>
        <p class="brand-sub">Job Competency Assessment Platform</p>
      </div>
    </header>

    <!-- 居中登录卡片 -->
    <el-card class="auth-card" shadow="always">
      <h2 class="card-title">欢迎登录</h2>
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        size="large"
        @keyup.enter="onSubmit"
      >
        <el-form-item prop="username">
          <el-input v-model="form.username" placeholder="用户名" :prefix-icon="User" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="密码（至少 6 位）"
            show-password
            :prefix-icon="Lock"
          />
        </el-form-item>
        <el-form-item>
          <el-button
            type="primary"
            class="submit-btn"
            :loading="loading"
            @click="onSubmit"
          >
            登 录
          </el-button>
        </el-form-item>
      </el-form>
      <div class="card-footer">
        还没有账号？
        <router-link to="/register">立即注册</router-link>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock, Aim } from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const formRef = ref()
const loading = ref(false)
const form = reactive({ username: '', password: '' })

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少 6 位', trigger: 'blur' }
  ]
}

// 提交登录，成功后按角色跳首页（或回跳 redirect）
async function onSubmit() {
  await formRef.value.validate().catch(() => Promise.reject())
  loading.value = true
  try {
    const user = await auth.login(form.username, form.password)
    ElMessage.success(`欢迎回来，${user.username}`)
    const fallback =
      user.role === 'admin' ? '/admin/positions' : '/assessment/positions'
    router.push(route.query.redirect || fallback)
  } catch (err) {
    const status = err.response?.status
    if (status === 401) {
      ElMessage.error('用户名或密码错误')
    } else {
      ElMessage.error('登录失败，请稍后重试')
    }
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-page {
  min-height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 12vh;
  background: linear-gradient(180deg, #eaf2ff 0%, #f5f7fa 45%);
}

.brand {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 32px;
}

.brand-logo {
  width: 52px;
  height: 52px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #409eff, #337ecc);
  box-shadow: 0 6px 16px rgba(64, 158, 255, 0.35);
}

.brand-title {
  margin: 0;
  font-size: 24px;
  color: #1f2d3d;
  letter-spacing: 1px;
}

.brand-sub {
  margin: 4px 0 0;
  font-size: 13px;
  color: #909399;
}

.auth-card {
  width: 400px;
  border-radius: 12px;
}

.card-title {
  margin: 0 0 22px;
  text-align: center;
  font-size: 20px;
  color: #303133;
}

.submit-btn {
  width: 100%;
  letter-spacing: 8px;
}

.card-footer {
  text-align: center;
  font-size: 13px;
  color: #909399;
}

.card-footer a {
  color: #409eff;
  text-decoration: none;
}
</style>
