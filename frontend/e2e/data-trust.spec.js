import { expect, test } from '@playwright/test'

const username = process.env.E2E_ADMIN_USERNAME || 'e2e-admin'
const password = process.env.E2E_ADMIN_PASSWORD || 'e2e-admin-password-123'

async function login(page) {
  await page.goto('/login')
  const inputs = page.locator('.auth-card input')
  await inputs.nth(0).fill(username)
  await inputs.nth(1).fill(password)
  const responsePromise = page.waitForResponse(
    (response) => response.url().endsWith('/api/auth/login') && response.request().method() === 'POST'
  )
  await page.locator('.auth-card .btn').click()
  expect((await responsePromise).ok()).toBeTruthy()
  await expect(page).toHaveURL(/\/dashboard$/)
}

test('核心页面不会把首次请求失败伪装成空数据', async ({ page }) => {
  await login(page)

  for (const target of [
    { path: '/dashboard', endpoint: '**/api/dashboard', title: '雷达总览加载失败' },
    { path: '/calendar', endpoint: '**/api/subscriptions?billing_type=recurring&active=true', title: '续费日历加载失败' },
    { path: '/subscriptions', endpoint: '**/api/subscriptions', title: '订阅账本加载失败' },
    { path: '/reports', endpoint: '**/api/reports/insights', title: '支出报表加载失败' }
  ]) {
    await page.route(target.endpoint, (route) => route.fulfill({ status: 503, body: 'temporary' }))
    await page.goto(target.path)
    const state = page.locator('[data-state="error"][data-trust="unknown"]')
    await expect(state).toContainText(target.title)
    await expect(state.getByRole('button', { name: '重试', exact: true })).toBeVisible()
    await page.unroute(target.endpoint)
  }
})

test('订阅快速筛选时旧响应不会覆盖新筛选', async ({ page }) => {
  await login(page)
  await page.goto('/subscriptions')
  await expect(page.locator('[data-state="loading"]')).toHaveCount(0)

  let delayed = false
  await page.route('**/api/subscriptions?billing_type=recurring', async (route) => {
    delayed = true
    await new Promise((resolve) => setTimeout(resolve, 500))
    await route.fulfill({
      json: [{ id: 987001, name: '旧周期响应', billing_type: 'recurring', amount: 1, currency: 'CNY' }]
    })
  })
  await page.route('**/api/subscriptions?billing_type=one_time', (route) => route.fulfill({
    json: [{ id: 987002, name: '最新买断响应', billing_type: 'one_time', amount: 1, currency: 'CNY' }]
  }))

  await page.getByRole('button', { name: '周期', exact: true }).click()
  await expect.poll(() => delayed).toBe(true)
  await page.getByRole('button', { name: '买断', exact: true }).click()
  await expect(page.getByText('最新买断响应', { exact: true })).toBeVisible()
  await page.waitForTimeout(600)
  await expect(page.getByText('旧周期响应', { exact: true })).toHaveCount(0)
})

test('雷达总览添加订阅直接打开现有表单', async ({ page }) => {
  await login(page)
  await page.getByRole('button', { name: '+ 添加订阅', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('添加订阅')
})
