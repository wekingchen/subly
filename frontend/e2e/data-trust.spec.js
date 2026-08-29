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
    { path: '/calendar', endpoint: '**/api/subscriptions?billing_type=recurring&active=true', title: '续费与还款日历加载失败' },
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

test('订阅搜索、类型和风险筛选只使用完整本地快照', async ({ page }) => {
  await login(page)
  let requests = 0
  await page.route('**/api/subscriptions', (route) => {
    requests += 1
    return route.fulfill({ json: [
      { id: 987001, name: '过期云主机', plan: 'Pro', billing_type: 'recurring', amount: 10, currency: 'CNY', next_renewal_date: '2020-01-01', is_active: true, is_paused: false },
      { id: 987002, name: '安全流媒体', plan: '家庭版', billing_type: 'recurring', amount: 20, currency: 'CNY', next_renewal_date: '2099-01-01', is_active: true, is_paused: false },
      { id: 987003, name: '永久授权', billing_type: 'one_time', amount: 30, currency: 'CNY', start_date: '2026-01-01', is_active: true }
    ] })
  })
  await page.goto('/subscriptions')
  await expect(page.getByText('安全流媒体', { exact: true })).toBeVisible()
  await expect.poll(() => requests).toBe(1)

  await page.getByPlaceholder('搜索名称、套餐或备注').fill('家庭版')
  await expect(page.getByText('安全流媒体', { exact: true })).toBeVisible()
  await expect(page.getByText('过期云主机', { exact: true })).toHaveCount(0)

  await page.getByPlaceholder('搜索名称、套餐或备注').fill('')
  await page.getByRole('button', { name: '周期', exact: true }).click()
  await page.getByLabel('续费风险').selectOption('overdue')
  await expect(page.getByText('过期云主机', { exact: true })).toBeVisible()
  await expect(page.getByText('安全流媒体', { exact: true })).toHaveCount(0)
  await expect(page.locator('.grip')).toHaveCount(0)
  expect(requests).toBe(1)

  await page.getByRole('button', { name: '清除筛选' }).click()
  await expect(page.getByText('永久授权', { exact: true })).toBeVisible()
  expect(requests).toBe(1)
})

test('雷达总览添加订阅直接打开现有表单', async ({ page }) => {
  await login(page)
  await page.getByRole('button', { name: '+ 添加订阅', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('添加订阅')
})
