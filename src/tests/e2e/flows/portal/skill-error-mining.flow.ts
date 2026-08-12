import { expect, test, type Page } from '@playwright/test';

import { EvalMiningPage } from '../../pages/portal/eval-mining.page';
import { PolicyQAPage } from '../../pages/portal/policy-qa.page';

const PREFIX = '/api/v1/medical-insurance-ai-agent';
const STREAM_URL = `**${PREFIX}/policy-qa/stream`;
const FEEDBACK_URL = `**${PREFIX}/policy-qa/feedback`;
const POOL_URL = `**${PREFIX}/infra-skills/eval-case-pool`;
const TRANSFORM_URL = `**${PREFIX}/infra-skills/eval-case-pool/pool-1/transform`;
const CONFIRM_URL = `**${PREFIX}/infra-skills/eval-case-pool/pool-1/confirm`;

function sseWithQaTurnId(qaTurnId: string): string {
  const result = {
    answer: '起付线按年度累计计算。',
    answer_status: 'complete',
    case_context: null,
    calculation_steps: [],
    definition: null,
    warnings: [],
    citations: [],
    uncertainties: [],
    verification_summary: { settlement_checked: false, calculation_checked: true, policy_count: 0, message: '已核对。' },
  };
  return [
    'event: result',
    `data: ${JSON.stringify({ result, qa_turn_id: qaTurnId })}`,
    '',
    'event: done',
    `data: ${JSON.stringify({ answer_status: 'complete', success: true, qa_turn_id: qaTurnId })}`,
    '',
    '',
  ].join('\n');
}

async function mockPolicyQAStream(page: Page, qaTurnId: string): Promise<void> {
  await page.route(STREAM_URL, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream; charset=utf-8',
      headers: { 'Cache-Control': 'no-cache' },
      body: sseWithQaTurnId(qaTurnId),
    });
  });
}

async function mockFeedback(page: Page): Promise<void> {
  await page.route(FEEDBACK_URL, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        pool_id: 'pool-1',
        status: 'pending_triage',
        error_dimension: 'calculation',
        source_selected_skill_id: 'deductible',
      }),
    });
  });
}

async function mockPoolList(page: Page, status = 'pending_triage'): Promise<void> {
  await page.route(POOL_URL, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: [
          {
            pool_id: 'pool-1',
            tenant_id: 'default',
            source_qa_turn_id: 'qat_e2e',
            source_user_id: 'demo',
            reason_code: 'wrong_calculation',
            error_dimension: 'calculation',
            initial_dimension: 'calculation',
            transformed_dimension: status === 'transformed' ? 'calculation' : null,
            target_skill_id: 'deductible',
            status,
            revision: 1,
            eval_case_ref: null,
            created_at: '2026-08-10T00:00:00Z',
            updated_at: '2026-08-10T00:00:00Z',
          },
        ],
        total: 1,
        limit: 100,
        offset: 0,
      }),
    });
  });
}

async function mockTransform(page: Page): Promise<void> {
  await page.route(TRANSFORM_URL, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        pool_id: 'pool-1',
        transformed_dimension: 'calculation',
        case_proposal: {
          case_type: 'calculation',
          target_skill_id: 'deductible',
          input_template: {},
          assertions: { case_type: 'calculation', expected_value: 100, tolerance: 0.01 },
        },
        root_cause: '计算口径错误',
        citations: [],
        uncertainties: [],
        revision: 2,
      }),
    });
  });
}

async function mockConfirm(page: Page): Promise<void> {
  await page.route(CONFIRM_URL, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        pool_id: 'pool-1',
        case_type: 'calculation',
        case_id: 'regcase_e2e',
        revision: 3,
      }),
    });
  });
}

test.describe('Skill 错误挖掘主链路（mock API）', () => {
  test('用户反馈 → 入池 → 案例分型编辑 → 确认投影', async ({ page }) => {
    await mockPolicyQAStream(page, 'qat_e2e');
    await mockFeedback(page);

    const policyQA = new PolicyQAPage(page);
    await policyQA.goto();
    await policyQA.ask('起付线怎么算');
    await policyQA.answer.first().waitFor({ state: 'visible' });

    // 1) 用户提交「回答有误」反馈
    await policyQA.submitFeedback('wrong_calculation');
    await expect(page.getByTestId('policy-qa-feedback-submitted')).toBeVisible();

    // 2) 案例挖掘：转换 → 编辑确认
    await mockPoolList(page, 'pending_triage');
    await mockTransform(page);
    await mockConfirm(page);

    const mining = new EvalMiningPage(page);
    await mining.goto();
    await mining.row('pool-1').waitFor({ state: 'visible' });

    await mining.transform('pool-1');
    // 转换后状态变为 transformed，出现「编辑确认」
    await mining.openEditor('pool-1');

    // 3) 分型编辑器只展示计算维度字段
    await expect(
      page.getByTestId('proposal-field-expected_value'),
    ).toBeVisible();
    await expect(
      page.getByTestId('proposal-field-applicability'),
    ).toHaveCount(0);

    // 4) 确认投影成功
    await mining.confirm('pool-1');
    // 列表刷新后该条状态为 confirmed（重新 mock 列表）
    await mockPoolList(page, 'confirmed');
    await page.reload();
    await mining.row('pool-1').waitFor({ state: 'visible' });
    await expect(mining.row('pool-1').getByText(/已确认/)).toBeVisible();
  });

  test('390px 视口无横向溢出', async ({ page }) => {
    await mockPoolList(page, 'transformed');
    await page.setViewportSize({ width: 390, height: 844 });

    const mining = new EvalMiningPage(page);
    await mining.goto();
    await mining.row('pool-1').waitFor({ state: 'visible' });

    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
    expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
  });
});
