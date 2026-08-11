import { Locator, Page, expect } from '@playwright/test';

import { BasePage } from '../base.page';

const API = '**/api/v1/medical-insurance-ai-agent';
const SKILL_ID = 'settlement_explain_skill';
const FULL_HASH = 'a'.repeat(64);

function workbenchItem(overrides: Record<string, unknown> = {}) {
  return {
    skill_id: SKILL_ID,
    skill_name: '结算解释技能',
    business_action: 'explain',
    business_object: 'settlement',
    semantic_version: '2.0.0',
    artifact_status: 'registered',
    validation_status: 'passed',
    latest_eval_status: 'failed',
    test_release_status: null,
    test_active_version: null,
    governance_status: 'gate_failed',
    attention_reason: 'required_case_failed',
    current_stage: 'diagnose',
    priority: 'blocked',
    latest_eval_run_id: 'run-current',
    candidate_version: '2.0.0',
    baseline_version: '1.0.0',
    regression_count: 1,
    required_failure_count: 1,
    linked_draft_id: null,
    linked_draft_status: null,
    waiting_since: '2026-08-11T06:00:00Z',
    next_action: 'create_fix_draft',
    next_action_reason: '高风险必测案例失败，需要先定位并修改候选制品',
    ...overrides,
  };
}

function workbenchResponse(items = [workbenchItem()]) {
  return {
    summary: {
      total: items.length,
      healthy: 0,
      needs_evaluation: 0,
      pending_approval: 0,
      test_active: 0,
      updated_at: '2026-08-11T06:00:00Z',
    },
    items,
    total: items.length,
    page: 1,
    page_size: 50,
  };
}

function version() {
  return {
    version_id: 'version-current',
    skill_id: SKILL_ID,
    semantic_version: '2.0.0',
    source_commit: 'source-commit-redacted',
    source_path: SKILL_ID,
    artifact_hash: FULL_HASH,
    manifest_snapshot: {},
    dependency_snapshot: {},
    file_count: 1,
    validation_status: 'passed',
    validation_issues: [],
    created_by: 'portal-developer',
    created_at: '2026-08-11T06:00:00Z',
  };
}

function failedRun() {
  return {
    run_id: 'run-current',
    skill_id: SKILL_ID,
    version_id: 'version-current',
    baseline_version_id: 'version-baseline',
    suite_version: 1,
    config_hash: 'b'.repeat(64),
    routing_manifest_hash: 'c'.repeat(64),
    status: 'failed',
    metrics: {
      total: 1,
      passed: 0,
      required_total: 1,
      required_passed: 0,
      top1_accuracy: 0,
      baseline_top1_accuracy: 1,
      regression_count: 1,
      new_false_takeover_count: 1,
      gate_passed: false,
    },
    results: [{
      case_id: 'case-high-risk',
      expected_skill_id: SKILL_ID,
      candidate_skill_id: null,
      baseline_skill_id: SKILL_ID,
      candidate_confidence: 0,
      baseline_confidence: 0.9,
      candidate_passed: false,
      baseline_passed: true,
      required: true,
      diff: 'new_failure',
      candidate_keywords: [],
      baseline_keywords: ['统筹自付'],
    }],
    case_snapshots: [{
      case_id: 'case-high-risk',
      skill_id: SKILL_ID,
      question_template: '脱敏高风险问题',
      expected_skill_id: SKILL_ID,
      expected_intent: null,
      required: true,
      active: true,
      suite_version: 1,
      risk_tags: ['高风险'],
      failure_code: 'HIGH_RISK_BLOCKED',
    }],
    created_by: 'portal-developer',
    created_at: '2026-08-11T06:00:00Z',
    completed_at: '2026-08-11T06:01:00Z',
  };
}

/** Portal Skill 治理工作台 Page Object。 */
export class SkillCatalogPage extends BasePage {
  readonly queue: Locator;
  readonly title: Locator;
  readonly workspace: Locator;
  readonly decision: Locator;
  readonly lifecycle: Locator;
  readonly regressionTable: Locator;
  readonly primaryAction: Locator;
  readonly evidence: Locator;
  readonly evidenceDrawer: Locator;
  readonly evidenceButton: Locator;
  readonly routeDrawer: Locator;
  readonly mobileBack: Locator;

