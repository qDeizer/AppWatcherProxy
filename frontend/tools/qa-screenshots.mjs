import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'
import { chromium } from 'playwright-core'

const projectRoot = resolve(import.meta.dirname, '..', '..')
const outputDirectory = resolve(projectRoot, 'docs', 'qa')
await mkdir(outputDirectory, { recursive: true })

const browser = await chromium.launch({
  headless: true,
  executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
})

try {
  for (const target of [
    { name: 'desktop', width: 1536, height: 1024 },
    { name: 'mobile', width: 390, height: 844 },
  ]) {
    const page = await browser.newPage({ viewport: target })
    await page.goto('http://127.0.0.1:43110', { waitUntil: 'networkidle' })
    await page.screenshot({ path: resolve(outputDirectory, `${target.name}.png`) })
    await page.close()
  }
} finally {
  await browser.close()
}

