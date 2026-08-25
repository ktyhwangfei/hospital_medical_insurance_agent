import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const governanceFlow = 'flows/portal/model-governance.flow.ts';
const args = process.argv.slice(2);
const explicitlyRunsGovernance = args.some((arg) =>
  arg.replaceAll('\\', '/').endsWith(governanceFlow));
const cli = fileURLToPath(new URL('./node_modules/@playwright/test/cli.js', import.meta.url));
const ports = JSON.parse(
  readFileSync(new URL('../../../.server-ports.json', import.meta.url), 'utf8').replace(/^\uFEFF/, ''),
);
const env = {
  ...process.env,
  E2E_BACKEND_PORT: process.env.E2E_BACKEND_PORT ?? String(ports.backend_port),
  E2E_FRONTEND_PORT: process.env.E2E_FRONTEND_PORT ?? String(ports.frontend_port),
};
const configArgs = explicitlyRunsGovernance
  ? ['--config=model-governance.playwright.config.ts']
  : [];
const result = spawnSync(process.execPath, [cli, 'test', ...configArgs, ...args], {
  stdio: 'inherit',
  env,
});

process.exit(result.status ?? 1);
