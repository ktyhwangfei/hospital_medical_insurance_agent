import { expect, test } from '@playwright/test';
import { PolicyKnowledgePage } from '../../pages/portal/policy-knowledge.page';

const prefix = '**/api/v1/medical-insurance-ai-agent';

test.describe('政策知识工作台与整批发布门禁', () => {
  test('导航顺序固定且 Unit 与 Knowledge 双向保持选中关系', async ({ page }) => {
    await page.route(`${prefix}/semantic/metrics?object_code=zcgz`, (route) => route.fulfill({ json: [] }));
    await page.route(`${prefix}/policy-workbench/documents`, (route) => route.fulfill({ json: { items: [{ doc_id: 'doc_1', doc_title: '职工医保', approved_unit_count: 1, knowledge_count: 1 }] } }));
    await page.route(`${prefix}/policy-workbench/documents/doc_1`, (route) => route.fulfill({ json: {
      doc_id: 'doc_1', doc_title: '职工医保', contract_version: '2', units: [{
        unit_id: 'unit_1', doc_id: 'doc_1', doc_title: '职工医保', path: ['第一条'], source_text: '原文', order_no: 1, status: 'reviewed', knowledge_count: 1,
        knowledge: [{ knowledge_id: 'kn_1', unit_id: 'unit_1', extraction_id: 'ext_1', relationship_source: 'persisted', business_sentence: '支付比例为80%', source_text: '原文', fields: [], standardized_fields: [], confidence: { completeness: 1, accuracy: null, source_fidelity: 1, model_confidence: 0.9, value_domain_compliance: null, overall: 0.9, uncertainties: ['待验证'] }, citations: [{ title: '政策原文', evidence: '第一条' }] }],
      }],
    } }));
    const policy = new PolicyKnowledgePage(page);
    await policy.gotoKnowledge();

    expect((await policy.navLabels()).map((item) => item.trim())).toEqual(['概览', '文档', '单元', '知识', '测试']);
    await expect(policy.unit('unit_1')).toHaveAttribute('aria-selected', 'true');
    await policy.selectKnowledge('kn_1');
    await expect(policy.unit('unit_1')).toHaveAttribute('aria-selected', 'true');
    await expect(policy.knowledge('kn_1')).toHaveAttribute('aria-selected', 'true');
  });

  test('候选版只能整批测试并在人工发布后切换活动版本', async ({ page }) => {
    await page.route(`${prefix}/policy-workbench/test-cases`, (route) => route.fulfill({ json: [] }));
    await page.route(`${prefix}/policy-workbench/releases/active`, (route) => route.fulfill({ json: { release_id: 'baseline', status: 'active', facts_collection: 'facts_baseline', rules_collection: 'rules_baseline', contract_version: '1', case_set_version: 1, config_hash: 'cfg', quality_score: 0.8, consistency_score: 1 } }));
    await page.route(`${prefix}/policy-workbench/releases`, (route) => route.fulfill({ json: [{ release_id: 'candidate', status: 'passed', facts_collection: 'facts_candidate', rules_collection: 'rules_candidate', contract_version: '2', case_set_version: 1, config_hash: 'cfg', quality_score: 0.95, consistency_score: 1 }] }));
    const policy = new PolicyKnowledgePage(page);
    await policy.gotoTest();

    await expect(policy.qualityGate).toBeVisible();
    await expect(policy.publishButton).toBeEnabled();
    await expect(policy.scopedPublishButtons).toHaveCount(0);
  });
});
