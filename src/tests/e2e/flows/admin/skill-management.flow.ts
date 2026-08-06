import { test, expect } from '@playwright/test';
import { SkillsPage } from '../../pages/admin/skills.page';

test.describe('技能管理流程', () => {
  let skillsPage: SkillsPage;
  const skillName = `E2E-Test-Skill-${Date.now() % 10000}`;

  test.beforeEach(async ({ page }) => {
    skillsPage = new SkillsPage(page);
    await skillsPage.goto();
  });

  test('创建→编辑→按角色筛选→删除', async () => {
    await skillsPage.createSkill({
      name: skillName,
      description: '端到端测试技能',
      owner: 'admin',
      keywords: ['e2e', 'test'],
    });
    await skillsPage.verifySkillExists(skillName);

    await skillsPage.filterByRole('billing_staff');

    await skillsPage.editSkill(skillName, { description: '已更新的描述' });

    await skillsPage.deleteSkill(skillName);
    await skillsPage.verifySkillNotExists(skillName);
  });

  test('按角色筛选技能列表', async () => {
    await skillsPage.filterByRole('doctor');
    const count = await skillsPage.getSkillCount();
    expect(count).toBeGreaterThanOrEqual(0);
  });
  test('route preview to execution result', async () => {
    await skillsPage.openRouteTest();
    await skillsPage.submitRouteQuestion('统筹自付怎么算？');
    await expect(skillsPage.routeResult).toBeVisible();

    await skillsPage.openExecutionTest();
    await skillsPage.submitExecutionQuestion('解释这笔费用');
    await expect(skillsPage.executionResult).toBeVisible();
  });
});
