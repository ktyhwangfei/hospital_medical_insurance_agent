// E2E 门户登录态种子（P2 路由守卫后必需）：真实调用 /auth/login 换 token，
// 注入 sessionStorage.portal-token（与浏览器真实登录同一通路，不自造 claims）。
import type { Page } from '@playwright/test'

import { E2E_BACKEND_URL } from './workspace-ports'

const LOGIN_URL = `${E2E_BACKEND_URL}/api/v1/medical-insurance-ai-agent/auth/login`

/** 默认账号与 start-servers.ps1 种子一致；可用环境变量覆盖。 */
const E2E_USERNAME = process.env.E2E_PORTAL_USER ?? 'admin'
const E2E_PASSWORD = process.env.E2E_PORTAL_PASSWORD ?? 'Admin@123456'

export async function seedPortalSession(page: Page): Promise<void> {
  const response = await fetch(LOGIN_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: E2E_USERNAME, password: E2E_PASSWORD }),
  })
  if (!response.ok) {
    throw new Error(`E2E 登录失败（HTTP ${response.status}）：请确认后端已用 start-servers.ps1 启动并种子账号可用`)
  }
  const body = (await response.json()) as { access_token?: string }
  if (!body.access_token) throw new Error('E2E 登录响应缺少 access_token')
  await page.addInitScript(
    (token) => window.sessionStorage.setItem('portal-token', token),
    body.access_token,
  )
}
