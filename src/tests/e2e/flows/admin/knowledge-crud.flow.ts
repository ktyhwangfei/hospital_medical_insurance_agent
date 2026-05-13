import { test, expect } from '@playwright/test';
import { KnowledgePage } from '../../pages/admin/knowledge.page';

test.describe('知识管理 CRUD', () => {
  let knowledgePage: KnowledgePage;
  const errorCode = `TEST-ERR-${Date.now() % 100000}`;
  const ruleId = `TEST-RULE-${Date.now() % 100000}`;

  test.beforeEach(async ({ page }) => {
    knowledgePage = new KnowledgePage(page);
    await knowledgePage.goto();
  });

  test('错误码创建→查询→删除', async () => {
    await knowledgePage.switchTab('errorCodes');

    await knowledgePage.createItem('errorCode', {
      error_code: errorCode,
      description: 'E2E测试错误码',
      exception_type: 'test',
      responsible_role: 'billing_staff',
      recommendation: '联系管理员',
    });
    await knowledgePage.verifyItemExists('errorCode', errorCode);

    await knowledgePage.deleteItem('errorCode', errorCode);
    await knowledgePage.verifyItemNotExists('errorCode', errorCode);
  });

  test('规则创建→查询→删除', async () => {
    await knowledgePage.switchTab('rules');

    await knowledgePage.createItem('rule', {
      rule_id: ruleId,
      rule_name: 'E2E测试规则',
      category: 'test',
      scenario: 'e2e',
      rule_content: '测试内容',
    });
    await knowledgePage.verifyItemExists('rule', ruleId);

    await knowledgePage.deleteItem('rule', ruleId);
  });

  test('知识资产标签页切换', async () => {
    await knowledgePage.switchTab('assets');
    const count = await knowledgePage.getItemCount();
    expect(count).toBeGreaterThanOrEqual(0);

    await knowledgePage.switchTab('appealTemplates');
    const tplCount = await knowledgePage.getItemCount();
    expect(tplCount).toBeGreaterThanOrEqual(0);

    await knowledgePage.switchTab('promptTemplates');
    const prmCount = await knowledgePage.getItemCount();
    expect(prmCount).toBeGreaterThanOrEqual(0);
  });
});
