// Takes the README screenshots against a running stack (default: the compose UI on :28080).
// It uploads the fictional documents in docs/samples/ if they are missing, so the shots
// never show anyone's own files. One-time setup: `npx playwright install chromium`.
import { readdir, readFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { chromium } from 'playwright'

const BASE = process.argv[2] ?? 'http://localhost:28080'
const ROOT = resolve(import.meta.dirname, '..', '..')
const SAMPLES = join(ROOT, 'docs', 'samples')
const OUT = join(ROOT, 'docs', 'screenshots')
const QUESTION = 'How do I descale the kettle?'
const READY_TIMEOUT_MS = 60_000

async function api(path, init) {
  const response = await fetch(`${BASE}/api${path}`, init)
  if (!response.ok) throw new Error(`${init?.method ?? 'GET'} /api${path}: HTTP ${response.status}`)
  return response.json()
}

async function uploadMissingSamples() {
  const titles = new Set((await api('/documents')).map((d) => d.title))
  for (const name of (await readdir(SAMPLES)).filter((n) => n.endsWith('.md'))) {
    if (titles.has(name)) continue
    const form = new FormData()
    const bytes = await readFile(join(SAMPLES, name))
    form.append('file', new Blob([bytes], { type: 'text/markdown' }), name)
    await api('/documents', { method: 'POST', body: form })
    console.log(`uploaded ${name}`)
  }
}

async function waitUntilReady() {
  const deadline = Date.now() + READY_TIMEOUT_MS
  for (;;) {
    const docs = await api('/documents')
    if (docs.every((d) => d.status === 'ready' || d.status === 'failed')) return
    if (Date.now() > deadline) {
      console.error(`documents not ready after ${READY_TIMEOUT_MS / 1000} s`)
      process.exit(1)
    }
    await new Promise((r) => setTimeout(r, 1000))
  }
}

await uploadMissingSamples()
await waitUntilReady()

const browser = await chromium.launch()
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
  await page.goto(BASE)
  await page.getByRole('cell', { name: 'lumen-kettle.md' }).waitFor()
  await page.screenshot({ path: join(OUT, 'documents.png') })

  await page.getByRole('button', { name: 'Ask', exact: true }).first().click()
  await page.getByLabel('Question').fill(QUESTION)
  await page.locator('form.ask-form button[type=submit]').click()
  await page.locator('.label-verifying').waitFor()
  await page.locator('.label-verifying').waitFor({ state: 'detached', timeout: 300_000 })
  await page.locator('article.answer details summary').first().click()
  await page.screenshot({ path: join(OUT, 'ask.png') })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('navigation', { name: 'History' }).getByRole('button').first().click()
  await page.screenshot({ path: join(OUT, 'history.png') })
} finally {
  await browser.close()
}
console.log(`saved documents.png, ask.png and history.png in ${OUT}`)
