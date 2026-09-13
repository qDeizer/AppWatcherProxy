import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'
import { chromium } from 'playwright-core'

const output = resolve(import.meta.dirname, '../../.runtime/qa')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true, channel: 'chrome' })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
const failures = []
const created = []
page.on('pageerror', error => failures.push(error.message))
page.on('response', async response => {
  if (response.url().endsWith('/api/recordings/start') && response.ok()) {
    created.push((await response.json()).id)
  }
})
try {
  const stats = await (await page.request.get('http://127.0.0.1:43110/api/stats')).json()
  assert.equal(stats.session_count, 0, 'Run only on an empty QA instance: import replaces RAM')
  assert.equal(stats.capture_state, 'stopped')
  assert.equal(stats.recording, false)
  await page.goto('http://127.0.0.1:43110')
  await page.getByRole('button', { name: 'Kayıt', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.waitFor()
  assert(await dialog.getByRole('button', { name: 'Kaydı başlat', exact: true }).isDisabled())
  await dialog.getByLabel('Parola (en az 8 karakter)').fill('qa-only-test-password')
  await dialog.getByRole('button', { name: 'Kaydı başlat', exact: true }).click()
  await dialog.getByRole('button', { name: '● Kaydı durdur', exact: true }).waitFor()
  await page.screenshot({ path: resolve(output, 'recording-active.png') })
  await dialog.getByRole('button', { name: '● Kaydı durdur', exact: true }).click()
  await dialog.getByText('Kayıt durduruldu.', { exact: true }).waitFor()
  const downloadEvent = page.waitForEvent('download')
  await dialog.getByRole('link', { name: 'Şifreli indir' }).first().click()
  const download = await downloadEvent
  assert(download.suggestedFilename().endsWith('.awp'))
  await dialog.getByLabel('Parola (en az 8 karakter)').fill('wrong-password')
  page.on('dialog', prompt => prompt.accept())
  await dialog.getByRole('button', { name: 'Aç', exact: true }).first().click()
  await dialog.getByRole('alert').filter({ hasText: 'Kayıt açılamadı' }).waitFor()
  await dialog.getByLabel('Parola (en az 8 karakter)').fill('qa-only-test-password')
  await dialog.getByRole('button', { name: 'Aç', exact: true }).first().click()
  await dialog.getByText('Kayıt RAM’e açıldı; ana tabloda inceleyebilirsiniz.', { exact: true }).waitFor()
  await page.screenshot({ path: resolve(output, 'recording-loaded.png') })
  await dialog.getByRole('button', { name: 'Kapat', exact: true }).click()
  assert.equal(await page.getByRole('dialog').count(), 0)
  assert.deepEqual(failures, [])
  console.log(JSON.stringify({ passed: true, created, screenshots: output }))
} finally {
  await browser.close()
}
