/**
 * V4.0 政策问答智能体：来源卡片数据映射（纯逻辑，可单测）。
 *
 * 设计 §4.1：政策来源卡片常显（文档标题 + 条款 + 摘要 + 原文链接）。
 * 向量检索命中的是语义单元，同一篇文档可能命中多条，按文档合并展示。
 */

import type { PolicyQAResult } from '@/lib/policy-qa-stream'

export interface CitationGroup {
  title: string
  docId?: string
  excerpts: Array<{ text: string; sourceExcerpt?: string }>
}

/** 同一篇文档命中的多个语义单元合并展示，避免同一标题重复出现。 */
export function groupCitationsByDocument(
  citations: PolicyQAResult['citations'],
): CitationGroup[] {
  const map = new Map<string, CitationGroup>()
  for (const citation of citations) {
    const key = citation.docId || citation.title
    const group = map.get(key) ?? {
      title: citation.title,
      docId: citation.docId,
      excerpts: [],
    }
    if (!group.excerpts.some((item) => item.text === citation.excerpt)) {
      group.excerpts.push({ text: citation.excerpt, sourceExcerpt: citation.sourceExcerpt })
    }
    map.set(key, group)
  }
  return [...map.values()]
}
