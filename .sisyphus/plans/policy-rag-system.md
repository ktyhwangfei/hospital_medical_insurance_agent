# 医保政策问答RAG系统设计与实现计划

> **计划状态**: 设计阶段 - 待用户确认
> **创建时间**: 2026-05-28
> **基于探索结果**: 4个并行探索任务已完成

---

## 0. 现有系统分析摘要

### 0.1 已有能力（可复用）

| 模块 | 能力 | 位置 |
|------|------|------|
| **MilvusPolicyRetriever** | 双集合向量检索(policy_nodes + policy_facts) | `src/knowledge_extension/rule_explanation/policy_retrieval/milvus_retriever.py` |
| **RuleBasedReranker** | 多维权重排序(事实类型/医院等级/住院次数) | `src/knowledge_extension/rule_explanation/policy_retrieval/reranker.py` |
| **QueryUnderstanding** | 自然语言查询解析(意图/实体/过滤条件) | `src/knowledge_extension/rule_explanation/policy_retrieval/query_understanding.py` |
| **ExplanationPlanner** | 起付线计算解释链生成 | `src/knowledge_extension/rule_explanation/policy_retrieval/explanation_planner.py` |
| **SemanticMapper** | 业务字段→政策语义字段映射 | `src/knowledge_extension/rule_explanation/policy_retrieval/semantic_mapping.py` |
| **domain_definitions.py** | 9大值域体系(693行) | `src/knowledge_extension/rule_explanation/policy_extract/domain_definitions.py` |
| **SSE流式框架** | 完整的SSE事件流(stream:start→step→delta→final→done) | `src/runtime/api/streaming.py` + `src/runtime/api/streaming_emitter.py` |
| **settlement-chat.tsx** | 生产级Chat组件(含SSE流式、思维链、打字机) | `src/apps/portal/src/components/settlement-chat.tsx` |

### 0.2 核心缺失（需新建）

| 缺失项 | 说明 | 优先级 |
|--------|------|--------|
| **PolicyRule领域模型** | xlsx有19个字段，现有领域模型仅覆盖3个 | 高 |
| **数据模型1入库** | 需要将xlsx数据导入Milvus | 高 |
| **意图识别LLM集成** | 当前query_understanding是规则匹配，需增强为LLM | 中 |
| **解释生成LLM润色** | 当前ExplanationPlanner是模板化，需LLM自然语言润色 | 中 |
| **前端政策问答组件** | 需要基于v3-prototype创建政策问答专用组件 | 高 |
| **policy_rules表** | PostgreSQL中无此表 | 高 |
| **value_domains表** | 值域枚举表 | 中 |

### 0.3 架构约束

- **大模型只负责意图识别和解释生成**，中间过程（检索、排序、计算）由代码完成
- **中间过程需要一步一步来**，前端思维链展示每个步骤的状态
- **向量搜索 + 高级搜索** 两种模式并存
- **knowledge_extension不直接调用model_service**，两者在runtime层组合

---

## 0. 现有系统分析摘要

### 0.1 已有能力（可复用）

| 模块 | 能力 | 关键文件 |
|------|------|----------|
| **MilvusPolicyRetriever** | 双集合检索(policy_nodes + policy_facts)、标量过滤、知识组扩展 | `milvus_retriever.py` |
| **QueryUnderstanding** | 自然语言→SearchQuery(意图、实体、过滤条件) | `query_understanding.py` |
| **RuleBasedReranker** | 多维度评分排序(事实类型/医院等级/住院次数等) | `reranker.py` |
| **ExplanationPlanner** | 起付线计算解释链(规则引擎，非LLM) | `explanation_planner.py` |
| **SemanticMapper** | 业务字段→政策语义字段映射(配置驱动) | `semantic_mapping.py` + `config/semantic_mapping.yaml` |
| **SSE流式框架** | 完整SSE事件格式化(stream:start/step/delta/final/done) | `runtime/api/streaming.py` |
| **前端Chat组件** | settlement-chat.tsx + ExecutionTimeline + IntentTraceCard | `portal/src/components/` |
| **domain_definitions.py** | 9大值域体系(险种/人群/医院等级/医疗类别/结算方式等) | `policy_extract/domain_definitions.py` |

