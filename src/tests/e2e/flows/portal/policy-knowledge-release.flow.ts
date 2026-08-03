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
    let candidateStatus = 'ready';
    let activeId = 'baseline';
    const release = (release_id: string, status: string) => ({ release_id, status, facts_collection: `facts_${release_id}`, rules_collection: `rules_${release_id}`, contract_version: '2', case_set_version: 1, config_hash: 'cfg', quality_score: status === 'passed' ? 0.95 : null, consistency_score: status === 'passed' ? 1 : null });
    await page.route(`${prefix}/policy-workbench/**`, async (route) => {
      const url = route.request().url();
      const method = route.request().method();
      if (url.endsWith('/test-cases')) return route.fulfill({ json: [] });
      if (url.endsWith('/releases/candidate/quality/latest')) return route.fulfill({ status: 404, json: { detail: '尚无运行' } });
      if (url.endsWith('/releases/candidate/test') && method === 'POST') {
        candidateStatus = 'passed';
        return route.fulfill({ json: { run_id: 'run_1', release_id: 'candidate', baseline_release_id: 'baseline', case_set_version: 1, config_hash: 'cfg', repeat_count: 3, status: 'passed', candidate_score: 0.95, baseline_score: 0.8, consistency_score: 1, blocked_reasons: [] } });
      }
      if (url.endsWith('/quality-runs/run_1/case-results')) return route.fulfill({ json: [{ run_id: 'run_1', target: 'candidate', case_id: 'case_1', repeat_index: 0, result_knowledge_ids: ['kn_1'], score: 1, passed: true, diagnostics: { rank_score: 1 } }, { run_id: 'run_1', target: 'baseline', case_id: 'case_1', repeat_index: 0, result_knowledge_ids: [], score: 0, passed: false, diagnostics: { rank_score: 0 } }] });
      if (url.endsWith('/releases/candidate/promote') && method === 'POST') { activeId = 'candidate'; candidateStatus = 'active'; return route.fulfill({ json: release('candidate', 'active') }); }
      if (url.endsWith('/releases/active')) return route.fulfill({ json: release(activeId, 'active') });
      if (url.endsWith('/releases')) return route.fulfill({ json: [release('candidate', candidateStatus), release('baseline', activeId === 'baseline' ? 'active' : 'retired')] });
      return route.fallback();
    });
    const policy = new PolicyKnowledgePage(page);
    await policy.gotoTest();

    await expect(policy.qualityGate).toBeVisible();
    await expect(policy.publishButton).toBeDisabled();
    await policy.runCandidate();
    await expect(policy.publishButton).toBeEnabled();
    page.on('dialog', (dialog) => dialog.accept(dialog.type() === 'prompt' ? 'reviewer_e2e' : undefined));
    await policy.publishCandidate();
    await expect(policy.activeReleaseCard).toContainText('candidate');
    await expect(policy.scopedPublishButtons).toHaveCount(0);
  });

  test('blocked 候选禁止发布且可整批回滚到退役版本', async ({ page }) => {
    let activeId = 'baseline';
    const release = (release_id: string, status: string) => ({ release_id, status, facts_collection: `facts_${release_id}`, rules_collection: `rules_${release_id}`, contract_version: '2', case_set_version: 1, config_hash: 'cfg', quality_score: null, consistency_score: null });
    await page.route(`${prefix}/policy-workbench/**`, async (route) => {
      const url = route.request().url();
      const method = route.request().method();
      if (url.endsWith('/test-cases')) return route.fulfill({ json: [] });
      if (url.endsWith('/releases/candidate/quality/latest')) return route.fulfill({ json: { run: { run_id: 'run_failed', release_id: 'candidate', baseline_release_id: 'baseline', case_set_version: 1, config_hash: 'cfg', repeat_count: 3, status: 'failed', candidate_score: 0.5, baseline_score: 0.8, consistency_score: 0.5, blocked_reasons: ['重复运行一致性低于门槛'] }, case_results: [] } });
      if (url.endsWith('/releases/previous/rollback') && method === 'POST') { activeId = 'previous'; return route.fulfill({ json: release('previous', 'active') }); }
      if (url.endsWith('/releases/active')) return route.fulfill({ json: release(activeId, 'active') });
      if (url.endsWith('/releases')) return route.fulfill({ json: [release('candidate', 'failed'), release('baseline', activeId === 'baseline' ? 'active' : 'retired'), release('previous', activeId === 'previous' ? 'active' : 'retired')] });
      return route.fallback();
    });
    const policy = new PolicyKnowledgePage(page);
    await policy.gotoTest();

    await expect(policy.blockedReason('重复运行一致性低于门槛')).toBeVisible();
    await expect(policy.publishButton).toBeDisabled();
    page.on('dialog', (dialog) => dialog.accept(dialog.type() === 'prompt' ? 'reviewer_e2e' : undefined));
    await policy.rollbackButton('previous').click();
    await expect(policy.activeReleaseCard).toContainText('previous');
  });
});
