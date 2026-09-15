import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    include: ['src/tests/**/*.test.{ts,tsx}'],
    setupFiles: ['./src/tests/setup.ts'],
  },
  resolve: {
    alias: [
      {
        find: '@',
        replacement: path.resolve(__dirname, './src'),
      },
      {
        // next/font 需要 Next.js 构建期处理，测试环境统一指向 stub
        find: 'next/font/google',
        replacement: path.resolve(__dirname, './src/tests/__mocks__/next-font-google.ts'),
      },
    ],
  },
})
