'use client'

import { useMemo, useState } from 'react'
import { BookOpen, Brain, FileText, ScrollText, Search } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Progress } from '@/components/ui/progress'
import {
  errorCodeKnowledge,
  mockDrgRules,
  mockKnowledgeAssets,
  mockPromptTemplates,
  mockRagResults,
} from '@/lib/mock-data'

export default function KnowledgeExplorer() {
  const [query, setQuery] = useState('待遇资格校验失败')
  const [searched, setSearched] = useState(false)

  const visibleRagResults = useMemo(() => {
    if (!searched) return mockRagResults.slice(0, 1)
    const q = query.trim().toLowerCase()
    if (!q) return mockRagResults
    return mockRagResults.filter(
      (r) => r.summary.toLowerCase().includes(q) || r.source.toLowerCase().includes(q)
    )
  }, [searched, query])

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold">知识扩展浏览</h2>
          <p className="text-sm text-gray-500 mt-1">浏览知识资产、规则解释、RAG 检索和提示模板</p>
        </div>
        <Badge className="bg-purple-100 text-purple-800">演示数据</Badge>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {mockKnowledgeAssets.map((asset) => (
          <Card key={asset.title}>
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-500">{asset.title}</p>
                  <p className={`text-2xl font-bold mt-1 ${asset.color}`}>{asset.value}</p>
                </div>
                <div className="p-3 rounded-lg bg-gray-50">
                  <BookOpen className={`w-6 h-6 ${asset.color}`} />
                </div>
              </div>
              <div className="mt-3">
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-gray-600">覆盖度</span>
                  <span className="font-medium">{asset.coverage}%</span>
                </div>
                <Progress value={asset.coverage} className="h-2" />
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Search className="w-5 h-5" />
            RAG 检索测试
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex gap-2">
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="输入知识检索问题"
            />
            <Button onClick={() => setSearched(true)} disabled={!query.trim()}>
              检索
            </Button>
          </div>
          <div className="space-y-3">
            {visibleRagResults.map((result) => (
              <Alert key={result.source}>
                <Search className="h-4 w-4" />
                <AlertTitle className="flex items-center justify-between gap-3">
                  <span>{result.source}</span>
                  <Badge variant="outline">相关度 {(result.score * 100).toFixed(0)}%</Badge>
                </AlertTitle>
                <AlertDescription className="mt-2">{result.summary}</AlertDescription>
              </Alert>
            ))}
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileText className="w-5 h-5" />
              错误码规则解释
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {Object.values(errorCodeKnowledge).map((item) => (
              <Alert key={item.code}>
                <ScrollText className="h-4 w-4" />
                <AlertTitle>
                  {item.code} - {item.description}
                </AlertTitle>
                <AlertDescription>
                  <p className="mt-2 text-sm">可能原因：{item.possibleCauses.slice(0, 2).join('、')}</p>
                  <p className="mt-1 text-sm">处理步骤：{item.handlingSteps.slice(0, 2).join('、')}</p>
                </AlertDescription>
              </Alert>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Brain className="w-5 h-5" />
              DRG/DIP 与提示模板
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {mockDrgRules.map((rule) => (
              <div key={rule.code} className="p-4 bg-gray-50 rounded-lg">
                <div className="flex items-center gap-2">
                  <Badge variant="outline">{rule.code}</Badge>
                  <span className="font-medium">{rule.title}</span>
                </div>
                <p className="text-sm text-gray-600 mt-2">{rule.summary}</p>
              </div>
            ))}
            <div className="border-t pt-4 space-y-2">
              {mockPromptTemplates.map((template) => (
                <div key={template.name} className="flex items-center justify-between gap-3 text-sm">
                  <span>{template.name}</span>
                  <div className="flex gap-2">
                    <Badge variant="outline">{template.scenario}</Badge>
                    <Badge>{template.role}</Badge>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
