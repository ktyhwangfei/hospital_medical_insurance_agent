import { expect, test } from '@playwright/test';

import { SkillCatalogPage } from '../../pages/portal/skill-catalog.page';


test.describe('Skill 治理工作台', () => {
  test.describe.configure({ mode: 'serial' });

  test('固定评测与人工审批后激活 Test Shadow 并刷新恢复', async ({ page }) => {
    const workbench = new SkillCatalogPage(page);
    await workbench.goto();
    await expect(workbench.title).toBeVisible();
    await workbench.registerCurrentVersion('settlement_explain_skill');
    await workbench.runFixedEvaluation('统筹自付为什么这么多');
    await workbench.approveAndActivateTestRelease();

    await expect(workbench.lifecycle).toContainText('Test 激活');
    await expect(page.getByText('Test Shadow 已激活')).toBeVisible();
    await page.reload();
    await expect(page).toHaveURL(/skill=settlement_explain_skill/);
    await expect(page.getByRole('tab', { name: '发布' })).toHaveAttribute('aria-selected', 'true');
  });

  test('路由抽屉关闭后保留选中 Skill', async ({ page }) => {
    const workbench = new SkillCatalogPage(page);
    await workbench.goto();
    await workbench.selectSkill('settlement_explain_skill');

    await page.getByRole('button', { name: '路由调试' }).click();
    await expect(workbench.routeDrawer).toBeVisible();
    await page.getByRole('button', { name: '关闭路由调试' }).click();

    await expect(page.getByTestId('skill-workspace-settlement_explain_skill')).toBeVisible();
    await expect(page).toHaveURL(/skill=settlement_explain_skill/);
  });

  test('窄屏目录可返回且页面无横向溢出', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const workbench = new SkillCatalogPage(page);
    await workbench.goto();
    await workbench.selectSkill('settlement_explain_skill');

    await expect(page.getByRole('button', { name: '返回 Skill 目录' })).toBeVisible();
    const noHorizontalOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    );
    expect(noHorizontalOverflow).toBe(true);
    await page.getByRole('button', { name: '返回 Skill 目录' }).click();
    await expect(workbench.catalogItem('settlement_explain_skill')).toBeVisible();
  });

  test('目录支持键盘方向键移动选择', async ({ page }) => {
    const workbench = new SkillCatalogPage(page);
    await workbench.goto();
    const items = page.locator('[data-skill-catalog-button]');
    const first = items.first();
    await first.focus();
    await page.keyboard.press('ArrowDown');
    if (await items.count() > 1) {
      await expect(items.nth(1)).toHaveAttribute('aria-current', 'true');
    } else {
      await expect(first).toHaveAttribute('aria-current', 'true');
    }
  });
});
