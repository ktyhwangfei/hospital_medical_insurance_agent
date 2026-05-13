const API_PREFIX = '/api/v1/medical-insurance-ai-agent';
const BACKEND_URL = 'http://127.0.0.1:8000';

export async function createTestServer(name: string, endpoint = 'http://localhost:9999', transport = 'stdio'): Promise<void> {
  try {
    await fetch(`${BACKEND_URL}${API_PREFIX}/mcp/servers`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        server_id: name,
        name: name,
        endpoint: endpoint,
        transport: transport,
        status: 'enabled',
      }),
    });
  } catch (e) {
    console.warn(`Failed to create test server ${name}:`, e);
  }
}

export async function cleanupTestServer(name: string): Promise<void> {
  try {
    await fetch(`${BACKEND_URL}${API_PREFIX}/mcp/servers/${name}`, { method: 'DELETE' });
  } catch (e) {
    console.warn(`Failed to cleanup test server ${name}:`, e);
  }
}

export async function createTestSkill(skillId: string, name: string, role = 'billing_staff'): Promise<void> {
  try {
    await fetch(`${BACKEND_URL}${API_PREFIX}/skills`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        skill_id: skillId,
        name: name,
        description: 'E2E test skill',
        owner: 'admin',
        steps: [],
        intent_keywords: ['e2e', 'test'],
        required_roles: [role],
        risk_level: 'low',
      }),
    });
  } catch (e) {
    console.warn(`Failed to create test skill:`, e);
  }
}

export async function cleanupTestSkill(skillId: string): Promise<void> {
  try {
    await fetch(`${BACKEND_URL}${API_PREFIX}/skills/${skillId}`, { method: 'DELETE' });
  } catch (e) {
    console.warn(`Failed to cleanup test skill:`, e);
  }
}

export async function createTestKnowledge(type: string, id: string, data: Record<string, unknown>): Promise<void> {
  try {
    const paths: Record<string, string> = {
      errorCode: '/knowledge/error-codes',
      rule: '/knowledge/rules',
      asset: '/knowledge/assets',
      appealTemplate: '/knowledge/appeal-templates',
      promptTemplate: '/knowledge/prompt-templates',
    };
    await fetch(`${BACKEND_URL}${API_PREFIX}${paths[type]}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  } catch (e) {
    console.warn(`Failed to create test knowledge:`, e);
  }
}

export async function cleanupTestKnowledge(type: string, id: string): Promise<void> {
  try {
    const paths: Record<string, string> = {
      errorCode: `/knowledge/error-codes/${id}`,
      rule: `/knowledge/rules/${id}`,
      asset: `/knowledge/assets/${id}`,
      appealTemplate: `/knowledge/appeal-templates/${id}`,
      promptTemplate: `/knowledge/prompt-templates/${id}`,
    };
    await fetch(`${BACKEND_URL}${API_PREFIX}${paths[type]}`, { method: 'DELETE' });
  } catch (e) {
    console.warn(`Failed to cleanup test knowledge:`, e);
  }
}

export async function apiHealthCheck(): Promise<boolean> {
  try {
    const resp = await fetch(`${BACKEND_URL}/health`);
    return resp.ok;
  } catch {
    return false;
  }
}
