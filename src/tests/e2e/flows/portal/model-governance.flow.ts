import { expect, test } from '@playwright/test';

import { ModelGovernancePage } from '../../pages/portal/model-governance.page';

test('信息科从 Portal 导航读取真实模型治理快照', async ({ page }) => {
  const governance = new ModelGovernancePage(page);
  await governance.useMobileViewport();
  await governance.goto();

  await expect(governance.roleSwitcher).toContainText('收费员');
  await expect(governance.modelGovernanceLink).toHaveCount(0);

  await governance.switchToInformationDepartment();
  await expect(governance.modelGovernanceLink).toBeVisible();

  const snapshotResponse = await governance.openAndWaitForSnapshot();
  expect(snapshotResponse.status()).toBe(200);
  await expect(governance.title).toBeVisible();
  await expect(governance.promptLedgerTitle).toBeVisible();
  expect(await governance.hasNoHorizontalOverflow()).toBe(true);
});
