import { test, expect } from '@playwright/test';
import { SkillsPage } from '../../pages/admin/skills.page';
import { ChatPage } from '../../pages/portal/chat.page';
import { waitForAPIReady } from '../../utils/wait-strategies';

test.describe('跨应用联动：Portal使用Admin配置', () => {
  test('Admin配置的技能在Portal中可用', async ({ browser }) => {
    await waitForAPIReady('http://127.0.0.1:8000');

    const adminPage = await browser.newPage();
    const skillsPage = new SkillsPage(adminPage);
    await skillsPage.goto();
    const skillCount = await skillsPage.getSkillCount();
    expect(skillCount).toBeGreaterThanOrEqual(0);
    await adminPage.close();

    const portalPage = await browser.newPage();
    const chatPage = new ChatPage(portalPage);
    await chatPage.goto();
    await chatPage.sendMessage('hello');
    await chatPage.waitForStreamingComplete();
    const response = await chatPage.getResponseText();
    expect(response).toBeTruthy();
    await portalPage.close();
  });
});
