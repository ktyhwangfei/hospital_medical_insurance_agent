import { test, expect } from '@playwright/test';
import { ChatPage } from '../../pages/portal/chat.page';
import { waitForAPIReady } from '../../utils/wait-strategies';

test.describe('Chat UX — Auto-scroll behavior', () => {
  let chat: ChatPage;

  test.beforeAll(async () => {
    await waitForAPIReady('http://127.0.0.1:8000');
  });

  test.beforeEach(async ({ page }) => {
    chat = new ChatPage(page);
    await chat.goto();
  });

  test('should auto-scroll to bottom on new message', async ({ page }) => {
    await chat.sendMessage('测试消息');

    // Wait for streaming to complete
    await page.waitForSelector('[data-testid="streaming-indicator"]', {
      state: 'hidden',
      timeout: 60000,
    });

    // Check that viewport is scrolled to bottom (within 50px)
    const isAtBottom = await page.evaluate(() => {
      const vp = document.querySelector('[data-testid="chat-viewport"]');
      if (!vp) return false;
      return vp.scrollTop + vp.clientHeight >= vp.scrollHeight - 50;
    });
    expect(isAtBottom).toBe(true);
  });

  test('should scroll during streaming content output', async ({ page }) => {
    await chat.sendMessage('测试消息');

    // Wait a bit for streaming to start
    await page.waitForTimeout(3000);

    // Check viewport is near bottom during streaming
    const isNearBottom = await page.evaluate(() => {
      const vp = document.querySelector('[data-testid="chat-viewport"]');
      if (!vp) return false;
      return vp.scrollTop + vp.clientHeight >= vp.scrollHeight - 100;
    });
    expect(isNearBottom).toBe(true);
  });
});

test.describe('Chat UX — Loading spinner states', () => {
  let chat: ChatPage;

  test.beforeAll(async () => {
    await waitForAPIReady('http://127.0.0.1:8000');
  });

  test.beforeEach(async ({ page }) => {
    chat = new ChatPage(page);
    await chat.goto();
  });

  test('should show loading spinner when sending message', async ({ page }) => {
    await chat.sendMessage('测试消息');

    // Check that streaming indicator appears
    await expect(page.locator('[data-testid="streaming-indicator"]')).toBeVisible({
      timeout: 10000,
    });
  });

  test('should hide loading spinner after response completes', async ({ page }) => {
    await chat.sendMessage('测试消息');

    // Wait for streaming to complete (with safety timeout)
    await page.waitForSelector('[data-testid="streaming-indicator"]', {
      state: 'hidden',
      timeout: 60000,
    });

    // Verify loader is hidden
    await expect(page.locator('[data-testid="loader-icon"]')).not.toBeVisible();
  });

  test('should recover chat input after streaming ends', async ({ page }) => {
    await chat.sendMessage('测试消息');

    // Wait for streaming to complete
    await page.waitForSelector('[data-testid="streaming-indicator"]', {
      state: 'hidden',
      timeout: 60000,
    });

    // Verify input is re-enabled
    await expect(page.locator('[data-testid="chat-input"]')).toBeEnabled();
  });
});
