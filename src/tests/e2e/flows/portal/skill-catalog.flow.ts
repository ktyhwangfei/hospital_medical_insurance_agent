import { expect, test } from '@playwright/test';

import { SkillCatalogPage } from '../../pages/portal/skill-catalog.page';


test.describe('Skill 版本化资产库', () => {
  test.describe.configure({ mode: 'serial' });

  test('登记当前 Skill 版本并查看不可变证据', async ({ page }) => {
    const catalogPage = new SkillCatalogPage(page);

    await catalogPage.goto();
    await expect(catalogPage.title).toBeVisible();
    await expect(catalogPage.catalogTitle).toBeVisible();
    await expect(catalogPage.row('settlement_explain_skill')).toBeVisible();

    await catalogPage.registerCurrentVersion('settlement_explain_skill');

    await expect(catalogPage.versionEvidence).toContainText('artifact hash');
    await expect(catalogPage.versionEvidence).toContainText('Git commit');
    await expect(catalogPage.versionEvidence).toContainText('校验通过');
  });

  test('固定评测与人工审批后激活 test shadow release', async ({ page }) => {
    const catalogPage = new SkillCatalogPage(page);

    await catalogPage.goto();
    await catalogPage.registerCurrentVersion('settlement_explain_skill');
    await page.getByRole('button', { name: 'Close' }).click();
    await catalogPage.runFixedEvaluation(
      'settlement_explain_skill',
      '统筹自付为什么这么多',
    );
    await expect(catalogPage.evaluationSuite).toContainText('必测通过');

    await catalogPage.approveAndActivateTestRelease();

    await expect(catalogPage.releasePanel).toContainText('shadow');
    await expect(catalogPage.releasePanel).toContainText('test active');
  });
});
