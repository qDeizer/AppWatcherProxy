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
  page.on('dialog', prompt => prompt.accept())
  await dialog.getByLabel('Parola (en az 8 karakter)').fill('qa-only-test-password')
  await dialog.getByRole('button', { name: 'Şifresini çöz · .mitm indir' }).first().click()
  await dialog.getByRole('alert').filter({ hasText: 'Replay için tam HTTP/WebSocket oturumu yok' }).waitFor()
  await page.screenshot({ path: resolve(output, 'mitm-empty-state.png') })
  await dialog.getByLabel('Parola (en az 8 karakter)').fill('wrong-password')
  await dialog.getByRole('button', { name: 'Aç', exact: true }).first().click()
  await dialog.getByRole('alert').filter({ hasText: 'Kayıt açılamadı' }).waitFor()
  await dialog.getByLabel('Parola (en az 8 karakter)').fill('qa-only-test-password')
  await dialog.getByRole('button', { name: 'Aç', exact: true }).first().click()
  await dialog.getByText('Kayıt RAM’e açıldı; ana tabloda inceleyebilirsiniz.', { exact: true }).waitFor()
  await page.screenshot({ path: resolve(output, 'recording-loaded.png') })
  await dialog.getByRole('button', { name: 'Kapat', exact: true }).click()
  assert.equal(await page.getByRole('dialog').count(), 0)
  const now = new Date().toISOString()
  const sse = Buffer.from('event: update\ndata: {"msg":"selam"}\nid: 42\n\n').toString('base64')
  const summary = {id: 'qa-sse', time: now, application: 'qa-sse.exe', pid: 1, direction: 'up', protocol: 'HTTP', host: 'example.test', method_event: 'GET', path: '/events', status: 200, content_type: 'text/event-stream', sent: 0, received: 42, duration_ms: null, inspection: 'Full', inspection_reason: null, is_streaming: true, has_error: false, is_binary: false}
  const detail = {id: 'qa-sse', connection_id: 'qa', type: 'http', opened_at: now, closed_at: null, duration_ms: null, http_version: 'HTTP/1.1', http2_stream_id: null, error: null, application: {name: 'qa-sse.exe', executable_path: null, icon: null}, process: {pid: 1, name: 'qa-sse.exe', executable_path: null, start_time: null}, connection: {id: 'qa', opened_at: now, closed_at: null, protocol: 'tcp', client_sockname: null, server_peername: null, server_hostname: 'example.test', dns_query: null, dns_answers: [], dns_duration_ms: null, inspection_status: 'Full', inspection_reason: null, tls: {version: null, cipher: null, alpn: null, sni: null, established: false, handshake_error: null}}, request: null, response: null, stream: {kind: 'sse', reconstructed: sse, frames: [{seq: 0, timestamp: now, direction: 'down', size_bytes: 42, type: 'sse', raw: sse, parsed: {event: 'update', data: {msg: 'selam'}, id: '42'}}]}, is_streaming: true, is_truncated: false, has_error: false, is_binary: false}
  await page.route('**/api/sessions?*', route => route.fulfill({json: {items: [summary], total: 1}}))
  await page.route('**/api/sessions/qa-sse', route => route.fulfill({json: detail}))
  await page.getByRole('main').getByRole('button').filter({ hasText: 'qa-sse.exe' }).first().click()
  await page.getByRole('tab', { name: 'Stream' }).click()
  await page.getByText(/"msg": "selam"/).first().waitFor()
  await page.screenshot({ path: resolve(output, 'sse-stream.png') })
  assert.deepEqual(failures, [])
  console.log(JSON.stringify({ passed: true, created, screenshots: output }))
} finally {
  await browser.close()
}
