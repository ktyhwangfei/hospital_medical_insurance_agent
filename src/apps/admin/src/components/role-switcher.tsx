import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { RoleId } from '@/lib/types'

export interface RoleOption {
  id: RoleId
  name: string
  icon: string
  color: string
}

const roles: RoleOption[] = [
  {
    id: 'cashier',
    name: '收费员',
    icon: '💰',
    color: 'bg-green-100 text-green-800',
  },
  {
    id: 'medical_office',
    name: '医保办',
    icon: '🏥',
    color: 'bg-blue-100 text-blue-800',
  },
  {
    id: 'information_department',
    name: '信息科',
    icon: '💻',
    color: 'bg-purple-100 text-purple-800',
  },
  {
    id: 'medical_record_staff',
    name: '病案室',
    icon: '📋',
    color: 'bg-orange-100 text-orange-800',
  },
  {
    id: 'clinician',
    name: '临床医生',
    icon: '🩺',
    color: 'bg-teal-100 text-teal-800',
  },
]

export default function RoleSwitcher({
  currentRole,
  onRoleChange,
}: {
  currentRole: RoleId
  onRoleChange: (role: RoleId) => void
}) {
  const current = roles.find((role) => role.id === currentRole) ?? roles[0]

  return (
    <Select value={currentRole} onValueChange={(value) => onRoleChange(value as RoleId)}>
      <SelectTrigger className="w-[140px]">
        <SelectValue>
          <span className="flex items-center gap-2">
            <span>{current.icon}</span>
            <span className="text-sm">{current.name}</span>
          </span>
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        {roles.map((role) => (
          <SelectItem key={role.id} value={role.id}>
            <span className="flex items-center gap-2">
              <span>{role.icon}</span>
              <span>{role.name}</span>
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

export { roles }
