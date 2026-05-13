import type { Page, Response } from '@playwright/test';

/**
 * Wait for the backend API to be ready by polling the /health endpoint.
 * @param backendUrl - Backend URL (default: http://127.0.0.1:8000)
 * @param timeoutMs - Max wait time in ms (default: 60000)
 * @param intervalMs - Poll interval in ms (default: 2000)
 */
export async function waitForAPIReady(
  backendUrl = 'http://127.0.0.1:8000',
  timeoutMs = 60000,
  intervalMs = 2000
): Promise<void> {
  const startTime = Date.now();
  while (Date.now() - startTime < timeoutMs) {
    try {
      const resp = await fetch(`${backendUrl}/health`);
      if (resp.ok) {
        console.log(`Backend ready after ${Date.now() - startTime}ms`);
        return;
      }
    } catch {
      // Server not ready yet
    }
    await new Promise(resolve => setTimeout(resolve, intervalMs));
  }
  throw new Error(`Backend not ready after ${timeoutMs}ms`);
}

/**
 * Wait for SSE streaming to complete by checking for the absence of
 * streaming indicators and presence of completion markers.
 */
export async function waitForStreamingComplete(
  page: Page,
  options: { timeout?: number; checkInterval?: number } = {}
): Promise<void> {
  const { timeout = 60000, checkInterval = 1000 } = options;
  const startTime = Date.now();

  while (Date.now() - startTime < timeout) {
    const streamingElements = page.locator('[class*="streaming"], [class*="loading"], [class*="spinner"]');
    const count = await streamingElements.count();
    if (count === 0) {
      const errorElements = page.locator('[class*="error"], [role="alert"]');
      const errorCount = await errorElements.count();
      if (errorCount > 0) {
        console.warn('Streaming ended with error state');
      }
      return;
    }
    await page.waitForTimeout(checkInterval);
  }
  console.warn(`Streaming did not complete within ${timeout}ms`);
}

/**
 * Wait for frontend app to be ready by checking if the page has rendered.
 */
export async function waitForFrontendReady(
  url: string,
  timeoutMs = 30000,
  intervalMs = 2000
): Promise<void> {
  const startTime = Date.now();
  while (Date.now() - startTime < timeoutMs) {
    try {
      const resp = await fetch(url);
      if (resp.ok) {
        return;
      }
    } catch {
      // Not ready
    }
    await new Promise(resolve => setTimeout(resolve, intervalMs));
  }
  console.warn(`Frontend at ${url} not ready after ${timeoutMs}ms`);
}

/**
 * Wait for a network response matching a URL pattern.
 */
export async function waitForNetworkResponse(
  page: Page,
  urlPattern: string | RegExp,
  timeoutMs = 30000
): Promise<Response> {
  return page.waitForResponse(
    (response) => {
      const url = response.url();
      if (typeof urlPattern === 'string') {
        return url.includes(urlPattern);
      }
      return urlPattern.test(url);
    },
    { timeout: timeoutMs }
  );
}
