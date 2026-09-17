import { redirect } from 'next/navigation'

// 数据目录已并入数据治理中心「数据资产」模块；旧 /data-catalog 书签 301 兼容
export default function DataCatalogRedirectPage() {
  redirect('/data-governance/assets')
}
