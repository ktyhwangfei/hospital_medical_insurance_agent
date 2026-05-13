# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: .workbuddy\front-diagnostics.spec.js >> diagnose front click path
- Location: .workbuddy\front-diagnostics.spec.js:3:1

# Error details

```
TimeoutError: page.goto: Timeout 15000ms exceeded.
Call log:
  - navigating to "http://127.0.0.1:3000/", waiting until "domcontentloaded"

```

# Test source

```ts
  1  | const { test, chromium } = require('@playwright/test')
  2  | 
  3  | test('diagnose front click path', async () => {
  4  |   const browser = await chromium.launch({ channel: 'msedge', headless: true })
  5  |   const page = await browser.newPage()
  6  | 
  7  |   page.on('console', (msg) => console.log('CONSOLE', msg.type(), msg.text()))
  8  |   page.on('pageerror', (err) => console.log('PAGEERROR', err.message))
  9  |   page.on('request', (req) => {
  10 |     if (req.url().includes('/api/v1/')) {
  11 |       console.log('REQUEST', req.method(), req.url())
  12 |     }
  13 |   })
  14 |   page.on('requestfailed', (req) => {
  15 |     console.log('REQFAILED', req.method(), req.url(), req.failure()?.errorText)
  16 |   })
  17 |   page.on('response', (res) => {
  18 |     if (res.url().includes('/api/v1/')) {
  19 |       console.log('RESPONSE', res.status(), res.url())
  20 |     }
  21 |   })
  22 | 
> 23 |   await page.goto('http://127.0.0.1:3000', { waitUntil: 'domcontentloaded', timeout: 15000 })
     |              ^ TimeoutError: page.goto: Timeout 15000ms exceeded.
  24 |   await page.getByText('为什么这个患者结算失败').click({ timeout: 5000 })
  25 |   await page.waitForTimeout(9000)
  26 | 
  27 |   const body = await page.locator('body').innerText()
  28 |   console.log(
  29 |     'BODY_FLAGS',
  30 |     body.includes('已定位医保结算异常'),
  31 |     body.includes('已连接'),
  32 |     body.includes('请求失败')
  33 |   )
  34 |   console.log('BODY_HEAD', body.slice(0, 1200).replace(/\n/g, ' | '))
  35 | 
  36 |   await browser.close()
  37 | })
  38 | 
```