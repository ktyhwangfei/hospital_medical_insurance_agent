import { expect, test } from '@playwright/test';
import { PolicyKnowledgePage } from '../../pages/portal/policy-knowledge.page';

const prefix = '**/api/v1/medical-insurance-ai-agent';
const qualityConfigHash = '197ceb8357b8a65b5db3db7044838ff7fd7010ab36caf2b11270e4ab61607e22';
const activeCase = { case_id: 'case_1', name: '住院支付比例', query: '职工住院支付比例', mode: 'semantic', expected_knowledge_ids: ['kn_1'], filters: {}, required: true, active: true, case_set_version: 1 };

test.describe('政策知识工作台与整批发布门禁', () => {
  test('知识页进入构建主页并仅展示新的三级工作区', async ({ page }) => {
    await page.route(`${prefix}/policy-workbench/knowledge-build/eligible-units`, (route) => route.fulfill({ json: [] }));
    await page.route(`${prefix}/policy-workbench/knowledge-build/tasks`, (route) => route.fulfill({ json: [] }));
    const policy = new PolicyKnowledgePage(page);
    await policy.gotoKnowledge();

    await expect(page).toHaveURL(/\/policy-knowledge\/knowledge\/build$/);
    expect((await policy.navLabels()).map((item) => item.trim())).toEqual(['概览', '文档', '单元', '知识', '测试']);
    expect((await policy.workspaceLabels()).map((item) => item.trim())).toEqual(['知识构建', '知识审核', '发布管理', '语义发现']);
    await expect(policy.buildTitle).toBeVisible();
    await expect(policy.newBuildTaskButton).toHaveCount(1);
    for (const legacyWorkspace of ['驾驶舱', '工作台', '变更集', '待决策', '已发布']) {
      await expect(policy.knowledgeWorkspaceNavigation.getByRole('link', {
        name: legacyWorkspace,
        exact: true,
      })).toHaveCount(0);
    }
  });

  test('候选版只能整批测试并在人工发布后切换活动版本', async ({ page }) => {
    let candidateStatus = 'ready';
    let activeId = 'baseline';
    const passedRun = { run_id: 'run_1', release_id: 'candidate', baseline_release_id: 'baseline', case_set_version: 1, config_hash: qualityConfigHash, repeat_count: 3, status: 'passed', candidate_score: 0.95, baseline_score: 0.8, consistency_score: 1, blocked_reasons: [] };
    const release = (release_id: string, status: string) => ({ release_id, status, facts_collection: `facts_${release_id}`, rules_collection: `rules_${release_id}`, contract_version: '2', case_set_version: 1, config_hash: qualityConfigHash, quality_score: status === 'passed' ? 0.95 : null, consistency_score: status === 'passed' ? 1 : null });
    await page.route(`${prefix}/policy-workbench/**`, async (route) => {
      const url = route.request().url();
      const method = route.request().method();
      if (url.endsWith('/test-cases')) return route.fulfill({ json: [activeCase] });
      if (url.endsWith('/releases/candidate/quality/latest')) return candidateStatus === 'passed'
        ? route.fulfill({ json: { run: passedRun, case_results: [] } })
        : route.fulfill({ status: 404, json: { detail: '尚无运行' } });
      if (url.endsWith('/releases/candidate/test') && method === 'POST') {
        candidateStatus = 'passed';
        return route.fulfill({ json: passedRun });
      }
      if (url.endsWith('/quality-runs/run_1/case-results')) return route.fulfill({ json: [{ run_id: 'run_1', target: 'candidate', case_id: 'case_1', repeat_index: 0, result_knowledge_ids: ['kn_1'], score: 1, passed: true, diagnostics: { rank_score: 1 } }, { run_id: 'run_1', target: 'baseline', case_id: 'case_1', repeat_index: 0, result_knowledge_ids: [], score: 0, passed: false, diagnostics: { rank_score: 0 } }] });
      if (url.endsWith('/releases/candidate/promote-legacy') && method === 'POST') { activeId = 'candidate'; candidateStatus = 'active'; return route.fulfill({ json: release('candidate', 'active') }); }
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
    const release = (release_id: string, status: string) => ({ release_id, status, facts_collection: `facts_${release_id}`, rules_collection: `rules_${release_id}`, contract_version: '2', case_set_version: 1, config_hash: qualityConfigHash, quality_score: null, consistency_score: null });
    await page.route(`${prefix}/policy-workbench/**`, async (route) => {
      const url = route.request().url();
      const method = route.request().method();
      if (url.endsWith('/test-cases')) return route.fulfill({ json: [activeCase] });
      if (url.endsWith('/releases/candidate/quality/latest')) return route.fulfill({ json: { run: { run_id: 'run_failed', release_id: 'candidate', baseline_release_id: 'baseline', case_set_version: 1, config_hash: qualityConfigHash, repeat_count: 3, status: 'failed', candidate_score: 0.5, baseline_score: 0.8, consistency_score: 0.5, blocked_reasons: ['重复运行一致性低于门槛'] }, case_results: [] } });
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

  test('候选规则可逐行查看完整编译与发布溯源', async ({ page }) => {
    const candidate = {
      knowledge_id: 'KN_TRACE', unit_id: 'UNIT_TRACE', extraction_id: 'EXT_TRACE', relationship_source: 'persisted',
      business_sentence: '待遇规则候选结论', source_text: '政策原文快照',
      fields: [{ field_code: 'rule_type', field_name: '规则类型', raw_value: '待遇规则' }], standardized_fields: [],
      confidence: { completeness: 1, accuracy: 1, source_fidelity: 1, model_confidence: 1, value_domain_compliance: 1, overall: 1, uncertainties: [] },
      citations: [{ evidence: '原文证据', title: '测试政策' }],
    };
    const changeSet = {
      change_set_id: 'CS_TRACE', source_document_version_id: 'DOC_TRACE_V1', doc_id: 'DOC_TRACE', doc_title: '测试政策', build_task_id: 'KB_TRACE',
      source_units: [{ doc_id: 'DOC_TRACE', doc_title: '测试政策', unit_id: 'UNIT_TRACE', unit_revision_id: 'UNIT_TRACE_V1', path: ['测试条款'] }],
      semantic_contract_version: '2', supersedes_candidate_id: null, status: 'PENDING_REVIEW',
      summary: { additions: 1, modifications: 0, replacements: 0, expirations: 0, unchanged: 0 },
      items: [{ item_id: 'ITEM_TRACE', change_type: 'ADD', rule_id: 'RULE_TRACE', compile_run_id: 'RUN_TRACE', unit_id: 'UNIT_TRACE', doc_id: 'DOC_TRACE', before: null, after: candidate, ai_recommendation: '核验后通过', reason: '编译完成', evidence_ids: ['EVID_TRACE'], quality_checks: [], risk_level: 'LOW', impact_scope: {}, needs_human: false }],
      quality_report: { source_fidelity: 1, structural_completeness: 1, semantic_consistency: 1, rule_consistency: 1 },
      risk_summary: { LOW: 1 }, blockers: [], review_decision: null,
      created_at: '2026-08-11T00:00:00Z', updated_at: '2026-08-11T00:00:01Z',
    };
    const step = (sequence_no: number, stage: string) => ({ step_id: `STEP_${sequence_no}`, run_id: 'RUN_TRACE', sequence_no, stage, status: 'PASS', input_payload: {}, output_payload: {}, issues: [], error: null, duration_ms: 1, started_at: '2026-08-11T00:00:00Z', finished_at: '2026-08-11T00:00:01Z' });
    const trace = {
      rule: { rule_id: 'RULE_TRACE', subject: '待遇规则', population: null, conditions: {}, result: { value: '候选结论' }, source_type: 'DIRECT', evidence: ['EVID_TRACE'], dependencies: [], formula: null, compiler_version: '1.0', rule_version: 1, status: 'PASS' },
      run: { run_id: 'RUN_TRACE', document_id: 'DOC_TRACE', unit_id: 'UNIT_TRACE', extraction_id: 'EXT_TRACE', raw_input: {}, llm_output: {}, model_name: null, prompt_version: null, schema_version: null, compiler_version: '1.0', status: 'PASS', metrics: {}, error: null, started_at: '2026-08-11T00:00:00Z', finished_at: '2026-08-11T00:00:01Z' },
      raw_input: { source_text: '政策原文快照' }, llm_output: { facts: [{ fact_id: 'FACT_TRACE' }] },
      steps: [step(3, 'CANONICALIZE'), step(7, 'VALIDATE'), step(8, 'PUBLISH')], issues: [],
      publication: { release_id: 'RELEASE_TRACE', status: 'published', published_at: '2026-08-11T00:00:02Z' }, history: [],
    };

    await page.route(`${prefix}/semantic/metrics?*`, (route) => route.fulfill({ json: [] }));
    await page.route(`${prefix}/policy-workbench/**`, (route) => {
      const url = route.request().url();
      if (url.includes('/decision-tasks')) return route.fulfill({ json: [] });
      if (url.endsWith('/change-sets/CS_TRACE')) return route.fulfill({ json: changeSet });
      if (url.endsWith('/rules/RULE_TRACE/trace?run_id=RUN_TRACE')) return route.fulfill({ json: trace });
      return route.fulfill({ status: 404, json: { detail: 'not mocked' } });
    });

    await page.goto(`http://127.0.0.1:${process.env.E2E_FRONTEND_PORT ?? 3000}/policy-knowledge/knowledge/review/CS_TRACE`);
    await page.getByRole('button', { name: '查看溯源' }).click();

    const drawer = page.getByRole('dialog').filter({ has: page.getByRole('heading', { name: '规则编译溯源' }) });
    await expect(drawer.getByText('原始输入', { exact: true })).toBeVisible();
    await expect(drawer.getByText('LLM 提取')).toBeVisible();
    await expect(drawer.getByText(/CANONICALIZE/)).toBeVisible();
    await expect(drawer.getByText(/VALIDATE/)).toBeVisible();
    await expect(drawer.getByText(/PUBLISH/)).toBeVisible();
    await drawer.getByRole('button', { name: '关闭溯源' }).click();
    await expect(drawer).toBeHidden();
  });
});
