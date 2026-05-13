import { test, expect } from '@playwright/test';
import { ModelPage } from '../../pages/admin/model.page';

test.describe('模型配置流程', () => {
  let modelPage: ModelPage;

  test.beforeEach(async ({ page }) => {
    modelPage = new ModelPage(page);
    await modelPage.goto();
  });

  test('模型配置页面加载', async () => {
    const providerCount = await modelPage.getProviderCount();
    expect(providerCount).toBeGreaterThanOrEqual(0);
  });

  test('注册 Provider 并测试连通性', async () => {
    const providerName = `test-provider-${Date.now() % 10000}`;
    await modelPage.registerProvider({
      name: providerName,
      endpoint: 'https://api.openai.com/v1',
    });

    await modelPage.testProvider(providerName);
    await modelPage.verifyTestResult();
  });
});
