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

async function confirmAction(page, actionName) {
  await page.getByRole('button', { name: actionName, exact: true }).click()
  const dialog = page.getByRole('dialog', { name: actionName })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: '确认', exact: true }).click()
}

test('私有 iCal 链接可生成、重置并撤销，明文不写浏览器存储', async ({ page, request }) => {
  await login(page)
  await page.goto('/settings')
  const card = page.getByRole('region', { name: '私有日历订阅' })
  await expect(card).toBeVisible()

  if (await card.getByRole('button', { name: '撤销订阅', exact: true }).isVisible()) {
    await confirmAction(page, '撤销订阅')
    await expect(card.getByRole('button', { name: '生成私有链接', exact: true })).toBeVisible()
  }

  const generateResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith('/api/calendar-feed/generate') && response.request().method() === 'POST'
  )
  await card.getByRole('button', { name: '生成私有链接', exact: true }).click()
  expect((await generateResponsePromise).ok()).toBeTruthy()
  const urlInput = card.getByLabel('本次生成的日历链接')
  await expect(urlInput).toBeVisible()
  const oldUrl = await urlInput.inputValue()
  expect(oldUrl).toContain('/api/calendar-feed.ics?token=')
  expect((await request.get(oldUrl)).status()).toBe(200)

  await confirmAction(page, '重置链接')
  await expect.poll(() => urlInput.inputValue()).not.toBe(oldUrl)
  const newUrl = await urlInput.inputValue()
  expect((await request.get(oldUrl)).status()).toBe(404)
  expect((await request.get(newUrl)).status()).toBe(200)
  expect(await page.evaluate(() => {
    const containsFeed = (storage) => Object.keys(storage).some((key) => (
      /calendar|feed/i.test(key)
      || /calendar-feed\.ics/.test(storage.getItem(key) || '')
    ))
    return {
      local: containsFeed(localStorage),
      session: containsFeed(sessionStorage)
    }
  })).toEqual({ local: false, session: false })

  await confirmAction(page, '撤销订阅')
  await expect(urlInput).toHaveCount(0)
  expect((await request.get(newUrl)).status()).toBe(404)
  await expect(card).toContainText('私有日历订阅已撤销')
})

test('生产 PWA 只缓存离线页与品牌图标', async ({ page, request }) => {
  await page.goto('/login')
  const cacheState = await page.evaluate(async () => {
    await navigator.serviceWorker.ready
    const keys = await globalThis.caches.keys()
    const paths = []
    for (const key of keys) {
      const requests = await (await globalThis.caches.open(key)).keys()
      paths.push(...requests.map((item) => new URL(item.url).pathname))
    }
    return { keys, paths: paths.sort() }
  })

  expect(cacheState.keys).toEqual(['subly-static-v2'])
  expect(cacheState.paths).toEqual([
    '/offline.html',
    '/pwa-192.png',
    '/pwa-512-maskable.png',
    '/pwa-512.png'
  ])
  expect(cacheState.paths.some((path) => path.startsWith('/api/'))).toBe(false)
  expect(cacheState.paths.some((path) => ['/login', '/', '/settings'].includes(path))).toBe(false)

  await page.route('**/pwa-192.png', (route) => route.abort())
  const offlineIconWidth = await page.evaluate(async () => {
    const image = new globalThis.Image()
    image.src = '/pwa-192.png'
    globalThis.document.body.appendChild(image)
    try {
      await image.decode()
      return image.naturalWidth
    } finally {
      image.remove()
    }
  })
  expect(offlineIconWidth).toBe(192)
  await page.unroute('**/pwa-192.png')

  const manifest = await request.get('/manifest.webmanifest')
  expect(manifest.ok()).toBeTruthy()
  expect(manifest.headers()['content-type']).toContain('application/manifest+json')
  expect(manifest.headers()['cache-control']).toBe('no-cache')

  const serviceWorker = await request.get('/sw.js')
  expect(serviceWorker.ok()).toBeTruthy()
  expect(serviceWorker.headers()['cache-control']).toContain('no-store')
})
