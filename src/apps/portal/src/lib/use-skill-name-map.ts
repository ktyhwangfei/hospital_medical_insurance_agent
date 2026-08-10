'use client'
import { useEffect, useState } from 'react'
import { listInfraSkills } from './api-client'

/**
 * 拉取 skill 目录建立 skill_id → skill_name 映射。
 *
 * 供"只有 skill_id、没有 skill_name"的列表（如评测运行的 r.skill_id、评测用例的
 * expected_skill_id）显示中文名，而非英文 ID。映射未就绪或拉取失败时回退到 skill_id。
 */
export function useSkillNameMap(): Map<string, string> {
  const [map, setMap] = useState<Map<string, string>>(new Map())
  useEffect(() => {
    let alive = true
    listInfraSkills()
      .then((skills) => {
        if (!alive) return
        setMap(new Map(skills.map((s) => [s.skill_id, s.skill_name])))
      })
      .catch(() => {
        // 拉取失败保持空映射，调用方回退到 skill_id
      })
    return () => {
      alive = false
    }
  }, [])
  return map
}
