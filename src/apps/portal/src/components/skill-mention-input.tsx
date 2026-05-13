'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import { Input } from '@/components/ui/input'
import type { Skill, RoleId } from '@/lib/types'

interface SkillMentionInputProps {
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
  role: RoleId
  skills: Skill[]
  placeholder?: string
  disabled?: boolean
}

function highlightMentions(text: string): React.ReactNode[] {
  const parts: React.ReactNode[] = []
  const regex = /@([a-z0-9_]+(?:-[a-z0-9_]+)*)/g
  let lastIndex = 0
  let match: RegExpExecArray | null

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index))
    }
    parts.push(
      <span key={match.index} className="bg-blue-100 text-blue-700 rounded px-0.5">
        {match[0]}
      </span>
    )
    lastIndex = match.index + match[0].length
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex))
  }

  return parts.length > 0 ? parts : [text]
}

export function SkillMentionInput({
  value,
  onChange,
  onSubmit,
  role,
  skills,
  placeholder,
  disabled,
}: SkillMentionInputProps) {
  const [showDropdown, setShowDropdown] = useState(false)
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [mentionStart, setMentionStart] = useState<number | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const filteredSkills = skills.filter(
    (skill) =>
      skill.enabled &&
      (skill.owner === role || skill.required_roles.includes(role))
  )

  const getQuery = useCallback((): string => {
    if (mentionStart === null) return ''
    return value.slice(mentionStart + 1).toLowerCase()
  }, [mentionStart, value])

  const visibleSkills = filteredSkills.filter((skill) => {
    const query = getQuery()
    if (!query) return true
    return (
      skill.name.toLowerCase().includes(query) ||
      skill.skill_id.toLowerCase().includes(query) ||
      skill.description.toLowerCase().includes(query)
    )
  })

  useEffect(() => {
    setSelectedIndex(0)
  }, [visibleSkills.length])

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setShowDropdown(false)
        setMentionStart(null)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newValue = e.target.value
    const cursorPos = e.target.selectionStart ?? newValue.length
    onChange(newValue)

    const textBeforeCursor = newValue.slice(0, cursorPos)
    const atIndex = textBeforeCursor.lastIndexOf('@')

    if (atIndex !== -1) {
      const textAfterAt = textBeforeCursor.slice(atIndex + 1)
      if (!/\s/.test(textAfterAt) && (atIndex === 0 || /\s/.test(textBeforeCursor[atIndex - 1]))) {
        setShowDropdown(true)
        setMentionStart(atIndex)
        return
      }
    }

    setShowDropdown(false)
    setMentionStart(null)
  }

  const selectSkill = (skill: Skill) => {
    if (mentionStart === null) return

    const before = value.slice(0, mentionStart)
    const after = value.slice(inputRef.current?.selectionStart ?? value.length)
    const newValue = `${before}@${skill.skill_id} ${after}`
    onChange(newValue)
    setShowDropdown(false)
    setMentionStart(null)

    requestAnimationFrame(() => {
      inputRef.current?.focus()
    })
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !showDropdown) {
      e.preventDefault()
      onSubmit()
      return
    }

    if (!showDropdown || visibleSkills.length === 0) return

    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedIndex((prev) => (prev + 1) % visibleSkills.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIndex((prev) => (prev - 1 + visibleSkills.length) % visibleSkills.length)
    } else if (e.key === 'Enter') {
      e.preventDefault()
      selectSkill(visibleSkills[selectedIndex])
    } else if (e.key === 'Escape') {
      setShowDropdown(false)
      setMentionStart(null)
    }
  }

  if (skills.length === 0) {
    return (
      <Input
        ref={inputRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && onSubmit()}
        placeholder={placeholder ?? '输入您的问题...'}
        disabled={disabled}
        className="flex-1"
      />
    )
  }

  return (
    <div ref={containerRef} className="relative flex-1">
      <Input
        ref={inputRef}
        value={value}
        onChange={handleInputChange}
        onKeyDown={handleKeyDown}
        placeholder={placeholder ?? '输入您的问题或 @ 选择技能...'}
        disabled={disabled}
        className="w-full"
      />

      {showDropdown && visibleSkills.length > 0 && (
        <div className="absolute bottom-full left-0 mb-1 z-50 w-72 max-h-60 overflow-y-auto rounded-lg border border-gray-200 bg-white shadow-lg">
          <div className="px-2 py-1.5 border-b border-gray-100 text-xs text-gray-500">
            技能列表 · 输入筛选 · ↑↓ 选择 · Enter 确认
          </div>
          {visibleSkills.map((skill, index) => (
            <button
              key={skill.skill_id}
              type="button"
              className={`w-full text-left px-3 py-2 text-sm transition-colors ${
                index === selectedIndex
                  ? 'bg-blue-50 text-blue-900'
                  : 'hover:bg-gray-50 text-gray-700'
              }`}
              onClick={() => selectSkill(skill)}
              onMouseEnter={() => setSelectedIndex(index)}
            >
              <div className="font-medium truncate">@{skill.skill_id}</div>
              <div className="text-xs text-gray-500 truncate">{skill.name}</div>
              {skill.description && (
                <div className="text-xs text-gray-400 truncate mt-0.5">{skill.description}</div>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}