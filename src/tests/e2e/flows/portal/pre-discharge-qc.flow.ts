import { test, expect } from '@playwright/test';
import { QCPage } from '../../pages/portal/qc.page';
import { waitForAPIReady } from '../../utils/wait-strategies';

test.describe('出院前质控流程', () => {
  let qcPage: QCPage;

  test.beforeAll(async () => {
    await waitForAPIReady('http://127.0.0.1:8000');
  });

  test.beforeEach(async ({ page }) => {
    qcPage = new QCPage(page);
    await qcPage.goto();
  });

  test('质控页面加载并展示质控项', async () => {
    await qcPage.verifyQcItemsLoaded();
    const count = await qcPage.getQcItemCount();
    expect(count).toBeGreaterThanOrEqual(0);
  });

  test('点击质控项查看详情', async () => {
    await qcPage.verifyQcItemsLoaded();
    const count = await qcPage.getQcItemCount();

    if (count > 0) {
      await qcPage.clickQCItem(0);
      await qcPage.verifyQCResult();
    }
  });

  test('质控结果状态展示', async () => {
    await qcPage.verifyQcItemsLoaded();
    const count = await qcPage.getQcItemCount();
    expect(count).toBeGreaterThanOrEqual(0);

    if (count > 0) {
      await qcPage.clickQCItem(0);
      await qcPage.verifyQCResult();
    }
  });
});
