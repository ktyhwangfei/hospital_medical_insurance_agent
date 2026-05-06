import type { NextConfig } from 'next'

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://127.0.0.1:8000'

const nextConfig: NextConfig = {
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
