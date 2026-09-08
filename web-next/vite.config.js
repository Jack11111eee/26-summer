import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发服务器将 /api 代理到本地 FastAPI 后端（端口 5174，与联调前端 web/ 的 5173 并行）。
// 代理目标可用 API_TARGET 覆盖（默认同源 8000——生产由 FastAPI 直接挂载 dist）。
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5174,
    proxy: {
      '/api': {
        target: process.env.API_TARGET || 'http://localhost:8000',
        changeOrigin: true
      }
    }
  }
})
