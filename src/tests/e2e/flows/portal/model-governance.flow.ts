import { expect, test } from '@playwright/test';

import { ModelGovernancePage } from '../../pages/portal/model-governance.page';

test('信息科管理模型、路由和提示词并回滚发布', async ({ page }) => {
  const governance = new ModelGovernancePage(page);
  await governance.goto();

  await expect(governance.roleSwitcher).toContainText('收费员');
  await expect(governance.modelGovernanceLink).toHaveCount(0);

  await governance.switchToInformationDepartment();
  await expect(governance.modelGovernanceLink).toBeVisible();

  const snapshotResponse = await governance.openAndWaitForSnapshot();
  expect(snapshotResponse.status()).toBe(200);
  await expect(governance.title).toBeVisible();
  await expect(governance.promptLedgerTitle).toBeVisible();

  const suffix = Date.now().toString();
  const profileId = `profile.e2e-${suffix}`;
  const routeId = `route.e2e-${suffix}`;
  const promptId = `prompt.e2e-${suffix}`;

  await governance.createModelProfile(profileId, 'deepseek-chat');
  await governance.completeReviewAndPublish(profileId);
  await governance.createRouteRule(routeId, `e2e-${suffix}`, profileId);
  await governance.completeReviewAndPublish(routeId);
  await governance.createPromptDraft(promptId, `问题：{question}`);
  await governance.completeReviewAndPublish(promptId);
  await governance.createPromptDraft(promptId, `问题二：{question}`);
  await governance.completeReviewAndPublish(promptId);
  await governance.rollbackToPreviousRelease(promptId);

  await expect(governance.assetCard(promptId).first()).toContainText('已发布，待接入');
  await governance.useMobileViewport();
  expect(await governance.hasNoHorizontalOverflow()).toBe(true);
});
