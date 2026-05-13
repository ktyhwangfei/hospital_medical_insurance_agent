# 工作计划：将硬编码测试数据迁移到数据库

## 概述

将前端和后端中硬编码的测试数据存入数据库，走正式流程进行查询。

## 硬编码数据清单

### 1. 患者和交易数据
**位置**: `src/data_platform/data_access/in_memory.py`
```python
patients={'P001': Patient(patient_id='P001', name='张三')}
transactions={
    ('P001', 'E001'): InsuranceTransaction(
        patient_id='P001', encounter_id='E001',
        settlement_status='failed', upload_status='failed',
        error_code='E-UPLOAD-001',
    )
}
```

### 2. 错误码知识库
**位置**: `src/knowledge_extension/knowledge/in_memory.py`
```python
ERROR_CODE_KNOWLEDGE = {
    'E-UPLOAD-001': {
        'description': '费用明细未全部上传',
        'exception_type': '费用上传异常',
        'responsible_role': '收费员',
        'recommendation': '请核对费用上传状态，补传失败明细后重新预结算。',
    }
}
```

### 3. 知识资产
**位置**: `src/knowledge_extension/assets/in_memory.py`
- 6个知识资产 (asset-policy-001, asset-error-code-001, etc.)
- 2个知识切片 (chunk-policy-001, chunk-rule-001)

### 4. 前端Mock数据
**位置**: `prototype/src/lib/mock-data.ts`
- Mock AI 响应
- Mock MCP 服务器
- Mock 模型测试结果

## 实施计划

### Wave 1: 创建数据库表结构

**任务1.1**: 患者和交易表
- 创建 `patients` 表
- 创建 `insurance_transactions` 表
- 创建种子数据加载函数

**任务1.2**: 错误码知识表
- 创建 `error_code_knowledge` 表
- 创建种子数据加载函数

**任务1.3**: 知识资产表
- 创建 `knowledge_assets` 表
- 创建 `knowledge_chunks` 表
- 创建种子数据加载函数

### Wave 2: 实现数据库存储

**任务2.1**: 患者数据访问
- 创建 `src/data_platform/data_access/postgres.py`
- 实现 `PostgresDataStore` 类
- 修改 factory 使用 PostgreSQL

**任务2.2**: 错误码知识存储
- 创建 `src/knowledge_extension/knowledge/postgres.py`
- 实现 `PostgresKnowledgeStore` 类

**任务2.3**: 知识资产存储
- 检查现有 `src/knowledge_extension/assets/` 实现
- 确保使用 PostgreSQL

### Wave 3: 更新种子数据加载

**任务3.1**: 统一种子数据加载
- 修改 `src/runtime/api/app.py` 的 lifespan
- 在启动时加载所有种子数据到数据库

**任务3.2**: 前端数据对接
- 确保前端 API 调用使用正式流程
- 移除 mock 降级（可选）

### Wave 4: 测试验证

**任务4.1**: 运行测试
- 确保所有测试通过
- 验证数据库查询正常工作

## 依赖关系

```
Wave 1 (表结构) → Wave 2 (存储实现) → Wave 3 (种子数据) → Wave 4 (测试)
```
