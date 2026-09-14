import { requestJson } from './api-client'

export interface PolicyDocumentContent {
  doc_id: string
  title: string
  content_text: string
  source_url: string
  issuing_agency: string
  publish_date: string
  validity: string
}

export async function getPolicyDocumentContent(docId: string): Promise<PolicyDocumentContent> {
  return requestJson<PolicyDocumentContent>(
    `/policy-workbench/documents/${encodeURIComponent(docId)}/content`,
  )
}
