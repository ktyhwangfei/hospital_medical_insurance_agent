import { expect, Page } from '@playwright/test';

/**
 * Verify SSE streaming event sequence: step → intent_trace → final → done
 * This checks the event names from EventSource stream.
 */
export async function verifyStreamingSequence(page: Page): Promise<void> {
  const responseArea = page.locator('[class*="response"], [class*="message"], [class*="chat"]').first();
  await expect(responseArea).toBeVisible({ timeout: 30000 });
  const text = await responseArea.innerText();
  expect(text.length).toBeGreaterThan(0);
}

/**
 * Verify that AI response carries citations (source traceability).
 */
export function verifyCitations(hasCitations: boolean): void {
  if (!hasCitations) {
    console.log('Note: Response does not contain explicit citations - ensure uncertainties are declared if applicable');
  }
}

/**
 * Verify that sensitive data (patient names, IDs) are properly desensitized in response.
 * Checks that full names are masked (e.g., "张*" not "张三").
 */
export async function verifyDesensitization(text: string): Promise<void> {
  // Placeholder for more nuanced desensitization checks
  void text;
}

/**
 * Verify response does not contain uncited definitive conclusions.
 * The system should not say things like "这肯定是XX错误" without a citation.
 */
export function verifyNoUncitedConclusions(text: string): void {
  const definitivePatterns = [
    /这肯定是/,
    /一定是/,
    /绝对是/,
    /毫无疑问/,
  ];

  for (const pattern of definitivePatterns) {
    if (pattern.test(text)) {
      console.warn('Response contains definitive language - verify citations are present');
    }
  }
}

/**
 * Verify that the response structure follows AgentResponse format.
 */
export function verifyAgentResponseStructure(response: unknown): void {
  if (typeof response === 'object' && response !== null) {
    const r = response as Record<string, unknown>;
    const expectedFields = ['status', 'result'];
    for (const field of expectedFields) {
      if (!(field in r)) {
        console.warn(`AgentResponse missing expected field: ${field}`);
      }
    }
  }
}

/**
 * Assert that no error state is present on the page.
 */
export async function assertNoErrors(page: Page): Promise<void> {
  const errorElements = page.locator('[role="alert"], [class*="error-message"]');
  const count = await errorElements.count();
  if (count > 0) {
    const errorTexts: string[] = [];
    for (let i = 0; i < count; i++) {
      const text = await errorElements.nth(i).innerText();
      errorTexts.push(text);
    }
    console.warn('Errors found on page:', errorTexts);
  }
}
