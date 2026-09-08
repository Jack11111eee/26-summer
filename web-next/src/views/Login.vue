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
          <div class="password-wrap">
            <input
              id="login-password"
              v-model="password"
              class="input"
              :type="showPassword ? 'text' : 'password'"
              autocomplete="current-password"
            />
            <button
              type="button"
              class="password-toggle"
              :aria-label="showPassword ? '隐藏密码' : '显示密码'"
              @click="showPassword = !showPassword"
            >
              <!-- 睁眼=明文可切回密文；闭眼=当前密文 -->
              <svg v-if="showPassword" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z" />
                <circle cx="12" cy="12" r="3" />
              </svg>
              <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <path d="M17.94 17.94A10.5 10.5 0 0 1 12 19c-7 0-11-7-11-7a19.8 19.8 0 0 1 5.06-5.94M9.9 4.24A9.9 9.9 0 0 1 12 4c7 0 11 7 11 7a19.8 19.8 0 0 1-3.22 4.31" />
                <line x1="1" y1="1" x2="23" y2="23" />
                <path d="M14.12 14.12A3 3 0 1 1 9.88 9.88" />
              </svg>
            </button>
          </div>
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
const showPassword = ref(false)
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
