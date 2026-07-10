import { expect, test } from '@playwright/test'

const username = process.env.E2E_ADMIN_USERNAME || 'e2e-admin'
const password = process.env.E2E_ADMIN_PASSWORD || 'e2e-admin-password-123'

function expectSpaCsp(response) {
  const csp = response?.headers()['content-security-policy']
  expect(csp).toContain("default-src 'self'")
  expect(csp).toContain("script-src 'self'")
  expect(csp).toContain("frame-ancestors 'none'")
}

test('登录、Cookie 恢复、旧令牌迁移与退出形成闭环', async ({ page, context, playwright }) => {
  const cspErrors = []
  page.on('console', (message) => {
    const text = message.text()
    if (text.includes('Content Security Policy') || text.includes('violates the following Content Security Policy')) {
      cspErrors.push(text)
    }
  })

  const loginPage = await page.goto('/login')
  expectSpaCsp(loginPage)
  const inputs = page.locator('.auth-card input')
  await inputs.nth(0).fill(username)
  await inputs.nth(1).fill(password)
  const loginResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith('/api/auth/login') && response.request().method() === 'POST'
  )
  await page.locator('.auth-card .btn').click()
  const loginResponse = await loginResponsePromise
  expect(loginResponse.ok()).toBeTruthy()

  await expect(page).toHaveURL(/\/dashboard$/)
  const legacyClient = await playwright.request.newContext({ baseURL: new URL(page.url()).origin })
  const legacyLogin = await legacyClient.post('/api/auth/login', {
    form: { username, password }
  })
  expect(legacyLogin.ok()).toBeTruthy()
  const legacyRefreshToken = (await legacyLogin.json()).refresh_token
  await legacyClient.dispose()
  expect(await page.evaluate(() => ({
    access: localStorage.getItem('access_token'),
    refresh: localStorage.getItem('refresh_token')
  }))).toEqual({ access: null, refresh: null })

  let cookies = await context.cookies()
  const refreshCookie = cookies.find((cookie) => cookie.name === 'subly_refresh')
  expect(refreshCookie?.httpOnly).toBe(true)
  expect(refreshCookie?.sameSite).toBe('Lax')
  expect(refreshCookie?.path).toBe('/api/auth')

  const transientPage = await context.newPage()
  await transientPage.route('**/api/auth/refresh', (route) => route.fulfill({ status: 503, body: 'temporary' }))
  const transientDashboard = await transientPage.goto('/dashboard')
  expectSpaCsp(transientDashboard)
  await expect(transientPage).toHaveURL(/\/dashboard$/)
  await transientPage.close()

  const reloadedDashboard = await page.reload()
  expectSpaCsp(reloadedDashboard)
  await expect(page).toHaveURL(/\/dashboard$/)
  await expect(page.locator('.user .uname')).toHaveText(username)

  for (const path of ['/subscriptions', '/settings', '/admin-diagnostics']) {
    const response = await page.goto(path)
    expectSpaCsp(response)
    await expect(page).not.toHaveURL(/\/login$/)
  }

  await page.route('**/api/auth/logout', (route) => route.abort())
  const dialogPromise = page.waitForEvent('dialog')
  await page.locator('.user a').click()
  const dialog = await dialogPromise
  expect(dialog.message()).toContain('退出失败')
  await dialog.accept()
  await expect(page).not.toHaveURL(/\/login$/)
  expect((await context.cookies()).some((cookie) => cookie.name === 'subly_refresh')).toBe(true)
  await page.unroute('**/api/auth/logout')

  await page.locator('.user a').click()
  await expect(page).toHaveURL(/\/login$/)
  cookies = await context.cookies()
  expect(cookies.some((cookie) => cookie.name === 'subly_refresh')).toBe(false)

  await page.evaluate((token) => {
    localStorage.setItem('access_token', 'legacy-access-token')
    localStorage.setItem('refresh_token', token)
  }, legacyRefreshToken)
  const migratedDashboard = await page.reload()
  expectSpaCsp(migratedDashboard)
  await expect(page).toHaveURL(/\/dashboard$/)
  expect(await page.evaluate(() => ({
    access: localStorage.getItem('access_token'),
    refresh: localStorage.getItem('refresh_token')
  }))).toEqual({ access: null, refresh: null })
  cookies = await context.cookies()
  expect(cookies.some((cookie) => cookie.name === 'subly_refresh' && cookie.httpOnly)).toBe(true)

  await page.locator('.user a').click()
  await expect(page).toHaveURL(/\/login$/)
  await page.goto('/dashboard')
  await expect(page).toHaveURL(/\/login$/)
  expect(cspErrors).toEqual([])
})

test('任意外部 Origin 不获得 CORS 许可', async ({ request }) => {
  const response = await request.get('/api/health', {
    headers: { Origin: 'https://evil.example' }
  })
  expect(response.ok()).toBeTruthy()
  expect(response.headers()['access-control-allow-origin']).toBeUndefined()
  expect(response.headers()['access-control-allow-credentials']).toBeUndefined()
})
