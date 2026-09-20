'use client'

import { LogOut, UserRound } from 'lucide-react'
import { useAuth } from '@/components/auth-provider'

// 门户账号角色 → 展示名（角色集与后端 src/config/security_policy/portal_roles.py 对齐）
const ROLE_LABELS: Record<string, string> = {
  admin: '管理员',
  governance_admin: '数据治理管理员',
  ops_admin: '运营管理员',
  knowledge_admin: '知识管理员',
  reviewer: '审核员',
  skill_admin: '技能管理员',
}

// Header 登录态出口（Issue #75）：展示当前登录主体并提供登出。
// 未登录（dev 无 token / 生产未登录）展示登录入口。
export function UserMenu() {
  const { principal, logout } = useAuth()

  if (!principal) {
    return (
      <a
        href="/login"
        className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-[11px] font-medium text-slate-600 ring-1 ring-slate-300 hover:bg-slate-50"
      >
        <UserRound className="size-3" />
        登录
      </a>
    )
  }

  const roleLabel = principal.roles.map((role) => ROLE_LABELS[role] ?? role).join('、')

  return (
    <div className="flex items-center gap-1.5">
      <span
        title={`账号 ${principal.user_id} · 角色 ${roleLabel}`}
        className="hidden max-w-52 items-center gap-1.5 truncate whitespace-nowrap rounded-full bg-slate-50 px-2.5 py-0.5 text-[11px] font-medium text-slate-700 ring-1 ring-slate-300 sm:inline-flex"
      >
        <UserRound className="size-3 shrink-0 text-slate-500" />
        <span className="truncate">{principal.user_id}</span>
        <span className="text-slate-400">·</span>
        <span className="truncate">{roleLabel}</span>
      </span>
      <button
        type="button"
        onClick={() => void logout()}
        aria-label="退出登录"
        title={`退出登录（${principal.user_id}）`}
        className="flex size-7 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
      >
        <LogOut className="size-3.5" />
      </button>
    </div>
  )
}
