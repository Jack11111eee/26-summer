<template>
  <div class="page">
    <div class="page-head">
      <div class="open-head serif">
        <div class="kicker">COMPETENCY ASSESSMENT</div>
        <h1>胜任力测评系统</h1>
        <p>登录后开始你的岗位胜任力测评，或进入管理端维护岗位与模型。</p>
      </div>
    </div>

    <div class="page-inner">
      <form class="paper-card" novalidate @submit.prevent="onSubmit">
        <div class="field">
          <label class="field-label" for="login-username">用户名</label>
          <input id="login-username" v-model="username" class="input" type="text" autocomplete="username" />
        </div>
        <div class="field">
          <label class="field-label" for="login-password">密码</label>
          <input id="login-password" v-model="password" class="input" type="password" autocomplete="current-password" />
        </div>
        <p v-if="errorText" class="field-error">{{ errorText }}</p>
        <button class="btn-accent" type="submit" :disabled="submitting || !username || !password">
          {{ submitting ? '正在登录…' : '登 录' }}
        </button>
        <p class="field-hint" style="margin-top: 12px; text-align: center">
          还没有账号？<span class="link" @click="goRegister">注册一个（考生身份）</span>
        </p>
      </form>
    </div>
  </div>
</template>

<script setup>
// 登录：暖纸入口页。body class 由 App.vue 路由钩子统一挂 candidate/admin，
// 页面内只管表单与跳转。
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { errMsg } from '../api'
import { toast } from '../components/ui'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const username = ref('')
const password = ref('')
const errorText = ref('')
const submitting = ref(false)

function goRegister() {
  router.push('/register')
}

async function onSubmit() {
  if (submitting.value) return
  submitting.value = true
  errorText.value = ''
  try {
    const user = await auth.login(username.value.trim(), password.value)
    toast(`欢迎回来，${user.username}`)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : ''
    if (redirect && redirect.startsWith('/')) {
      router.push(redirect)
    } else {
      router.push(auth.homePath)
    }
  } catch (e) {
    errorText.value = errMsg(e, '用户名或密码错误')
  } finally {
    submitting.value = false
  }
}
</script>