### 0.2 需要新增的部分

| 模块 | 需要做什么 |
|------|-----------|
| **数据入库** | 将`raw/数据模型1.xlsx`导入Milvus(新增`policy_rules`集合或复用`policy_facts`) |
| **意图识别LLM** | 当前`query_understanding.py`是规则匹配，需增加LLM意图识别路径 |
| **解释生成NLG** | 当前ExplanationPlanner输出模板化文本，需LLM润色为自然语言 |
| **SSE编排器** | 新增PolicyQAOrchestrator，将上述模块串联为5步SSE流 |
| **前端政策问答** | 基于v3-prototype创建PolicyQAChat组件，对接SSE流 |
| **API端点** | 新增`/policy-qa/stream`端点 |

### 0.3 关键设计约束

1. **大模型只负责意图识别和最终解释**，中间检索/排序/计算由代码完成
2. **中间过程必须一步一步来**，前端实时展示每步状态
3. **双搜索模式**：向量搜索(语义) + 高级搜索(标量过滤)
4. **不重复造轮子**：复用现有MilvusPolicyRetriever和RuleBasedReranker

---

## 1. 项目概述

### 1.1 目标
基于v3-prototype前端界面，构建完整的医保政策问答RAG系统，支持：
- 向量搜索（语义检索）
- 高级搜索（基于数据模型1.xlsx的结构化查询）
- 大模型意图识别
- 逐步推理过程展示
- 自然语言解释生成

### 1.2 核心场景
用户输入："三级医院在职职工住院起付线是多少？"

系统响应：
1. **意图识别** → 识别为"政策查询"
2. **查询理解** → 提取关键实体：医院等级=三级，人群=在职，场景=住院，查询类型=起付线
3. **向量检索** → 从Milvus检索相关政策节点
4. **高级检索** → 基于标量过滤检索结构化事实
5. **重排序** → 对检索结果进行相关性排序
6. **解释生成** → 使用大模型生成自然语言解释
7. **结果展示** → 在前端展示思维链和导办卡片

---

## 1.5 用户确认的关键决策

| 决策项 | 选择 | 说明 |
|--------|------|------|
| **Milvus集合** | 新建policy_rules集合 | 保持现有policy_nodes和policy_facts不变 |
| **前端方案** | 创建独立PolicyQAChat组件 | 放在portal/src/components/policy-qa/，不影响现有结算导办 |
| **LLM流式** | 意图识别非流式+解释生成流式 | 意图需完整结果才能继续，解释用流式+打字机效果 |

---

## 1.6 关键技术决策

基于探索结果，确定以下决策：

| 决策 | 选择 | 理由 |
|------|------|------|
| **前端方案** | 复用settlement-chat.tsx + 新增PolicyQAChat组件 | 生产组件已有完整SSE流式集成，v3-prototype仅作设计参考 |
| **检索引擎** | 复用MilvusPolicyRetriever + 扩展数据模型1 | 已有双集合(policy_nodes+policy_facts)混合检索，无需重建 |
| **重排序** | 复用RuleBasedReranker | 已有12维业务权重重排，适配政策查询 |
| **意图识别** | 通过model_service调用LLM | knowledge_extension不直接调用model_service，在runtime层组合 |
| **解释生成** | ExplanationPlanner(计算) + LLM(润色) | 遵循"大模型只负责解释，不决定金额"原则 |
| **数据入库** | 扩展milvus_ingest.py支持数据模型1 | 已有Excel→Milvus管道，增加新Schema即可 |
| **Milvus端口** | 19121 (production.py配置) | 不是默认19530 |

---

## 2. 系统架构