  constructor(page: Page) {
    super(page, (process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:3000').replace(/\/$/, ''));
    this.queue = page.getByRole('navigation', { name: '治理待办' });
    this.title = page.getByRole('heading', { level: 1, name: 'Skill 日常治理' });
    this.workspace = page.getByTestId('skill-governance-workbench');
    this.decision = page.getByRole('region', { name: '治理决策区' });
    this.lifecycle = page.getByRole('list', { name: 'Skill 治理阶段' });
    this.regressionTable = page.getByRole('table', { name: '评测差异案例' });
    this.primaryAction = page.getByTestId('skill-primary-action');
    this.evidence = page.getByRole('complementary', { name: '治理证据' });
    this.evidenceDrawer = page.getByRole('dialog', { name: '治理证据' });
    this.evidenceButton = page.getByRole('button', { name: '查看治理证据' });
    this.routeDrawer = page.getByRole('dialog', { name: '路由调试' });
    this.mobileBack = page.getByRole('button', { name: '返回治理待办' });
  }

  async goto(query = ''): Promise<void> {
    await super.goto(`/skills${query}`);
    await this.title.waitFor({ state: 'visible' });
  }

  async gotoWhileLoading(): Promise<void> {
    await this.page.goto(`${this.baseURL}/skills`, { waitUntil: 'domcontentloaded' });
    await this.title.waitFor({ state: 'visible' });
  }

  async gotoAIAuthoring(): Promise<void> {
    await super.goto('/skills/new');
    await this.page.getByRole('button', { name: 'AI 创建' }).click();
    await this.page.getByRole('heading', { name: 'AI 创建 Skill 草稿' }).waitFor({ state: 'visible' });
  }

  async generateAndAcceptAIDraft(metricName: string, description: string): Promise<void> {
    await this.page.getByPlaceholder('描述你希望 Skill 完成的能力').fill(description);
    await this.page.getByLabel(metricName).check();
    await this.page.getByRole('button', { name: '生成候选' }).click();
    await this.page.getByText('尚未进入运行时').waitFor({ state: 'visible' });
    await this.page.getByRole('button', { name: '接受为草稿' }).click();
    await this.page.getByRole('heading', { name: /编辑草稿/ }).waitFor({ state: 'visible' });
  }

  async optimizeValidateAndEvaluateCandidate(): Promise<void> {
    await this.page.getByLabel('AI 优化要求').fill('简化解释并补充收费员提示');
    await this.page.getByRole('button', { name: '生成优化提案' }).click();
    await this.page.getByRole('region', { name: 'AI 优化差异' }).waitFor({ state: 'visible' });
    await this.page.getByRole('button', { name: '接受优化' }).click();
    await this.page.getByText('优化已接受并保存').waitFor({ state: 'visible' });
    await this.page.getByRole('button', { name: '校验' }).click();
    await this.page.getByRole('button', { name: '运行候选路由评测' }).click();
    await this.page.getByText('路由评测：已完成').waitFor({ state: 'visible' });
    await this.page.getByRole('button', { name: '运行候选行为评测' }).click();
    await this.page.getByText('行为评测：已完成').waitFor({ state: 'visible' });
  }

  catalogItem(skillId: string): Locator {
    return this.page.getByTestId(`skill-catalog-item-${skillId}`);
  }

  queueButtons(): Locator {
    return this.queue.locator('[data-skill-catalog-button]');
  }

  async selectSkill(skillId: string): Promise<void> {
    await this.catalogItem(skillId).click();
    await this.page.getByTestId(`skill-workspace-${skillId}`).waitFor({ state: 'visible' });
  }

  async registerCurrentVersion(skillId: string): Promise<void> {
    await this.selectSkill(skillId);
    if (await this.primaryAction.filter({ hasText: '登记当前版本' }).isVisible()) {
      await this.primaryAction.click();
      const register = this.page.getByTestId('register-skill-version');
      await register.click();
      await register.waitFor({ state: 'hidden' });
    }
  }

  async triggerLiveVersionConflict(skillId: string): Promise<void> {
    await this.selectSkill(skillId);
    await expect(this.primaryAction).toContainText('登记当前版本');
    await this.primaryAction.click();
    await this.page.getByTestId('register-skill-version').click();
  }

  async assertSelectedSkillInURL(skillId: string): Promise<void> {
    await expect(this.page).toHaveURL(new RegExp(`[?&]skill=${skillId}(?:&|$)`));
  }

  async runFixedEvaluation(): Promise<void> {
    const run = this.primaryAction.filter({ hasText: '运行候选评测' });
    if (await run.isVisible()) {
      await run.click();
      await this.primaryAction.filter({ hasText: '创建发布候选' }).waitFor({ state: 'visible' });
    }
    await this.page.getByRole('button', { name: '全部', exact: true }).click();
    await this.regressionTable.waitFor({ state: 'visible' });
    await expect(this.page.getByText('候选通过率')).toBeVisible();
  }

  async approveAndActivateTestRelease(): Promise<void> {
    const create = this.primaryAction.filter({ hasText: '创建发布候选' });
    if (await create.isVisible()) {
      await create.click();
      await this.primaryAction.filter({ hasText: '申请复审' }).waitFor({ state: 'visible' });
    }
    const request = this.primaryAction.filter({ hasText: '申请复审' });
    if (await request.isVisible()) {
      await request.click();
      await this.primaryAction.filter({ hasText: '进入人工复审' }).waitFor({ state: 'visible' });
    }
    const review = this.primaryAction.filter({ hasText: '进入人工复审' });
    if (await review.isVisible()) {
      await review.click();
      await this.page.getByRole('region', { name: '当前 Skill 人工复审' }).waitFor({ state: 'visible' });
      await this.page.getByRole('button', { name: '人工审批通过' }).click();
      const activate = this.page.getByRole('button', { name: '激活 Test Shadow' });
      await activate.waitFor({ state: 'visible' });
      await activate.click();
      await this.page.getByText('Test Shadow 已激活').waitFor({ state: 'visible' });
      await this.goto(`?skill=${SKILL_ID}`);
      return;
    }
    const activate = this.primaryAction.filter({ hasText: '激活 Test Shadow' });
    if (await activate.isVisible()) await activate.click();
    await this.page.getByText('Test Active').first().waitFor({ state: 'visible' });
  }

  async openEvidenceDrawer(): Promise<void> {
    await this.evidenceButton.click();
    await this.evidenceDrawer.waitFor({ state: 'visible' });
  }

  async showAllRegressionCases(): Promise<void> {
    await this.decision.getByRole('button', { name: '全部', exact: true }).click();
  }

  async returnToQueue(): Promise<void> {
    await this.mobileBack.click();
    await this.queue.waitFor({ state: 'visible' });
  }

  async assertNoPageOverflow(): Promise<void> {
    expect(await this.page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  }

  async capture(name: string): Promise<void> {
    await this.page.screenshot({ path: `test-results/${name}.png`, fullPage: true });
  }

  text(value: string): Locator {
    return this.page.getByText(value, { exact: false });
  }

  button(name: string): Locator {
    return this.page.getByRole('button', { name });
  }

  alertWithText(value: string): Locator {
    return this.page.getByRole('alert').filter({ hasText: value });
  }

  async assertTitleDoesNotBreakPerCharacter(): Promise<void> {
    const box = await this.title.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.width).toBeGreaterThan(120);
    expect(box!.height).toBeLessThan(60);
  }

  async assertSinglePageH1(): Promise<void> {
    await expect(this.page.getByRole('heading', { level: 1 })).toHaveCount(1);
  }

  async assertMobileDetailUsesViewport(viewportWidth: number): Promise<void> {
    const main = await this.page.getByRole('main').boundingBox();
    const detail = await this.decision.boundingBox();
    expect(main).not.toBeNull();
    expect(detail).not.toBeNull();
    expect(main!.x).toBeLessThanOrEqual(1);
    expect(main!.width).toBeGreaterThanOrEqual(viewportWidth - 1);
    expect(detail!.width).toBeGreaterThanOrEqual(viewportWidth * 0.78);
  }

  async assertNoSensitiveOrFullHash(): Promise<void> {
    const body = await this.page.locator('body').innerText();
    expect(body).not.toContain(this.fullHash());
    expect(body).not.toMatch(/\b[a-f0-9]{32,64}\b/i);
    expect(body).not.toContain('张三');
    expect(body).not.toContain('110101199001011234');
  }

  async assertQueueKeyboardSemantics(): Promise<void> {
    await this.primaryAction.focus();
    await expect(this.primaryAction).toBeFocused();
    await this.evidenceButton.focus();
    await expect(this.evidenceButton).toBeFocused();

    const items = this.queueButtons();
    const first = items.first();
    const second = items.nth(1);
    await first.focus();
    await this.page.keyboard.press('ArrowDown');
    await expect(second).toBeFocused();
    await expect(first).toHaveAttribute('aria-current', 'true');
    await expect(second).not.toHaveAttribute('aria-current', 'true');
    await this.page.keyboard.press('ArrowUp');
    await expect(first).toBeFocused();
    await expect(first).toHaveAttribute('aria-current', 'true');
    await expect(second).not.toHaveAttribute('aria-current', 'true');
    await this.page.keyboard.press('ArrowDown');
    await this.page.keyboard.press('Enter');
    await expect(second).toHaveAttribute('aria-current', 'true');
  }

  async assertMobileReturnRestoresFocus(skillId: string): Promise<void> {
    await this.returnToQueue();
    await expect(this.catalogItem(skillId)).toBeFocused();
  }

  async setCssZoom(value: string): Promise<void> {
    await this.page.evaluate((zoom) => { document.documentElement.style.zoom = zoom; }, value);
  }

  async mockWorkbench(items: Array<Record<string, unknown>>): Promise<void> {
    await this.page.route(`${API}/infra-skills/workbench*`, (route) => route.fulfill({ json: workbenchResponse(items) }));
  }

  async mockGovernanceLoop(): Promise<void> {
    let state: 'changed' | 'registered' | 'evaluated' | 'candidate' | 'pending' | 'approved' | 'active' = 'changed';
    let creatorAuthorization = '';
    const currentVersion = version();
    const passedRun = {
      ...failedRun(),
      status: 'passed',
      baseline_version_id: null,
      metrics: {
        ...failedRun().metrics,
        passed: 1,
        required_passed: 1,
        top1_accuracy: 1,
        regression_count: 0,
        new_false_takeover_count: 0,
        gate_passed: true,
      },
      results: [{ ...failedRun().results[0], candidate_skill_id: SKILL_ID, candidate_confidence: 0.9, candidate_passed: true, diff: 'unchanged_pass' }],
      case_snapshots: [],
    };
    const currentRelease = () => ({
      release_id: 'release-current',
      skill_id: SKILL_ID,
      version_id: currentVersion.version_id,
      environment: 'test',
      status: state === 'candidate' ? 'candidate' : state === 'pending' ? 'approval_pending' : state === 'approved' ? 'approved' : 'active',
      baseline_release_id: null,
      eval_run_id: passedRun.run_id,
      artifact_hash: currentVersion.artifact_hash,
      config_hash: passedRun.config_hash,
      rollout_percent: state === 'active' ? 100 : 0,
      runtime_mode: 'shadow',
      revision: state === 'candidate' ? 1 : state === 'pending' ? 2 : state === 'approved' ? 3 : 4,
      created_by: 'portal-developer',
      created_at: '2026-08-11T06:00:00Z',
      activated_at: state === 'active' ? '2026-08-11T06:30:00Z' : null,
      retired_at: null,
      approval: state === 'approved' || state === 'active' ? {
        approved_by: 'portal-information-admin',
        approver_role: 'information_department',
        approved_at: '2026-08-11T06:20:00Z',
      } : null,
    });
    const item = () => {
      const facts = {
        changed: ['changed', 'modify', 'register_version'],
        registered: ['needs_evaluation', 'evaluate', 'run_evaluation'],
        evaluated: ['needs_evaluation', 'review', 'create_candidate'],
        candidate: ['pending_approval', 'review', 'request_approval'],
        pending: ['pending_approval', 'review', 'review_approval'],
        approved: ['pending_approval', 'release', 'activate_test_shadow'],
        active: ['healthy', 'healthy', 'view_evidence'],
      }[state];
      return workbenchItem({
        artifact_status: state === 'changed' ? 'changed' : 'registered',
        governance_status: facts[0],
        current_stage: facts[1],
        next_action: facts[2],
        next_action_reason: state === 'active' ? 'Test Shadow 已激活' : '按当前冻结事实推进',
        latest_eval_status: state === 'changed' || state === 'registered' ? null : 'passed',
        latest_eval_run_id: state === 'changed' || state === 'registered' ? null : passedRun.run_id,
        candidate_version: state === 'changed' ? null : currentVersion.semantic_version,
        test_release_status: state === 'active' ? 'active' : state === 'candidate' ? 'candidate' : state === 'pending' ? 'approval_pending' : state === 'approved' ? 'approved' : null,
        test_active_version: state === 'active' ? currentVersion.semantic_version : null,
        priority: state === 'active' ? 'normal' : 'high',
      });
    };

    await this.page.route(`${API}/infra-skills/workbench*`, (route) => route.fulfill({ json: workbenchResponse([item()]) }));
    await this.page.route(`${API}/infra-skills/${SKILL_ID}`, (route) => route.fulfill({ json: {
      skill_id: SKILL_ID, skill_name: '结算解释技能', business_action: 'explain', business_object: 'settlement',
      semantic_version: '2.0.0', include_keywords: [], excluded_intents: [], required_mcp: [], optional_mcp: [],
      needed_objects: [], locked_versions: {}, file_count: 1,
    } }));
    await this.page.route(`${API}/infra-skills/${SKILL_ID}/versions`, (route) => route.fulfill({
      json: state === 'changed' ? [] : [currentVersion],
    }));
    await this.page.route(`${API}/infra-skills/${SKILL_ID}/versions/sync`, (route) => {
      state = 'registered';
      return route.fulfill({ status: 201, json: currentVersion });
    });
    await this.page.route(`${API}/infra-skills/${SKILL_ID}/eval-runs`, (route) => {
      if (route.request().method() === 'POST') {
        state = 'evaluated';
        return route.fulfill({ status: 202, json: passedRun });
      }
      return route.fulfill({ json: { items: state === 'changed' || state === 'registered' ? [] : [passedRun], total: state === 'changed' || state === 'registered' ? 0 : 1 } });
    });
    await this.page.route(`${API}/infra-skills/${SKILL_ID}/releases**`, (route) => {
      const url = route.request().url();
      const method = route.request().method();
      if (method === 'GET') return route.fulfill({ json: { items: ['candidate', 'pending', 'approved', 'active'].includes(state) ? [currentRelease()] : [], total: ['candidate', 'pending', 'approved', 'active'].includes(state) ? 1 : 0 } });
      if (url.endsWith('/request-approval')) state = 'pending';
      else if (url.endsWith('/approve')) {
        const reviewerAuthorization = route.request().headers().authorization ?? '';
        if (!reviewerAuthorization || reviewerAuthorization === creatorAuthorization) {
          return route.fulfill({ status: 403, json: { detail: { error_code: 'SELF_APPROVAL_FORBIDDEN', message: '候选发布创建人不能审批自己的发布', audit_event: {} } } });
        }
        state = 'approved';
      } else if (url.endsWith('/activate')) state = 'active';
      else {
        creatorAuthorization = route.request().headers().authorization ?? '';
        state = 'candidate';
      }
      return route.fulfill({ status: 201, json: currentRelease() });
    });
  }

  async mockFailedEvaluation(overrides: Record<string, unknown> = {}): Promise<void> {
    const item = workbenchItem(overrides);
    await this.mockWorkbench([item]);
    await this.page.route(`${API}/infra-skills/${SKILL_ID}`, (route) => route.fulfill({ json: {
      skill_id: SKILL_ID,
      skill_name: '结算解释技能',
      business_action: 'explain',
      business_object: 'settlement',
      semantic_version: '2.0.0',
      include_keywords: [],
      excluded_intents: [],
      required_mcp: [],
      optional_mcp: [],
      needed_objects: [],
      locked_versions: {},
      file_count: 1,
    } }));
    await this.page.route(`${API}/infra-skills/${SKILL_ID}/versions`, (route) => route.fulfill({ json: [version()] }));
    await this.page.route(`${API}/infra-skills/${SKILL_ID}/eval-runs`, (route) => route.fulfill({ json: { items: [failedRun()], total: 1 } }));
    await this.page.route(`${API}/infra-skills/${SKILL_ID}/releases*`, (route) => route.fulfill({ json: { items: [], total: 0 } }));
  }

  async mockEmpty(): Promise<void> {
    await this.mockWorkbench([]);
  }

  async mockLoading(delayMs = 1500): Promise<void> {
    await this.page.route(`${API}/infra-skills/workbench*`, async (route) => {
      await new Promise((resolve) => setTimeout(resolve, delayMs));
      await route.fulfill({ json: workbenchResponse([workbenchItem()]) });
    });
  }

  async mockPartialReleaseError(): Promise<void> {
    await this.mockFailedEvaluation();
    await this.page.route(`${API}/infra-skills/${SKILL_ID}/releases*`, (route) => route.fulfill({
      status: 503,
      json: { detail: { error_code: 'RELEASE_UNAVAILABLE', message: '发布记录暂不可用', audit_event: {} } },
    }));
  }

  async mockMutationError(status: 403 | 409, message: string): Promise<void> {
    await this.mockFailedEvaluation({
      latest_eval_status: 'passed',
      current_stage: 'release',
      governance_status: 'pending_approval',
      next_action: 'activate_test_shadow',
      next_action_reason: '人工复审已通过，等待激活',
    });
    const run = { ...failedRun(), status: 'passed', metrics: { ...failedRun().metrics, passed: 1, required_passed: 1, gate_passed: true } };
    const release = {
      release_id: 'release-current', skill_id: SKILL_ID, version_id: 'version-current', environment: 'test',
      status: 'approved', baseline_release_id: null, eval_run_id: 'run-current', artifact_hash: FULL_HASH,
      config_hash: 'b'.repeat(64), rollout_percent: 0, runtime_mode: 'shadow', revision: 3,
      created_by: 'portal-developer', created_at: '2026-08-11T06:00:00Z', activated_at: null, retired_at: null,
      approval: { approved_by: 'information-admin', approver_role: 'information_department', approved_at: '2026-08-11T06:30:00Z' },
    };
    await this.page.route(`${API}/infra-skills/${SKILL_ID}/eval-runs`, (route) => route.fulfill({ json: { items: [run], total: 1 } }));
    await this.page.route(`${API}/infra-skills/${SKILL_ID}/releases*`, (route) => route.fulfill({ json: { items: [release], total: 1 } }));
    await this.page.route(`${API}/infra-skills/${SKILL_ID}/releases/release-current/activate`, (route) => route.fulfill({
      status,
      json: { detail: { error_code: status === 403 ? 'SKILL_CONTROL_FORBIDDEN' : 'SKILL_EVIDENCE_CHANGED', message, audit_event: {} } },
    }));
  }

  async mockTwoItemQueue(): Promise<void> {
    await this.mockWorkbench([
      workbenchItem(),
      workbenchItem({ skill_id: 'e2e_second_skill', skill_name: 'E2E 第二待办' }),
    ]);
    await this.page.route(`${API}/infra-skills/e2e_second_skill`, (route) => route.fulfill({ status: 404, json: { detail: 'not found' } }));
    await this.page.route(`${API}/infra-skills/e2e_second_skill/**`, (route) => route.fulfill({ status: 404, json: { detail: 'not found' } }));
  }

  fullHash(): string {
    return FULL_HASH;
  }
}
