import { redirect } from 'next/navigation'

// 治理 Flow 已迁入数据治理中心；旧 /flow/<id> 书签 301 兼容
export default async function FlowEditorRedirectPage({
  params,
}: {
  params: Promise<{ flowId: string }>
}) {
  const { flowId } = await params
  redirect(`/data-governance/flows/${encodeURIComponent(flowId)}`)
}
