import { test, expect } from '@playwright/test';
import { MCPPage } from '../../pages/admin/mcp.page';
import { createTestServer, cleanupTestServer } from '../../utils/api-helpers';

test.describe('MCP 服务器生命周期', () => {
  let mcpPage: MCPPage;
  const serverName = `test-drg-server-${Date.now()}`;

  test.beforeEach(async ({ page }) => {
    mcpPage = new MCPPage(page);
    await mcpPage.goto();
  });

  test('注册→发现→删除', async () => {
    await mcpPage.registerServer({
      name: serverName,
      endpoint: 'http://localhost:9999',
      transport: 'stdio',
    });

    await expect(mcpPage.getServerRow(serverName)).toBeVisible({ timeout: 5000 });

    await mcpPage.viewServerCapabilities(serverName);
    await expect(mcpPage.capabilityList).toBeVisible();

    await mcpPage.deleteServer(serverName);
    await expect(mcpPage.getServerRow(serverName)).not.toBeVisible({ timeout: 5000 });
  });

  test('MCP 存储健康检查', async () => {
    await mcpPage.checkHealth();
  });

  test.afterEach(async () => {
    await cleanupTestServer(serverName);
  });
});
