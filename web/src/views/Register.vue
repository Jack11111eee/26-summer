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

    <!-- 居中注册卡片 -->
    <el-card class="auth-card" shadow="always">
      <h2 class="card-title">创建账号</h2>
      <p class="card-tip">注册后将以「候选人」身份使用测评功能</p>
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
        <el-form-item prop="confirm">
          <el-input
            v-model="form.confirm"
            type="password"
            placeholder="确认密码"
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
            注 册
          </el-button>
        </el-form-item>
      </el-form>
      <div class="card-footer">
        已有账号？
        <router-link to="/login">返回登录</router-link>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock, Aim } from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()

const formRef = ref()
const loading = ref(false)
const form = reactive({ username: '', password: '', confirm: '' })

// 确认密码需与密码一致
const validateConfirm = (rule, value, callback) => {
  if (value !== form.password) {
    callback(new Error('两次输入的密码不一致'))
  } else {
    callback()
  }
}

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少 6 位', trigger: 'blur' }
  ],
  confirm: [
    { required: true, message: '请再次输入密码', trigger: 'blur' },
    { validator: validateConfirm, trigger: 'blur' }
  ]
}

// 提交注册，成功后引导去登录页
async function onSubmit() {
  await formRef.value.validate().catch(() => Promise.reject())
  loading.value = true
  try {
    await auth.register(form.username, form.password)
    ElMessage.success('注册成功，请登录')
    router.push('/login')
  } catch (err) {
    const status = err.response?.status
    if (status === 409) {
      ElMessage.error('该用户名已被注册')
    } else {
      ElMessage.error('注册失败，请稍后重试')
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
  padding-top: 10vh;
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
  margin: 0 0 8px;
  text-align: center;
  font-size: 20px;
  color: #303133;
}

.card-tip {
  margin: 0 0 22px;
  text-align: center;
  font-size: 13px;
  color: #909399;
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
