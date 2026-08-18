import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const governanceFlow = 'flows/portal/model-governance.flow.ts';
const args = process.argv.slice(2);
const explicitlyRunsGovernance = args.some((arg) =>
  arg.replaceAll('\\', '/').endsWith(governanceFlow));
const cli = fileURLToPath(new URL('./node_modules/@playwright/test/cli.js', import.meta.url));
const configArgs = explicitlyRunsGovernance
  ? ['--config=model-governance.playwright.config.ts']
  : [];
const result = spawnSync(process.execPath, [cli, 'test', ...configArgs, ...args], {
  stdio: 'inherit',
});

process.exit(result.status ?? 1);
