import { Page, Locator } from '@playwright/test';
import { BasePage } from '../base.page';

/**
 * ChatPage encapsulates the Portal Chat导办 page (http://127.0.0.1:3000/).
 */
export class ChatPage extends BasePage {
  readonly messageInput: Locator;
  readonly sendButton: Locator;
  readonly responseArea: Locator;
  readonly streamingIndicator: Locator;
  readonly doneIndicator: Locator;
  readonly citations: Locator;
  readonly errorMessage: Locator;

  constructor(page: Page) {
    super(page, 'http://127.0.0.1:3000');

    this.messageInput = page.getByPlaceholder(/输入|Type|Message/i).or(page.getByRole('textbox'));
    this.sendButton = page.getByRole('button', { name: /发送|submit|send/i });
    this.responseArea = page.locator('[class*="response"], [class*="message"], [class*="chat"]').first();
    this.streamingIndicator = page.locator('[class*="streaming"], [class*="loading"]');
    this.doneIndicator = page.getByText('done');
    this.citations = page.locator('[class*="citation"]');
    this.errorMessage = page.locator('[class*="error"], [role="alert"]');
  }

  /**
   * Type a message into the chat input and click the send button.
   * Then waits for a response element to appear.
   */
  async sendMessage(text: string): Promise<void> {
    await this.messageInput.fill(text);
    await this.sendButton.click();
    await this.responseArea.waitFor({ state: 'visible', timeout: 30_000 });
  }

  /**
   * Send a message and then wait for the network to become idle.
   */
  async sendMessageAndWait(text: string): Promise<void> {
    await this.sendMessage(text);
    await this.waitForLoad();
  }

  /**
   * Poll until the streaming indicator is no longer visible (timeout 60 s).
   */
  async waitForStreamingComplete(): Promise<void> {
    await this.streamingIndicator.first().waitFor({ state: 'hidden', timeout: 60_000 });
  }

  /**
   * Return the combined inner text of all visible response-area elements.
   */
  async getResponseText(): Promise<string> {
    const count = await this.responseArea.count();
    const texts: string[] = [];
    for (let i = 0; i < count; i++) {
      texts.push(await this.responseArea.nth(i).innerText());
    }
    return texts.join('\n');
  }

  /**
   * Return true when at least one citation element is visible.
   */
  async hasCitations(): Promise<boolean> {
    return (await this.citations.count()) > 0;
  }

  /**
   * Return the number of citation elements on the page.
   */
  async getCitationCount(): Promise<number> {
    return this.citations.count();
  }

  /**
   * Return true when an error indicator is visible.
   */
  async isError(): Promise<boolean> {
    return this.errorMessage.isVisible();
  }

  /**
   * Click a navigation link matching the given path text.
   */
  async navigateTo(path: string): Promise<void> {
    await this.page.getByRole('link', { name: new RegExp(path, 'i') }).click();
    await this.waitForLoad();
  }
}
