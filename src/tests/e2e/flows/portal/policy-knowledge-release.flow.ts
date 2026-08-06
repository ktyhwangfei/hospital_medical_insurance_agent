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
    expect((await policy.workspaceLabels()).map((item) => item.trim())).toEqual(['知识构建', '知识审核', '发布管理']);
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
});
