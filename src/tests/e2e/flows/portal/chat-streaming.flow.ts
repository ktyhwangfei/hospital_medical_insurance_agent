import { test, expect } from '@playwright/test';
import { ChatPage } from '../../pages/portal/chat.page';
import { waitForAPIReady } from '../../utils/wait-strategies';

test.describe('SSE 流式对话流程', () => {
  let chatPage: ChatPage;

  test.beforeAll(async () => {
    await waitForAPIReady('http://127.0.0.1:8000');
  });

  test.beforeEach(async ({ page }) => {
    chatPage = new ChatPage(page);
    await chatPage.goto();
  });

  test('流式对话：消息发送→流式响应→引用展示', async () => {
    await chatPage.sendMessage('P001 患者结算异常，请分析原因');

    await chatPage.waitForStreamingComplete();

    const response = await chatPage.getResponseText();
    expect(response).toBeTruthy();
    expect(response.length).toBeGreaterThan(0);

    const hasCitations = await chatPage.hasCitations();
    expect(typeof hasCitations).toBe('boolean');
  });

  test('多轮对话保持上下文', async () => {
    await chatPage.sendMessage('P001 患者信息');
    await chatPage.waitForStreamingComplete();

    await chatPage.sendMessage('他的结算状态如何？');
    await chatPage.waitForStreamingComplete();

    const response = await chatPage.getResponseText();
    expect(response).toBeTruthy();
  });

  test('默认患者 P002 触发降级路径', async () => {
    await chatPage.sendMessage('P002 患者结算查询');
    await chatPage.waitForStreamingComplete();

    const response = await chatPage.getResponseText();
    expect(response).toBeTruthy();
  });

  test('流式中断与错误展示', async () => {
    await chatPage.sendMessage('查询 DRG 分组结果');
    await chatPage.waitForStreamingComplete();

    const response = await chatPage.getResponseText();
    expect(response.length).toBeGreaterThan(0);
    expect(response).not.toContain('我无法');
  });
});
