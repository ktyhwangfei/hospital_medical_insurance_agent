import { test, expect } from '@playwright/test';
import { EmbedChatWidgetPage } from '../../pages/embed/chat-widget.page';

test.describe('Embed Widget 独立对话', () => {
  let embedPage: EmbedChatWidgetPage;

  test.beforeEach(async ({ page }) => {
    embedPage = new EmbedChatWidgetPage(page);
    await embedPage.goto();
  });

  test('Widget 加载并展示基础对话', async () => {
    await embedPage.isWidgetLoaded();

    await embedPage.sendMessage('查询结算异常');

    await embedPage.waitForResponse();
    const response = await embedPage.getResponseText();
    expect(response).toBeTruthy();
    expect(response.length).toBeGreaterThan(0);
  });
});
