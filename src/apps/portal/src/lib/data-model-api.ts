// 数据模型建模 API 客户端 — 数据治理中心 · 数据建模（V3.0 §4）
// 字段与后端 src/domain/data_model/models.py 逐字段对齐（snake_case 直传）。
import { dataGovernanceRequest } from './data-governance-api'

export type DataModelLayer = 'ods' | 'dwd' | 'dws' | 'ads'
export type DataModelStatus = 'draft' | 'published' | 'deprecated'
export type ModelFieldRole = 'identifier' | 'dimension' | 'fact' | 'datetime'
export type MappingStatus = 'draft' | 'confirmed'

export interface DataModelField {
  field_code: string
  name: string
  data_type: string
  field_role: ModelFieldRole
  value_domain?: string | null
  expression?: string | null
  dependencies?: string[]
}

export interface DataModel {
  model_code: string
  name: string
  layer: DataModelLayer
  grain: string
  entity_code: string
  status: DataModelStatus
  owner: string
  description: string
  fields: DataModelField[]
  version: number
  revision: number
  content_hash?: string
  created_at?: string | null
  updated_at?: string | null
}

export interface DataModelMapping {
  model_code: string
  field_code: string
  source_id: string
  physical_table: string
  physical_column: string
  transform_rule?: string | null
  status: MappingStatus
  revision: number
  updated_at?: string | null
}

export const listDataModels = () => dataGovernanceRequest<DataModel[]>('/models')

export const getDataModel = (code: string) =>
  dataGovernanceRequest<DataModel>(`/models/${encodeURIComponent(code)}`)

export const createDataModel = (model: Partial<DataModel>) =>
  dataGovernanceRequest<DataModel>('/models', { method: 'POST', body: JSON.stringify(model) })

export const updateDataModel = (model: DataModel) =>
  dataGovernanceRequest<DataModel>(
    `/models/${encodeURIComponent(model.model_code)}?expected_revision=${model.revision}`,
    { method: 'PUT', body: JSON.stringify(model) },
  )

export const publishDataModel = (code: string) =>
  dataGovernanceRequest<DataModel>(`/models/${encodeURIComponent(code)}/publish`, { method: 'POST' })

export const deprecateDataModel = (code: string) =>
  dataGovernanceRequest<DataModel>(`/models/${encodeURIComponent(code)}/deprecate`, { method: 'POST' })

export const listDataModelMappings = (code: string) =>
  dataGovernanceRequest<DataModelMapping[]>(`/models/${encodeURIComponent(code)}/mappings`)

export const saveDataModelMapping = (mapping: Partial<DataModelMapping> & { model_code: string }) =>
  dataGovernanceRequest<DataModelMapping>(
    `/models/${encodeURIComponent(mapping.model_code)}/mappings`,
    { method: 'PUT', body: JSON.stringify(mapping) },
  )

export const confirmDataModelMapping = (modelCode: string, fieldCode: string, sourceId: string) =>
  dataGovernanceRequest<DataModelMapping>(
    `/models/${encodeURIComponent(modelCode)}/mappings/${encodeURIComponent(fieldCode)}/${encodeURIComponent(sourceId)}/confirm`,
    { method: 'POST' },
  )
