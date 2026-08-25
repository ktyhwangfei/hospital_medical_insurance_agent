import { expect, test, type Page } from '@playwright/test';

import { PolicyQAPage } from '../../pages/portal/policy-qa.page';
import { E2E_BACKEND_URL } from '../../utils/workspace-ports';
import { waitForAPIReady } from '../../utils/wait-strategies';

const STREAM_URL = '**/api/v1/medical-insurance-ai-agent/policy-qa/stream';

interface PublicResultOptions {
  answer: string;
  answerStatus: 'complete' | 'partial' | 'unavailable';
  withDetails?: boolean;
}

function publicResult({ answer, answerStatus, withDetails = false }: PublicResultOptions) {
  const complete = answerStatus === 'complete';
  return {
    answer,
    answer_status: answerStatus,
    case_context: withDetails
      ? {
          basic_pooling_self_pay: 4962.67,
          personal_total_pay: 8231.44,
        }
      : null,
    calculation_steps: withDetails
      ? [{ step_name: '分段计算', description: '按起付线与政策比例核对。' }]
      : [],
    definition: null,
    warnings: [],
    citations: withDetails
      ? [{ title: '基本医疗保险住院待遇政策', excerpt: '按规定核对住院费用待遇。' }]
      : [],
    uncertainties: complete ? [] : ['部分核验信息暂不可用，请以医保经办结果为准。'],
    verification_summary: {
      settlement_checked: complete || answerStatus === 'partial',
      calculation_checked: complete,
      policy_count: withDetails ? 1 : 0,
      message:
        answerStatus === 'complete'
          ? '已核对当前结算单与 1 条政策依据。'
          : answerStatus === 'partial'
            ? '已核对结算单，部分政策依据仍待确认。'
            : '现有信息不足，未形成可靠核对结论。',
    },
  };
}

function sseBody(result: ReturnType<typeof publicResult>): string {
  return [
    'event: context_need',
    'data: {"settlement_id":"1671213"}',
    '',
    'event: step',
    'data: {"public_message":"正在核对政策依据","status":"running"}',
    '',
    'event: result',
    `data: ${JSON.stringify({ result })}`,
    '',
    'event: done',
    `data: ${JSON.stringify({ answer_status: result.answer_status, success: true, attempt_count: 1, halt_reason: 'verified' })}`,
    '',
    '',
  ].join('\n');
}

async function mockPolicyQAStream(
  page: Page,
  results: Array<ReturnType<typeof publicResult>>,
): Promise<void> {
  let requestIndex = 0;
  await page.route(STREAM_URL, async (route) => {
    const result = results[Math.min(requestIndex, results.length - 1)];
    requestIndex += 1;
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream; charset=utf-8',
      headers: { 'Cache-Control': 'no-cache' },
      body: sseBody(result),
    });
  });
}

test.describe('Policy QA chat-first 全链路', () => {
  test.beforeAll(async () => {
    await waitForAPIReady(E2E_BACKEND_URL);
  });

  test('空态展示示例问题并可填入 Composer', async ({ page }) => {
    const policyQA = new PolicyQAPage(page);
    await policyQA.goto();

    await expect(page.getByText('先问一个与当前结算相关的问题')).toBeVisible();
    await page.getByRole('button', { name: '查询住院费用，结算单 1671213' }).click();
    await expect(policyQA.composer).toHaveValue('查询住院费用，结算单 1671213');
  });

  test('真实 SSE 只形成一个安全公开答案', async ({ page }) => {
    const policyQA = new PolicyQAPage(page);
    await policyQA.goto();
    await policyQA.ask('查询住院费用，结算单 1671213');

    await expect(policyQA.answer).toHaveCount(1);
    await expect(policyQA.settlementChip).toContainText('1671213');
    await expect(policyQA.verification).toBeVisible();
    expect((await policyQA.readAnswer()).trim()).not.toBe('');
    await expect(page.getByText('本轮执行链路')).toHaveCount(0);
    await expect(page.getByText('结算数据来源')).toHaveCount(0);
  });

  test('支持连续追问、计算折叠区与政策来源 Dialog', async ({ page }) => {
    await mockPolicyQAStream(page, [
      publicResult({
        answer: '本次统筹自付为 4,962.67 元。',
        answerStatus: 'complete',
        withDetails: true,
      }),
      publicResult({
        answer: '统筹自付由起付线及政策比例共同计算。',
        answerStatus: 'complete',
        withDetails: true,
      }),
    ]);
    const policyQA = new PolicyQAPage(page);
    await policyQA.goto();

    await policyQA.ask('查询住院费用，结算单 1671213');
    await expect(policyQA.settlementChip).toContainText('1671213');
    await page.getByText('计算依据').last().click();
    await expect(page.getByText('分段计算').last()).toBeVisible();

    await policyQA.ask('统筹自付为什么这么多？');
    await expect(policyQA.answer).toHaveCount(2);
    await expect(policyQA.answer.last()).toContainText('统筹自付');
    await policyQA.openSources();
    await expect(policyQA.sourcesDialog).toContainText('基本医疗保险住院待遇政策');
    await expect(page.getByText('本轮执行链路')).toHaveCount(0);
    await expect(page.getByText('结算数据来源')).toHaveCount(0);
  });

  test('明确展示 partial 与 unavailable 核验状态', async ({ page }) => {
    await mockPolicyQAStream(page, [
      publicResult({ answer: '当前只能给出部分费用解释。', answerStatus: 'partial' }),
      publicResult({ answer: '现有信息不足，暂无法可靠解释。', answerStatus: 'unavailable' }),
    ]);
    const policyQA = new PolicyQAPage(page);
    await policyQA.goto();

    await policyQA.ask('查询住院费用，结算单 1671213');
    await expect(policyQA.verification.last()).toHaveAttribute('data-status', 'partial');
    await expect(page.getByText('部分核验信息暂不可用，请以医保经办结果为准。')).toBeVisible();

    await policyQA.ask('还能确认哪些信息？');
    await expect(policyQA.verification.last()).toHaveAttribute('data-status', 'unavailable');
    await expect(policyQA.answer.last()).toContainText('暂无法可靠解释');
  });
});
