// Skill 写操作的 dev 鉴权集中定义（api-client 与 skill-draft-api 共用，避免双份漂移）

import { getToken, hasPermission } from '@/lib/auth'

export const DEV_SKILL_CONTROL_TOKEN =
  'test.eyJzdWIiOiJwb3J0YWwtZGV2ZWxvcGVyIiwicm9sZXMiOlsiZGV2ZWxvcGVyIl0sInBlcm1pc3Npb25zIjpbInNraWxsOnJlbGVhc2U6dGVzdCIsInNraWxsOmV2YWx1YXRlIl0sImV4cCI6NDEwMjQ0NDgwMH0.signature'

export const DEV_SKILL_APPROVAL_TOKEN =
  'test.eyJzdWIiOiJwb3J0YWwtaW5mb3JtYXRpb24tYWRtaW4iLCJyb2xlcyI6WyJpbmZvcm1hdGlvbl9kZXBhcnRtZW50Il0sInBlcm1pc3Npb25zIjpbInNraWxsOnJlbGVhc2U6dGVzdCJdLCJleHAiOjQxMDI0NDQ4MDB9.signature'

export const DEV_POLICY_QA_FEEDBACK_TOKEN =
  'test.eyJzdWIiOiJkZW1vIiwicm9sZXMiOlsiY2FzaGllciJdLCJwZXJtaXNzaW9ucyI6W10sImV4cCI6NDEwMjQ0NDQ4MDB9.signature'

// Issue #75：portal-token 登录态优先；为空时维持 dev 假 token 兜底（D8，deprecated 待后续切片移除）
function resolveToken(devFallback: string): string | null {
  if (typeof window === 'undefined') return null
  return getToken() ?? (process.env.NODE_ENV !== 'production' ? devFallback : null)
}

// 评测者鉴权头（skill:evaluate）
export function skillEvaluationHeaders(): HeadersInit {
  const headers: Record<string, string> = {}
  const token = resolveToken(DEV_SKILL_CONTROL_TOKEN)
  if (token) headers.Authorization = `Bearer ${token}`
  return headers
}

export function policyQAFeedbackHeaders(): HeadersInit {
  const headers: Record<string, string> = {}
  const token = resolveToken(DEV_POLICY_QA_FEEDBACK_TOKEN)
  if (token) headers.Authorization = `Bearer ${token}`
  return headers
}

// Skill 治理写/评测权限预判（后端校验 skill:release:test / skill:evaluate；体验层禁用）
export function hasSkillControlPermission(): boolean {
  return hasPermission('skill:release:test')
}

export function hasSkillEvaluationPermission(): boolean {
  return hasPermission('skill:evaluate')
}

// 控制台写操作鉴权头（可带幂等键；approval=true 时用审批人 token）
export function skillControlHeaders(
  idempotencyKey?: string,
  approval = false,
): HeadersInit {
  const headers: Record<string, string> = {}
  if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey
  const token = resolveToken(approval ? DEV_SKILL_APPROVAL_TOKEN : DEV_SKILL_CONTROL_TOKEN)
  if (token) headers.Authorization = `Bearer ${token}`
  return headers
}