### 2.1 整体架构
```
┌─────────────────────────────────────────────────────────────┐
│                    前端 (Next.js Portal)                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ Chat界面    │  │ 思维链卡片  │  │ 导办结果卡片        │  │
│  │ (v3风格)    │  │ (5步骤)     │  │ (结构化展示)        │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    后端 API (FastAPI)                         │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ /api/v1/medical-insurance-ai-agent/chat/stream (SSE)    │ │
│  └─────────────────────────────────────────────────────────┘ │
│                           │                                   │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │              PolicyQAOrchestrator (编排器)               │ │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────────┐  │ │
│  │  │ 意图    │→│ 查询    │→│ 检索    │→│ 解释        │  │ │
│  │  │ 识别    │ │ 理解    │ │ 引擎    │ │ 生成        │  │ │
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────────┘  │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│ Milvus向量库  │    │ PostgreSQL    │    │ Model Service │
│ (语义检索)    │    │ (结构化数据)  │    │ (大模型)      │
└───────────────┘    └───────────────┘    └───────────────┘
```

### 2.2 数据流
```
用户输入 → 意图识别 → 查询理解 → 检索策略选择
                                    ├─ 向量检索 (Milvus policy_nodes)
                                    ├─ 高级检索 (Milvus policy_facts + 标量过滤)
                                    └─ 混合检索 (向量+标量)
                                         │
                                         ▼
                                    重排序 → 证据组装 → 大模型解释 → 流式返回
```

---

## 3. 前端改造

### 3.1 改造目标
将v3-prototype集成到Next.js应用，支持：
- 动态消息渲染（非硬编码）
- SSE流式接收
- 思维链步骤动态更新
- 导办卡片动态生成

### 3.2 组件设计
```typescript
// 1. PolicyQAChat - 政策问答主组件
interface PolicyQAChatProps {
  sessionId: string;
}

// 2. ThinkingChainStep - 思维链步骤
interface ThinkingChainStepProps {
  stepNumber: number;
  stepType: 'intent' | 'query' | 'search' | 'rerank' | 'explain';
  status: 'pending' | 'running' | 'done';
  detail: string;
  duration: number;
}

// 3. PolicyAnswerCard - 政策答案卡片
interface PolicyAnswerCardProps {
  answer: string;
  citations: Citation[];
  confidence: number;
  ruleDetails?: RuleDetail[];
}

// 4. Citation - 引用来源
interface Citation {
  policyTitle: string;
  clauseText: string;
  policyNo: string;
  publishDate: string;
}
```

### 3.3 API集成
```typescript
// src/lib/api-client.ts 新增
export async function streamPolicyQA(
  question: string,
  onStep: (step: ThinkingStep) => void,
  onAnswer: (chunk: string) => void,
  onComplete: (result: PolicyQAResult) => void
): Promise<void> {
  const response = await fetch('/api/v1/medical-insurance-ai-agent/policy-qa/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question })
  });
  
  // SSE解析逻辑
}
```

---

## 4. 后端实现

### 4.1 新增模块结构
```
src/runtime/policy_qa/
├── __init__.py
├── orchestrator.py      # 编排器 - 协调各步骤
├── intent_detector.py   # 意图识别
├── query_analyzer.py    # 查询理解与实体提取
├── search_engine.py     # 检索引擎（封装MilvusRetriever）
├── reranker.py          # 重排序
├── explanation.py       # 解释生成
└── models.py            # 数据模型
```

### 4.2 核心接口
```python
# src/runtime/policy_qa/orchestrator.py
class PolicyQAOrchestrator:
    """政策问答编排器"""
    
    async def stream_qa(
        self,
        question: str,
        session_id: str
    ) -> AsyncGenerator[PolicyQAEvent, None]:
        """
        流式政策问答
        
        Yields:
            PolicyQAEvent: 包含思维链步骤和最终答案
        """
        # Step 1: 意图识别
        yield PolicyQAEvent(step="intent", status="running")
        intent = await self.intent_detector.detect(question)
        yield PolicyQAEvent(step="intent", status="done", detail=intent)
        
        # Step 2: 查询理解
        yield PolicyQAEvent(step="query", status="running")
        search_query = await self.query_analyzer.analyze(question, intent)
        yield PolicyQAEvent(step="query", status="done", detail=search_query)
        
        # Step 3: 检索
        yield PolicyQAEvent(step="search", status="running")
        search_results = await self.search_engine.search(search_query)
        yield PolicyQAEvent(step="search", status="done", detail=len(search_results))
        
        # Step 4: 重排序
        yield PolicyQAEvent(step="rerank", status="running")
        ranked_results = await self.reranker.rerank(question, search_results)
        yield PolicyQAEvent(step="rerank", status="done", detail=len(ranked_results))
        
        # Step 5: 解释生成
        yield PolicyQAEvent(step="explain", status="running")
        async for chunk in self.explanation.generate_stream(question, ranked_results):
            yield PolicyQAEvent(step="explain", status="streaming", chunk=chunk)
        yield PolicyQAEvent(step="explain", status="done")
```

