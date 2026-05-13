import { Page, Locator } from '@playwright/test';
import { BasePage } from '../base.page';

/**
 * EmbedChatWidgetPage encapsulates the embedded Chat Widget (http://127.0.0.1:3002/).
 */
export class EmbedChatWidgetPage extends BasePage {
  readonly widgetContainer: Locator;
  readonly messageInput: Locator;
  readonly sendButton: Locator;
  readonly responseArea: Locator;
  readonly loadingIndicator: Locator;

  constructor(page: Page) {
    super(page, 'http://127.0.0.1:3002');

    this.widgetContainer = page.locator('[class*="widget"], [class*="embed"]');
    this.messageInput = page.getByRole('textbox').or(page.getByPlaceholder(/输入|Type|Message/i));
    this.sendButton = page.getByRole('button', { name: /发送|send|submit/i });
    this.responseArea = page.locator('[class*="response"], [class*="message"], [class*="chat"]').first();
    this.loadingIndicator = page.locator('[class*="loading"], [class*="spinner"], [class*="streaming"]');
  }

  /**
   * Navigate to the embedded widget root and wait for the page to load.
   */
  async goto(): Promise<void> {
    await super.goto('/');
  }

  /**
   * Type a message and click the send button, then wait for a response
   * element to appear.
   */
  async sendMessage(text: string): Promise<void> {
    await this.messageInput.fill(text);
    await this.sendButton.click();
    await this.responseArea.waitFor({ state: 'visible', timeout: 30_000 });
  }

  /**
   * Return the inner text of the response area.
   */
  async getResponseText(): Promise<string> {
    return this.responseArea.innerText();
  }

  /**
   * Wait until the loading indicator is no longer visible.
   */
  async waitForResponse(): Promise<void> {
    await this.loadingIndicator.first().waitFor({ state: 'hidden', timeout: 60_000 });
  }

  /**
   * Assert that the main widget container is visible.
   */
  async isWidgetLoaded(): Promise<boolean> {
    return this.widgetContainer.isVisible();
  }
}
