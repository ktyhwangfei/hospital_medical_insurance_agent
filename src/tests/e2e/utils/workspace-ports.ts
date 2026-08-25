function requiredPort(name: 'E2E_BACKEND_PORT' | 'E2E_FRONTEND_PORT'): number {
  const port = Number(process.env[name]);
  if (!Number.isInteger(port) || port <= 0) {
    throw new Error(`${name} 未设置；请通过 run-playwright.mjs 运行 E2E`);
  }
  return port;
}

export const E2E_BACKEND_URL = `http://127.0.0.1:${requiredPort('E2E_BACKEND_PORT')}`;
export const E2E_FRONTEND_URL = `http://127.0.0.1:${requiredPort('E2E_FRONTEND_PORT')}`;
