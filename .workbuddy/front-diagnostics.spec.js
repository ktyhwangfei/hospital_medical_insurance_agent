const { test, chromium } = require('@playwright/test')

test('diagnose front click path', async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true })
  const page = await browser.newPage()

  page.on('console', (msg) => console.log('CONSOLE', msg.type(), msg.text()))
  page.on('pageerror', (err) => console.log('PAGEERROR', err.message))
  page.on('request', (req) => {
    if (req.url().includes('/api/v1/')) {
      console.log('REQUEST', req.method(), req.url())
    }
  })
  page.on('requestfailed', (req) => {
    console.log('REQFAILED', req.method(), req.url(), req.failure()?.errorText)
  })
  page.on('response', (res) => {
    if (res.url().includes('/api/v1/')) {
      console.log('RESPONSE', res.status(), res.url())
    }
  })

  await page.goto('http://127.0.0.1:3000', { waitUntil: 'domcontentloaded', timeout: 15000 })
  await page.getByText('为什么这个患者结算失败').click({ timeout: 5000 })
  await page.waitForTimeout(9000)

  const body = await page.locator('body').innerText()
  console.log(
    'BODY_FLAGS',
    body.includes('已定位医保结算异常'),
    body.includes('已连接'),
    body.includes('请求失败')
  )
  console.log('BODY_HEAD', body.slice(0, 1200).replace(/\n/g, ' | '))

  await browser.close()
})
