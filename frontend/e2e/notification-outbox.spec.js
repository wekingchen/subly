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

const baseItems = [
  { id: 1, status: 'pending', subscription_name: '待发送订阅', channel: 'telegram' },
  { id: 2, status: 'sending', subscription_name: '投递中订阅', channel: 'bark', attempt_count: 1 },
  { id: 3, status: 'retry_wait', subscription_name: '等待重试订阅', channel: 'webhook', attempt_count: 2, next_attempt_at: '2024-01-01T01:05:00Z', last_error: 'ConnectError' },
  { id: 4, status: 'sent', subscription_name: '已发送订阅', channel: 'telegram', attempt_count: 1, sent_at: '2024-01-01T01:00:00Z' },
  { id: 5, status: 'dead', subscription_name: '停止重试订阅', channel: 'bark', attempt_count: 6, last_error: 'HTTP 400' },
  { id: 6, status: 'canceled', subscription_name: '已取消订阅', channel: 'webhook', attempt_count: 0, last_error: '发送条件已变化' }
].map((item) => ({
  key: `subscription:${item.id}`,
  kind: 'subscription',
  source_id: item.id,
  source_name: item.subscription_name,
  business_date: '2024-01-01',
  event_date: '2024-01-08',
  event_label: '续费日',
  days_before: 7,
  attempt_count: 0,
  next_attempt_at: null,
  last_error: null,
  created_at: '2024-01-01T01:00:00Z',
  updated_at: '2024-01-01T01:00:00Z',
  sent_at: null,
  canceled_at: null,
  ...item
}))
delete baseItems.forEach ? null : null

function summary(items) {
  const result = { total: items.length, pending: 0, sending: 0, retry_wait: 0, sent: 0, dead: 0, canceled: 0 }
  for (const item of items) result[item.status] += 1
  return result
}

test('通知投递中心展示六种状态、尝试历史与受控重发', async ({ page }) => {
  await login(page)
  let items = structuredClone(baseItems)
  let retryCalls = 0
  const requestedStatuses = []

  await page.route(/\/api\/notifications\/deliveries(?:\?.*)?$/, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    const status = new URL(route.request().url()).searchParams.get('status')
    if (status) requestedStatuses.push(status)
    const pageItems = status ? items.filter((item) => item.status === status) : items
    await route.fulfill({
      json: { summary: summary(items), items: pageItems, has_more: false, next_cursor: null }
    })
  })
  await page.route('**/api/notifications/deliveries/subscription/3/attempts', async (route) => {
    await route.fulfill({ json: [
      { id: 31, attempt_no: 1, retry_cycle: 0, status: 'failed', message: 'ConnectError', sent_at: '2024-01-01T01:00:00Z' },
      { id: 32, attempt_no: 2, retry_cycle: 0, status: 'failed', message: 'HTTP 503', sent_at: '2024-01-01T01:01:00Z' },
      { id: 33, attempt_no: 1, retry_cycle: 1, status: 'sent', message: '已送达', sent_at: '2024-01-01T01:02:00Z' }
    ] })
  })
  await page.route('**/api/notifications/deliveries/subscription/3/retry', async (route) => {
    retryCalls += 1
    await new Promise((resolve) => setTimeout(resolve, 120))
    items = items.map((item) => item.id === 3
      ? { ...item, status: 'pending', attempt_count: 0, next_attempt_at: null, last_error: null }
      : item)
    await route.fulfill({ json: { ok: true, status: 'pending' } })
  })
  await page.route('**/api/notifications/deliveries/subscription/3', async (route) => {
    await route.fulfill({ json: items.find((item) => item.id === 3) })
  })

  await page.goto('/notifications')
  await expect(page.getByRole('heading', { name: '通知投递中心' })).toBeVisible()
  for (const label of ['待发送', '投递中', '等待重试', '已发送', '已停止重试', '已取消']) {
    await expect(page.getByText(label, { exact: true }).first()).toBeVisible()
  }
  await page.getByRole('button', { name: '已停止重试 1', exact: true }).click()
  await expect(page.getByRole('article').filter({ hasText: '停止重试订阅' })).toBeVisible()
  expect(requestedStatuses).toContain('dead')
  await page.getByRole('button', { name: '全部 6', exact: true }).click()

  const retryCard = page.getByRole('article').filter({ hasText: '等待重试订阅' })
  const historyButton = retryCard.getByRole('button', { name: /尝试记录/ })
  await expect(historyButton).toHaveAttribute('aria-expanded', 'false')
  await historyButton.click()
  await expect(historyButton).toHaveAttribute('aria-expanded', 'true')
  await expect(retryCard.getByText('第 2 次')).toBeVisible()
  await expect(retryCard.getByText('第 2 轮 · 第 1 次')).toBeVisible()
  await expect(retryCard.getByText('HTTP 503')).toBeVisible()

  const retryButton = retryCard.getByRole('button', { name: '重新发送', exact: true })
  await retryButton.evaluate((button) => {
    button.click()
    button.click()
  })
  await expect(retryCard.getByText('待发送', { exact: true })).toBeVisible()
  expect(retryCalls).toBe(1)

  await expect(page.getByRole('article').filter({ hasText: '待发送订阅' }).getByRole('button', { name: '重新发送' })).toHaveCount(0)
  await expect(page.getByRole('article').filter({ hasText: '已发送订阅' }).getByRole('button', { name: '重新发送' })).toHaveCount(0)
  await expect(page.getByRole('article').filter({ hasText: '停止重试订阅' }).getByRole('button', { name: '重新发送' })).toBeVisible()
})

