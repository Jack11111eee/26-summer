import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发服务器将 /api 代理到本地 FastAPI 后端（端口 5174，与联调用 web/ 的 5173 并行不冲突）
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5174,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true
      }
    }
  }
})
