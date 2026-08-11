import { expect, test } from '@playwright/test';

import { SkillCatalogPage } from '../../pages/portal/skill-catalog.page';

const SKILL_ID = 'settlement_explain_skill';

test.describe('Skill 日常治理工作台', () => {
  test.describe.configure({ mode: 'serial' });

  test('从当前事实推进到人工复审和 Test Shadow', async ({ page }) => {
    const workbench = new SkillCatalogPage(page);
    await workbench.mockGovernanceLoop();
    await workbench.goto();
    await expect(workbench.title).toBeVisible();
    await expect(workbench.queue).toBeVisible();
    await workbench.registerCurrentVersion(SKILL_ID);
    await workbench.runFixedEvaluation();
    await workbench.approveAndActivateTestRelease();

    await expect(workbench.lifecycle).toContainText('发布');
    await expect(workbench.lifecycle).toContainText('已完成');
    await expect(workbench.text('Test Active').first()).toBeVisible();
    await page.reload();
    await expect(page).toHaveURL(/skill=settlement_explain_skill/);
    await expect(workbench.lifecycle).toContainText('发布');
    await expect(workbench.text('Test Active').first()).toBeVisible();
  });

  test('路由抽屉关闭后保留选中 Skill', async ({ page }) => {
    const workbench = new SkillCatalogPage(page);
    await workbench.goto();
    await workbench.selectSkill(SKILL_ID);

    await workbench.button('路由调试').click();
    await expect(workbench.routeDrawer).toBeVisible();
    await workbench.button('关闭路由调试').click();

    await expect(workbench.catalogItem(SKILL_ID)).toHaveAttribute('aria-current', 'true');
    await expect(page).toHaveURL(/skill=settlement_explain_skill/);
  });

  test('待办键盘方向键只移动焦点，Enter 才打开', async ({ page }) => {
    const workbench = new SkillCatalogPage(page);
    await workbench.mockTwoItemQueue();
    await workbench.goto();

    await workbench.assertQueueKeyboardSemantics();
  });

  test('宽屏与 2xl 三区布局可读且无页面溢出', async ({ page }) => {
    const workbench = new SkillCatalogPage(page);
    await page.setViewportSize({ width: 1440, height: 1000 });
    await workbench.goto();
    await workbench.selectSkill(SKILL_ID);
    await expect(workbench.queue).toBeVisible();
    await expect(workbench.decision).toBeVisible();
    await expect(workbench.evidence).toBeHidden();
    await workbench.openEvidenceDrawer();
    await expect(workbench.evidenceDrawer).toContainText('门禁结论');
    await workbench.button('关闭治理证据').click();
    await workbench.assertNoPageOverflow();
    await workbench.capture('skill-governance-1440');

    await page.setViewportSize({ width: 1600, height: 1000 });
    await expect(workbench.evidence).toBeVisible();
    await expect(workbench.queue).toBeVisible();
    await expect(workbench.decision).toBeVisible();
    await workbench.assertNoPageOverflow();
    await workbench.capture('skill-governance-1600');
  });

  test('1024 待办与决策可用，证据通过抽屉打开', async ({ page }) => {
    const workbench = new SkillCatalogPage(page);
    await page.setViewportSize({ width: 1024, height: 900 });
    await workbench.goto();
    await workbench.selectSkill(SKILL_ID);

    await expect(workbench.queue).toBeVisible();
    await expect(workbench.decision).toBeVisible();
    await expect(workbench.evidenceButton).toBeVisible();
    await workbench.openEvidenceDrawer();
    await expect(workbench.evidenceDrawer).toBeVisible();
    await workbench.assertNoPageOverflow();
    await workbench.capture('skill-governance-1024');
  });

  test('390 详情可返回待办并恢复焦点', async ({ page }) => {
    const workbench = new SkillCatalogPage(page);
    await workbench.mockFailedEvaluation({ next_action: 'run_evaluation', current_stage: 'evaluate' });
    await page.setViewportSize({ width: 390, height: 844 });
    await workbench.goto();
    await expect(workbench.queue).toBeVisible();
    await workbench.selectSkill(SKILL_ID);

    await expect(workbench.mobileBack).toBeFocused();
    await expect(workbench.primaryAction).toBeVisible();
    await workbench.primaryAction.focus();
    await expect(workbench.primaryAction).toBeFocused();
    await workbench.assertTitleDoesNotBreakPerCharacter();
    await workbench.assertNoPageOverflow();
    await workbench.capture('skill-governance-390');
    await workbench.assertMobileReturnRestoresFocus(SKILL_ID);
  });

  test('200% 缩放等价下核心任务仍可操作', async ({ page }) => {
    const workbench = new SkillCatalogPage(page);
    await page.setViewportSize({ width: 720, height: 500 });
    await workbench.goto();
    await workbench.setCssZoom('2');
    await expect(workbench.queue).toBeVisible();
    await workbench.selectSkill(SKILL_ID);
    await expect(workbench.mobileBack).toBeVisible();
    await expect(workbench.evidenceButton).toBeVisible();
    await workbench.openEvidenceDrawer();
    await expect(workbench.evidenceDrawer).toContainText('门禁结论');
  });

  test('加载、无待办和筛选无匹配状态明确', async ({ page }) => {
    const workbench = new SkillCatalogPage(page);
    await workbench.mockLoading();
    await workbench.gotoWhileLoading();
    await expect(workbench.text('正在加载 Skill…')).toBeVisible();
    await expect(workbench.catalogItem(SKILL_ID)).toBeVisible();

    await page.unrouteAll({ behavior: 'wait' });
    await workbench.mockEmpty();
    await workbench.goto();
    await expect(workbench.text('当前没有需要处理的 Skill')).toBeVisible();
    await workbench.goto('?q=not-found');
    await expect(workbench.text('没有符合筛选条件的 Skill')).toBeVisible();
    await expect(workbench.button('清除筛选')).toBeVisible();
  });

  test('局部发布错误不清空待办和评测证据', async ({ page }) => {
    const workbench = new SkillCatalogPage(page);
    await workbench.mockPartialReleaseError();
    await workbench.goto();
    await workbench.selectSkill(SKILL_ID);
    await workbench.showAllRegressionCases();

    await expect(workbench.alertWithText('发布记录加载失败')).toBeVisible();
    await expect(workbench.queue).toBeVisible();
    await expect(workbench.regressionTable).toContainText('case-high-risk');
    await workbench.assertNoSensitiveOrFullHash();
  });

  test('长原因与高风险失败可读，不泄露完整哈希', async ({ page }) => {
    const workbench = new SkillCatalogPage(page);
    const longReason = '高风险必测案例失败，需要先核对候选版本、冻结证据与路由差异，再由责任人修改并重新提交复审。';
    await workbench.mockFailedEvaluation({ next_action_reason: longReason });
    await workbench.goto();
    await workbench.selectSkill(SKILL_ID);
    await workbench.showAllRegressionCases();

    await expect(workbench.text(longReason).first()).toBeVisible();
    await expect(workbench.regressionTable).toContainText('高风险');
    await expect(workbench.regressionTable).toContainText('新增失败');
    await expect(workbench.button('创建发布候选')).toHaveCount(0);
    await workbench.assertNoSensitiveOrFullHash();
    await workbench.assertNoPageOverflow();
  });

  test('403 只读与 409 证据变化均保留当前上下文', async ({ page }) => {
    const workbench = new SkillCatalogPage(page);
    await workbench.mockFailedEvaluation({ next_action: 'run_evaluation', current_stage: 'evaluate' });
    await workbench.goto('?env=dev');
    await workbench.selectSkill(SKILL_ID);
    await expect(workbench.primaryAction).toBeDisabled();
    await expect(workbench.queue).toBeVisible();

    await page.unrouteAll({ behavior: 'wait' });
    await workbench.mockMutationError(403, '当前身份无权执行发布控制');
    await workbench.goto();
    await workbench.selectSkill(SKILL_ID);
    await workbench.primaryAction.click();
    await expect(workbench.alertWithText('当前身份无权执行发布控制')).toBeVisible();
    await expect(workbench.queue).toBeVisible();
    await expect(workbench.lifecycle).toBeVisible();

    await page.unrouteAll({ behavior: 'wait' });
    await workbench.goto(`?skill=${SKILL_ID}`);
    await workbench.triggerLiveVersionConflict(SKILL_ID);
    await expect(workbench.alertWithText('已绑定其他制品')).toBeVisible();
    await expect(workbench.queue).toBeVisible();
    await expect(workbench.lifecycle).toBeVisible();
    await workbench.assertSelectedSkillInURL(SKILL_ID);
    await workbench.assertNoSensitiveOrFullHash();
  });
});