test('快速切换筛选时旧响应不会覆盖当前结果', async ({ page }) => {
  await login(page)
  const items = structuredClone(baseItems)

  await page.route(/\/api\/notifications\/deliveries(?:\?.*)?$/, async (route) => {
    const status = new URL(route.request().url()).searchParams.get('status')
    if (status === 'dead') await new Promise((resolve) => setTimeout(resolve, 200))
    if (status === 'sent') await new Promise((resolve) => setTimeout(resolve, 10))
    const pageItems = status ? items.filter((item) => item.status === status) : items
    await route.fulfill({
      json: { summary: summary(items), items: pageItems, has_more: false, next_cursor: null }
    })
  })

  await page.goto('/notifications')
  await page.getByRole('button', { name: '已停止重试 1', exact: true }).click()
  await page.getByRole('button', { name: '已发送 1', exact: true }).click()
  await expect(page.getByRole('article').filter({ hasText: '已发送订阅' })).toBeVisible()
  await expect(page.getByRole('article').filter({ hasText: '停止重试订阅' })).toHaveCount(0)
})

test('重发 409 后刷新行状态，390px 页面不横向溢出', async ({ page }) => {
  await login(page)
  let item = { ...baseItems[4] }

  await page.route(/\/api\/notifications\/deliveries(?:\?.*)?$/, async (route) => {
    await route.fulfill({ json: { summary: summary([item]), items: [item] } })
  })
  await page.route('**/api/notifications/deliveries/subscription/5/retry', async (route) => {
    item = { ...item, status: 'sent', sent_at: '2024-01-01T01:03:00Z' }
    await route.fulfill({ status: 409, json: { detail: '当前状态不可重新发送' } })
  })
  await page.route('**/api/notifications/deliveries/subscription/5', async (route) => {
    await route.fulfill({ json: item })
  })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/notifications')
  const card = page.getByRole('article').filter({ hasText: '停止重试订阅' })
  await card.getByRole('button', { name: '重新发送', exact: true }).click()
  await expect(card.getByText('已发送', { exact: true })).toBeVisible()
  await expect(card.getByRole('button', { name: '重新发送' })).toHaveCount(0)
  await expect(page.getByText('当前状态不可重新发送')).toBeVisible()

  const layout = await page.evaluate(() => ({
    viewport: globalThis.innerWidth,
    pageWidth: globalThis.document.documentElement.scrollWidth,
    actionHeights: [...globalThis.document.querySelectorAll('.delivery-actions button')]
      .map((button) => Math.round(button.getBoundingClientRect().height))
  }))
  expect(layout.pageWidth).toBe(layout.viewport)
  expect(layout.actionHeights.every((height) => height >= 44)).toBe(true)
})
