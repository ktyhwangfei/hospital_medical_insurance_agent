import { expect, Page, test } from '@playwright/test';

import { SkillCatalogPage } from '../../pages/portal/skill-catalog.page';

const API_PREFIX = '/api/v1/medical-insurance-ai-agent';
const CONFIG = {
  basic: {
    skill_id: 'ai_settlement_explain',
    skill_name: 'AI 结算解释',
    description: '解释结算自付金额',
    owner: 'skill-team',
  },
  business_mounting: {
    business_action: 'explain',
    business_object: 'settlement',
    include_keywords: ['自付'],
    excluded_intents: [],
  },
  inputs: [{ metric_code: 'settlement.self_pay_amount', alias: 'self_pay_amount', required: true, purpose: '解释自付' }],
  schemas: { input: { type: 'object' }, output: { type: 'object' } },
};
const RAW_FILES = {
  'assembler.py': 'def assemble(data):\n    return {"answer": str(data.get("self_pay_amount", 0))}\n',
  'prompt_template.yaml': 'system: explain settlement\n',
};
const PROVENANCE = {
  model_type: 'authoring-model',
  scene: 'skill_authoring',
  prompt_version: 'v1',
  metric_versions: [{ metric_code: 'settlement.self_pay_amount', object_code: 'settlement', object_version: 1, status: 'published' }],
  generated_at: '2026-08-10T09:00:00Z',
  content_hash: 'a'.repeat(64),
};

function json(route: Parameters<Parameters<Page['route']>[1]>[0], body: unknown, status = 200) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}

async function mockAuthoringAPI(page: Page): Promise<void> {
  let revision = 1;
  let status = 'editing';

  await page.route(`**${API_PREFIX}/**`, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const draft = {
      draft_id: 'draft-ai-1',
      skill_id: CONFIG.basic.skill_id,
      skill_name: CONFIG.basic.skill_name,
      status,
      source_type: 'ai_generated',
      structured_config: CONFIG,
      raw_files: RAW_FILES,
      validation_report: null,
      validation_blocking_ok: status === 'validated',
      revision,
      etag: `etag-${revision}`,
      created_at: '2026-08-10T09:00:00Z',
      updated_at: '2026-08-10T09:00:00Z',
      created_by: 'e2e-user',
    };

    if (path.endsWith('/semantic/skill-inputs/selector')) {
      return json(route, {
        tree: [{
          domain_code: 'medical_insurance', name: '医保', objects: [{
            object_code: 'settlement', name: '结算', definition: '结算指标', status: 'published', current_version: 'v1',
            metrics: [{ metric_code: 'settlement.self_pay_amount', name: '结算自付金额', definition: '患者自付金额', source_type: 'field', status: 'published', current_version: 'v1', quality_score: 1 }],
          }],
        }],
      });
    }
    if (path.endsWith('/infra-skills/ai-generate')) {
      return json(route, {
        generation_id: 'generation-1', proposal_hash: 'b'.repeat(64), structured_config: CONFIG,
        raw_files: RAW_FILES, validation_preview: { issues: [], has_blocking: false, blocking_ok: true },
        provenance: PROVENANCE, citations: [{ source_id: 'metric:settlement.self_pay_amount@1', summary: '已发布指标', url: null }], uncertainties: [],
      });
    }
    if (path.endsWith('/infra-skills/drafts/from-ai')) return json(route, draft, 201);
    if (path.endsWith('/infra-skills/drafts/draft-ai-1/ai-optimize')) {
      return json(route, {
        base_revision: revision, proposal_hash: 'c'.repeat(64), structured_config: CONFIG, raw_files: RAW_FILES,
        validation_preview: { issues: [], has_blocking: false, blocking_ok: true }, provenance: PROVENANCE,
        diff: [{ scope: 'field', change_type: 'changed', path: 'basic.description', before: '解释结算自付金额', after: '简洁解释结算自付金额' }], citations: [], uncertainties: [],
      });
    }
    if (path.endsWith('/infra-skills/drafts/draft-ai-1') && request.method() === 'PATCH') {
      revision += 1;
      return json(route, { ...draft, revision, etag: `etag-${revision}` });
    }
    if (path.endsWith('/infra-skills/drafts/draft-ai-1') && request.method() === 'GET') return json(route, draft);
    if (path.endsWith('/infra-skills/drafts/draft-ai-1/validate')) {
      revision += 1;
      status = 'validated';
      return json(route, { draft_id: 'draft-ai-1', issues: [], has_blocking: false, blocking_ok: true, revision });
    }
    if (path.endsWith('/candidate-evaluations/routes')) {
      return json(route, {
        artifact_hash: 'd'.repeat(64), case_snapshot_hash: 'e'.repeat(64), status: 'completed', blocked_reason: null, results: [],
        metrics: { total: 1, passed: 1, required_total: 1, required_passed: 1, top1_accuracy: 1, baseline_top1_accuracy: 0, regression_count: 0, new_false_takeover_count: 0, gate_passed: true },
      });
    }
    if (path.endsWith('/candidate-evaluations/behavior')) {
      return json(route, { artifact_hash: 'd'.repeat(64), case_snapshot_hash: 'f'.repeat(64), status: 'completed', blocked_reason: null, results: [{ case_id: 'behavior-1', status: 'passed', passed: true, output: { answer: '100' }, blocked_reason: null }] });
    }
    return json(route, { error_code: 'E2E_UNHANDLED', message: path, audit_event: null }, 500);
  });
}

test.describe('Skill AI 创作主链路', () => {
  test('从已发布指标生成草稿，人工接受、优化、校验并评测候选版本', async ({ page }) => {
    await mockAuthoringAPI(page);
    const skills = new SkillCatalogPage(page);

    await skills.gotoAIAuthoring();
    await skills.generateAndAcceptAIDraft('结算自付金额 (settlement.self_pay_amount)', '创建一个结算自付解释 Skill');
    await expect(page.getByText('状态: editing')).toBeVisible();
    await skills.optimizeValidateAndEvaluateCandidate();
    await expect(page.getByText('状态: validated')).toBeVisible();

    await page.setViewportSize({ width: 390, height: 844 });
    const noHorizontalOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    );
    expect(noHorizontalOverflow).toBe(true);
  });
});
