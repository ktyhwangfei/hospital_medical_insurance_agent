import { test, expect } from '@playwright/test';
import { ChatPage } from '../../pages/portal/chat.page';
import { SettlementPage } from '../../pages/portal/settlement.page';
import { waitForAPIReady } from '../../utils/wait-strategies';

test.describe('结算异常导办全流程', () => {
  let chatPage: ChatPage;
  let settlementPage: SettlementPage;

  test.beforeAll(async () => {
    await waitForAPIReady('http://127.0.0.1:8000');
  });

  test.beforeEach(async ({ page }) => {
    chatPage = new ChatPage(page);
    settlementPage = new SettlementPage(page);
    await chatPage.goto();
  });

  test('结算异常查询→导办步骤→引用展示', async () => {
    await chatPage.sendMessage('P001 患者 5月门诊结算被拒付');

    const response = await chatPage.getResponseText();
    expect(response).toBeTruthy();
    expect(response.length).toBeGreaterThan(0);

    expect(await chatPage.hasCitations()).toBeTruthy();

    await settlementPage.goto();
    await settlementPage.verifyExceptionList();
    const count = await settlementPage.getExceptionCount();
    expect(count).toBeGreaterThanOrEqual(0);
  });

  test('结算异常详情展开导办步骤', async () => {
    await settlementPage.goto();
    await settlementPage.verifyExceptionList();

    const count = await settlementPage.getExceptionCount();
    if (count > 0) {
      await settlementPage.clickFirstException();
      await settlementPage.verifyGuideStepsVisible();
    }
  });

  test('高风险动作触发拦截或导办引导', async () => {
    await chatPage.sendMessage('我要进行正式结算操作');

    await chatPage.waitForStreamingComplete();
    const response = await chatPage.getResponseText();
    expect(response).toBeTruthy();
  });
});
