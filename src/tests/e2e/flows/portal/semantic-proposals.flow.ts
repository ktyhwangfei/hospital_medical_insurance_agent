import { expect, test } from '@playwright/test';
import { SemanticProposalsPage } from '../../pages/portal/semantic-proposals.page';

const proposal = {
  proposal_id: 'proposal-e2e', fingerprint: 'fingerprint-e2e', proposal_type: 'metric',
  trigger_source: 'EXTRACTION_UNKNOWN', status: 'proposed', concept: '大额互助起付标准',
  object_code: 'zcgz', axis_metric_code: null,
  metric_draft: {
    metric_code: 'mutual_aid_deductible', object_code: 'zcgz', name: '大额互助起付标准',
    definition: '大额互助的起付金额', metric_type: 'Atomic', semantic_type: 'Amount', unit: '元',
    value_domain: null, metric_kind: 'field', indexed: true, extraction_hint: null, schema_version: 1,
  },
  value_draft: null, suggested_mappings: [], mapping_only: false, formula: null,
  evidence: [{
    source_ref: 'policy-extraction:doc-e2e:unit-e2e:concept', excerpt: '大额互助起付标准为 1200 元',
    doc_id: 'doc-e2e', unit_id: 'unit-e2e', extraction_id: 'ext-e2e', occurrence_count: 1,
  }],
  confidence: 0.9, occurrence_count: 1, reviewed_by: null, reviewed_at: null, review_note: null,
  created_at: '2026-08-12T00:00:00Z', updated_at: '2026-08-12T00:00:00Z',
};

test('政策未知概念可在提议页审阅并发布', async ({ page }) => {
  let status = 'proposed';
  const actions: string[] = [];
  await page.route('**/api/v1/medical-insurance-ai-agent/semantic/alignment/proposals**', async (route) => {
    const url = route.request().url();
    if (route.request().method() === 'GET') {
      return route.fulfill({ json: url.includes('proposal_type=metric') ? [{ ...proposal, status }] : [] });
    }
    const action = url.split('/').pop() ?? '';
    actions.push(action);
    status = action === 'review' ? 'reviewing' : action === 'accept' ? 'accepted' : 'published';
    return route.fulfill({ json: { ...proposal, status, reviewed_by: 'reviewer-e2e' } });
  });

  const proposals = new SemanticProposalsPage(page);
  await proposals.goto();

  await expect(proposals.metricTab).toHaveAttribute('aria-selected', 'true');
  await expect(proposals.proposalCode('mutual_aid_deductible')).toBeVisible();
  await proposals.expandEvidence('mutual_aid_deductible');
  await expect(proposals.evidence('大额互助起付标准为 1200 元')).toHaveCount(2);
  await proposals.acceptAndPublish('mutual_aid_deductible');

  await expect(proposals.publishedStatus).toBeVisible();
  await expect(proposals.successStatus).toContainText('已通过并发布');
  expect(actions).toEqual(['review', 'accept', 'publish']);
});
