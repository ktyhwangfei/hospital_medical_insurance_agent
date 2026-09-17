import { redirect } from 'next/navigation'

// 治理 Flow 已迁入数据治理中心；旧 /flow 书签 301 兼容
export default function FlowRedirectPage() {
  redirect('/data-governance/flows')
}
