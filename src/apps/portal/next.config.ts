import type { NextConfig } from 'next'

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://127.0.0.1:8000'

const nextConfig: NextConfig = {
  // 支持多实例 dev：默认 .next，可用 NEXT_DIST_DIR 覆盖（避免同目录双开 dev 的锁冲突）
  distDir: process.env.NEXT_DIST_DIR || '.next',
  // Benchmark 运行同步执行需 1-2 分钟，默认 30s 代理超时会 500
  // ponytail: 同步等待上限 10 分钟；运行时长超过它时改为异步 202 + 轮询
  experimental: {
    proxyTimeout: 600_000,
  },
  allowedDevOrigins: ['127.0.0.1', '192.168.43.190'],
  async redirects() {
    return [{
      source: '/semantic-layer/proposals',
      destination: '/policy-knowledge/knowledge/semantic-discovery',
      permanent: false,
    }]
  },
  async rewrites() {
    return [
      {
        source: '/api/v1/medical-insurance-ai-agent/:path*',
        destination: `${apiBaseUrl}/api/v1/medical-insurance-ai-agent/:path*`,
      },
    ]
  },
}

export default nextConfig
