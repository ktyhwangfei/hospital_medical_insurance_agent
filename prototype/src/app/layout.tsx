import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import { ApiProvider } from '@/lib/api-context'
import './globals.css'

const inter = Inter({ subsets: ['latin'] })

export const metadata: Metadata = {
  title: '医保AI导办与运营协同平台 - 原型演示',
  description: '医院医保智能工作台原型演示系统',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="zh-CN">
      <body className={inter.className}>
        <ApiProvider>{children}</ApiProvider>
      </body>
    </html>
  )
}
