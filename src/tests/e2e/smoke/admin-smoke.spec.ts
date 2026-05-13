import { test, expect } from '@playwright/test';
import { MCPPage } from '../pages/admin/mcp.page';
import { KnowledgePage } from '../pages/admin/knowledge.page';
import { ModelPage } from '../pages/admin/model.page';
import { SkillsPage } from '../pages/admin/skills.page';

test.describe('Admin 冒烟测试', () => {
  test('MCP 管理页面加载', async ({ page }) => {
    const mcpPage = new MCPPage(page);
    await mcpPage.goto();
    await expect(page).not.toHaveTitle(/error/i);
  });

  test('知识管理页面加载', async ({ page }) => {
    const knowledgePage = new KnowledgePage(page);
    await knowledgePage.goto();
    await expect(page).not.toHaveTitle(/error/i);
  });

  test('模型管理页面加载', async ({ page }) => {
    const modelPage = new ModelPage(page);
    await modelPage.goto();
    await expect(page).not.toHaveTitle(/error/i);
  });

  test('技能管理页面加载', async ({ page }) => {
    const skillsPage = new SkillsPage(page);
    await skillsPage.goto();
    await expect(page).not.toHaveTitle(/error/i);
  });

  test('Admin 管理首页加载', async ({ page }) => {
    await page.goto('http://127.0.0.1:3001/');
    await expect(page).not.toHaveTitle(/error/i);
  });
});
