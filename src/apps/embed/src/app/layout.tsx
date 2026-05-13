import type { Metadata } from 'next'
import { Noto_Sans_SC } from 'next/font/google'
import { ApiProvider } from '@/lib/api-context'
import './globals.css'

const notoSansSC = Noto_Sans_SC({ subsets: ['latin'], variable: '--font-noto-sans-sc' })

export const metadata: Metadata = {
  title: '医保AI导办 - 嵌入式',
  description: '嵌入HIS/EMR的医保AI导办对话组件',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className={`${notoSansSC.variable} font-sans antialiased h-screen overflow-hidden`}>
        <ApiProvider>
          {children}
        </ApiProvider>
      </body>
    </html>
  )
}
