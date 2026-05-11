import type { Metadata } from 'next'
import { Noto_Sans_SC } from 'next/font/google'
import { ApiProvider } from '@/lib/api-context'
import './globals.css'

const notoSansSC = Noto_Sans_SC({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  variable: '--font-sans',
  display: 'swap',
})

export const metadata: Metadata = {
  title: '医保AI导办与运营协同平台',
  description: '医院医保智能工作台',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className={notoSansSC.variable}>
        <ApiProvider>{children}</ApiProvider>
      </body>
    </html>
  )
}