### 4.3 API端点
```python
# src/runtime/api/routes.py 新增
@router.post("/policy-qa/stream")
async def stream_policy_qa(
    request: PolicyQARequest,
    session_id: str = Header(...)
):
    """流式政策问答"""
    async def event_generator():
        async for event in orchestrator.stream_qa(request.question, session_id):
            yield f"data: {event.json()}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )
```

---

## 5. 数据入库

### 5.1 数据模型1.xlsx结构
```
政策规则表 (19字段):
├── rule_id, fact_id, policy_id, clause_id (标识)
├── source_text (原始政策文本)
├── insu_type (险种类别): 城镇职工、城乡居民、超转人员、生育保险
├── med_type (医疗类别): 住院-普通住院、门诊-一般门特
├── hosp_lv (医疗机构等级): 一级医院、二级医院、三级医院、社区
├── psn_type (人群标签): 退休、在职、70岁以上、学生儿童
├── setl_type (结算方式): 按项目付费、DRG、单病种、床日定额
├── payment_ratio (支付比例)
├── deductible_amount (起付金额)
├── cap_amount (封顶金额)
├── time_period (时间周期)
├── admission_order (住院次数)
├── rule_type (规则类型)
├── rule_value (规则值)
├── amount_band (金额分段)
└── priority (规则优先级)
```

### 5.2 入库策略
```python
# src/knowledge_extension/rule_explanation/policy_retrieval/excel_loader.py 扩展
class DataModel1Loader:
    """数据模型1.xlsx加载器"""
    
    def load_to_milvus(
        self,
        excel_path: str,
        collection_name: str = "policy_rules"
    ):
        """
        将数据模型1加载到Milvus
        
        映射关系:
        - insu_type → insurance_type
        - med_type → service_type
        - hosp_lv → hospital_level
        - psn_type → population
        - deductible_amount → amount
        - payment_ratio → ratio
        """
        df = pd.read_excel(excel_path, sheet_name='政策规则表')
        
        for _, row in df.iterrows():
            fact = self._row_to_policy_fact(row)
            self._insert_to_milvus(fact)
```

### 5.3 Milvus Schema扩展
```python
# 新增 policy_rules collection
POLICY_RULES_SCHEMA = CollectionSchema([
    FieldSchema("rule_id", DataType.VARCHAR, max_length=64, is_primary=True),
    FieldSchema("embedding", DataType.FLOAT_VECTOR, dim=768),
    FieldSchema("insurance_type", DataType.VARCHAR, max_length=32),
    FieldSchema("service_type", DataType.VARCHAR, max_length=32),
    FieldSchema("hospital_level", DataType.VARCHAR, max_length=32),
    FieldSchema("population", DataType.VARCHAR, max_length=32),
    FieldSchema("deductible_amount", DataType.FLOAT),
    FieldSchema("payment_ratio", DataType.FLOAT),
    FieldSchema("cap_amount", DataType.FLOAT),
    FieldSchema("rule_type", DataType.VARCHAR, max_length=64),
    FieldSchema("rule_value", DataType.VARCHAR, max_length=256),
    FieldSchema("source_text", DataType.VARCHAR, max_length=4096),
])
```

---

## 6. 检索策略

