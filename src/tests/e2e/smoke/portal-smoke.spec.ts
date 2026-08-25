import { test, expect } from '@playwright/test';
import { PolicyQAPage } from '../pages/portal/policy-qa.page';

test.describe('Portal 冒烟测试', () => {
  test('根路径进入唯一业务入口 policy-qa', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveURL(/\/policy-qa$/);
  });

  test('政策问答页面加载', async ({ page }) => {
    const policyQAPage = new PolicyQAPage(page);
    await policyQAPage.goto();
    await expect(policyQAPage.composer).toBeVisible();
  });

  for (const route of ['/settlement', '/qc', '/dashboard']) {
    test(`${route} 已退役并返回 404`, async ({ page }) => {
      const response = await page.goto(route);
      expect(response?.status()).toBe(404);
    });
  }
});
