import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const aiApiTarget = (env.VITE_AI_API_BASE_URL || 'http://localhost:9000').replace(/\/$/, '')
  const internalApiKey = env.INTERNAL_API_KEY || env.AI_INTERNAL_API_KEY || ''

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      port: 5173,
      // local RF 시뮬 heatmap — DB 에 저장된 ai_api URL(localhost:9000) 을
      // 브라우저 same-origin 으로 우회. ai_api 가 실행 중이어야 함.
      proxy: {
        '/__ai_api__': {
          target: aiApiTarget,
          changeOrigin: true,
          rewrite: (reqPath) => reqPath.replace(/^\/__ai_api__/, ''),
          configure: (proxy) => {
            proxy.on('proxyReq', (proxyReq) => {
              if (internalApiKey) {
                proxyReq.setHeader('X-Internal-API-Key', internalApiKey)
              }
            })
          },
        },
      },
    },
  }
})