### 6.1 三阶段检索
```python
class PolicySearchEngine:
    """政策检索引擎"""
    
    async def search(
        self,
        query: SearchQuery
    ) -> list[SearchResult]:
        """
        三阶段检索:
        1. 向量检索 - 语义相似度
        2. 高级检索 - 标量过滤
        3. 混合检索 - 合并去重
        """
        # 阶段1: 向量检索
        vector_results = await self.milvus_retriever.search_nodes(
            query=query.question_embedding,
            top_k=10
        )
        
        # 阶段2: 高级检索 (标量过滤)
        filter_expr = self._build_filter_expr(query)
        filter_results = await self.milvus_retriever.search_facts(
            query=query.question_embedding,
            expr=filter_expr,
            top_k=10
        )
        
        # 阶段3: 混合并集
        merged = self._merge_results(vector_results, filter_results)
        
        return merged
    
    def _build_filter_expr(self, query: SearchQuery) -> str:
        """构建Milvus标量过滤表达式"""
        parts = []
        
        if query.insurance_type:
            parts.append(f'insurance_type == "{query.insurance_type}"')
        if query.hospital_level:
            parts.append(f'hospital_level == "{query.hospital_level}"')
        if query.population:
            parts.append(f'population == "{query.population}"')
        
        return " and ".join(parts) if parts else ""
```

### 6.2 查询理解
```python
class QueryAnalyzer:
    """查询分析器 - 提取结构化查询参数"""
    
    async def analyze(
        self,
        question: str,
        intent: Intent
    ) -> SearchQuery:
        """
        分析用户查询，提取:
        - insurance_type (险种)
        - hospital_level (医院等级)
        - population (人群)
        - service_type (医疗类别)
        - 查询目标 (起付线/报销比例/封顶线)
        """
        # 使用LLM提取实体
        entities = await self.llm_extract_entities(question)
        
        return SearchQuery(
            question=question,
            insurance_type=entities.get("insurance_type"),
            hospital_level=entities.get("hospital_level"),
            population=entities.get("population"),
            service_type=entities.get("service_type"),
            target_field=entities.get("target_field")
        )
```

---

## 7. 大模型集成

### 7.1 意图识别
```python
INTENT_PROMPT = """
你是一个医保政策问答系统的意图识别模块。

用户输入: {question}

请识别用户意图，返回JSON格式:
{{
  "intent": "policy_qa|settlement_guide|qc_check|drg_analysis",
  "confidence": 0.95,
  "entities": {{
    "insurance_type": "城镇职工|城乡居民|...",
    "hospital_level": "三级|二级|一级|社区",
    "population": "在职|退休|...",
    "service_type": "住院|门诊",
    "target": "起付线|报销比例|封顶线|..."
  }}
}}

只返回JSON，不要其他内容。
"""
```

### 7.2 解释生成
```python
EXPLANATION_PROMPT = """
你是一个医保政策解释专家。

用户问题: {question}

检索到的政策依据:
{evidence}

请生成清晰、准确的解释，要求:
1. 直接回答问题
2. 列出关键数据（起付线、比例、金额等）
3. 说明适用条件
4. 引用政策来源

使用Markdown格式，关键数据用**加粗**。
"""
```

---

## 8. 任务拆分

### Phase 1: 数据准备 (2天)
- [ ] 1.1 解析数据模型1.xlsx，设计policy_rules集合Schema
- [ ] 1.2 实现DataModel1Loader数据加载器
- [ ] 1.3 将政策规则数据导入Milvus
- [ ] 1.4 验证向量检索+标量过滤

### Phase 2: 后端核心 (3天)
- [ ] 2.1 新增`runtime/policy_qa/`模块
- [ ] 2.2 实现PolicyQAOrchestrator编排器(串联意图→查询→检索→排序→解释)
- [ ] 2.3 实现SSE流式API端点`/policy-qa/stream`
- [ ] 2.4 集成model_service做意图识别Prompt
- [ ] 2.5 集成model_service做解释生成NLG润色

### Phase 3: 前端改造 (2天)
- [ ] 3.1 将v3-prototype样式迁移到React组件
- [ ] 3.2 实现PolicyQAChat主组件
- [ ] 3.3 实现SSE流式接收和思维链动态更新
- [ ] 3.4 实现PolicyAnswerCard答案卡片
- [ ] 3.5 集成到portal应用路由

