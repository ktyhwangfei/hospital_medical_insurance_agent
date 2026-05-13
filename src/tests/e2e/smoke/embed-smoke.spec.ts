import { test, expect } from '@playwright/test';
import { EmbedChatWidgetPage } from '../pages/embed/chat-widget.page';

test.describe('Embed 冒烟测试', () => {
  test('Embed Widget 加载', async ({ page }) => {
    const embedPage = new EmbedChatWidgetPage(page);
    await embedPage.goto();

    const loaded = await embedPage.isWidgetLoaded();
    expect(loaded).toBeTruthy();
  });

  test('Widget 基础对话交互', async ({ page }) => {
    const embedPage = new EmbedChatWidgetPage(page);
    await embedPage.goto();

    await embedPage.sendMessage('你好');
    await embedPage.waitForResponse();

    const response = await embedPage.getResponseText();
    expect(response).toBeTruthy();
    expect(response.length).toBeGreaterThan(0);
  });
});
