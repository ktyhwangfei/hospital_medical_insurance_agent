import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

// 回归测试：Base UI 实际渲染的是 data-orientation="horizontal" 属性，
// Tabs 根节点的布局选择器必须与该属性匹配，否则 flex-col 失效，
// 标签按钮会与内容区左右并排（语义发现页曾出现该 bug）。
describe('Tabs 布局', () => {
  it('horizontal 方向时根节点选择器匹配 data-orientation 实现上下布局', () => {
    const { container } = render(
      <Tabs defaultValue="a">
        <TabsList>
          <TabsTrigger value="a">标签A</TabsTrigger>
          <TabsTrigger value="b">标签B</TabsTrigger>
        </TabsList>
        <TabsContent value="a">内容A</TabsContent>
        <TabsContent value="b">内容B</TabsContent>
      </Tabs>,
    )
    const root = container.querySelector('[data-slot="tabs"]')
    expect(root).not.toBeNull()
    // Base UI 输出的真实属性
    expect(root?.getAttribute('data-orientation')).toBe('horizontal')
    // 类名中的选择器必须引用该属性，才能让 flex-col 生效
    expect(root?.className).toContain('data-[orientation=horizontal]:flex-col')
  })
})
