import { expect, test } from '@playwright/test';

import { SkillCatalogPage } from '../../pages/portal/skill-catalog.page';


test.describe('Skill 版本化资产库', () => {
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
});