### Phase 4: 集成测试 (1天)
- [ ] 4.1 端到端功能测试
- [ ] 4.2 性能优化
- [ ] 4.3 边界case处理

---

## 8.5 现有代码复用清单

基于探索结果，以下是可直接复用的现有代码：

| 组件 | 文件路径 | 复用方式 |
|------|----------|----------|
| **MilvusPolicyRetriever** | `src/knowledge_extension/rule_explanation/policy_retrieval/milvus_retriever.py` | 直接注入SearchEngine |
| **RuleBasedReranker** | `src/knowledge_extension/rule_explanation/policy_retrieval/reranker.py` | 直接使用 |
| **ExplanationPlanner** | `src/knowledge_extension/rule_explanation/policy_retrieval/explanation_planner.py` | 扩展支持更多规则类型 |
| **QueryUnderstanding** | `src/knowledge_extension/rule_explanation/policy_retrieval/query_understanding.py` | 直接使用 |
| **SemanticMapper** | `src/knowledge_extension/rule_explanation/policy_retrieval/semantic_mapping.py` | 直接使用 |
| **EmbeddingProvider** | `src/knowledge_extension/rule_explanation/policy_retrieval/embedding_provider.py` | 直接使用 |
| **domain_definitions.py** | `src/knowledge_extension/rule_explanation/policy_extract/domain_definitions.py` | 值域映射参考 |
| **SSE框架** | `src/runtime/api/streaming.py` + `streaming_emitter.py` | 直接使用 |
| **settlement-chat.tsx** | `src/apps/portal/src/components/settlement-chat.tsx` | 参考结构，新增PolicyQAChat |
| **ExecutionTimeline** | `src/apps/portal/src/components/chat/execution-timeline.tsx` | 直接复用 |
| **Typewriter** | `src/apps/portal/src/components/chat/typewriter.tsx` | 直接复用 |
| **api-client.ts** | `src/apps/portal/src/lib/api-client.ts` | 新增端点函数 |
| **sse-hooks.ts** | `src/apps/portal/src/lib/sse-hooks.ts` | 新增usePolicyQAStream |

---

## 9. 技术风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| Milvus检索延迟高 | 用户体验差 | 1. 使用缓存 2. 限制top_k 3. 异步并行检索 |
| 大模型响应慢 | 思维链卡顿 | 1. 流式输出 2. 并行调用 3. 超时降级 |
| 数据模型映射复杂 | 入库困难 | 1. 分阶段入库 2. 先核心字段后扩展 |
| 意图识别不准 | 检索偏差 | 1. 多轮澄清 2. 意图确认 3. 降级到关键词 |

---

## 10. 验收标准

### 10.1 功能验收
- [ ] 用户输入政策问题，系统正确识别意图
- [ ] 系统展示5步思维链，每步状态实时更新
- [ ] 系统返回准确的政策答案，包含引用来源
- [ ] 支持向量搜索和高级搜索两种模式
- [ ] 流式输出，响应时间<3秒

### 10.2 测试用例
```
输入: "三级医院在职职工住院起付线是多少？"
期望: 
- 意图: policy_qa
- 实体: hospital_level=三级, population=在职, service_type=住院
- 答案: 包含1300元起付线
- 引用: 北京市医保政策文件

输入: "为什么我的起付线是1950？"
期望:
- 意图: policy_qa (解释型)
- 答案: 解释第二次住院减半规则
- 计算过程: 1300 * 1.5 = 1950
```

---

## 11. 参考资源

### 现有代码
- `src/knowledge_extension/rule_explanation/policy_retrieval/` - RAG检索模块
- `src/apps/portal/public/chat-v3-prototype.html` - 前端原型
- `src/model_service/` - 大模型服务
- `src/runtime/api/` - API框架

### 数据文件
- `raw/数据模型1.xlsx` - 政策规则数据模型
- `raw/北京市医保局政策文件.xlsx` - 政策原文
- `raw/policy_nodes.xlsx` - 政策节点
- `raw/policy_facts.xlsx` - 政策事实

### 外部依赖
- Milvus 2.x - 向量数据库
- PostgreSQL - 关系数据库
- OpenAI兼容模型 - 大模型服务
