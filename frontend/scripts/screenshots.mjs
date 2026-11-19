// Takes the README screenshots against a running stack (default: the compose UI on :28080).
// It needs a stack holding nothing but the fictional documents in docs/samples/ (it uploads
// them if missing) and an empty history; otherwise it stops before taking any shot, so
// nobody's own files reach the repository. One-time setup: `npx playwright install chromium`.
import { readdir, readFile, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { chromium } from 'playwright'
import { foreignContent } from './stack-check.mjs'

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

async function sampleNames() {
  return (await readdir(SAMPLES)).filter((n) => n.endsWith('.md'))
}

async function refuseForeignContent() {
  const found = foreignContent(await api('/documents'), await api('/questions'), await sampleNames())
  if (found.length > 0) {
    console.error(`The stack holds more than the samples, and it would show in the screenshots:`)
    for (const line of found) console.error(`  - ${line}`)
    console.error('Delete those documents on the Documents tab and clear the history with')
    console.error('  docker compose exec postgres psql -U fontes -c "TRUNCATE questions"')
    console.error('then run this again.')
    process.exit(1)
  }
}

async function uploadMissingSamples() {
  const titles = new Set((await api('/documents')).map((d) => d.title))
  for (const name of await sampleNames()) {
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

await refuseForeignContent()
await uploadMissingSamples()
await waitUntilReady()

// Shots stay in memory until all three are taken, so a failed run leaves the committed set
// untouched rather than half replaced.
async function takeShots(page) {
  const shots = {}
  await page.goto(BASE)
  await page.getByRole('cell', { name: 'lumen-kettle.md' }).waitFor()
  shots['documents.png'] = await page.screenshot()

  await page.getByRole('button', { name: 'Ask', exact: true }).first().click()
  await page.getByLabel('Question').fill(QUESTION)
  await page.locator('form.ask-form button[type=submit]').click()
  await page.locator('.label-verifying').waitFor()
  await page.locator('.label-verifying').waitFor({ state: 'detached', timeout: 300_000 })
  const failed = page.locator('section.ask [role=alert]')
  if (await failed.count()) {
    throw new Error(`the question failed, so there is no answer to show: ${await failed.first().innerText()}`)
  }
  await page.locator('article.answer details summary').first().click()
  shots['ask.png'] = await page.screenshot()

  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('navigation', { name: 'History' }).getByRole('button').first().click()
  shots['history.png'] = await page.screenshot()
  return shots
}

const browser = await chromium.launch()
try {
  const shots = await takeShots(await browser.newPage({ viewport: { width: 1280, height: 800 } }))
  for (const [name, png] of Object.entries(shots)) await writeFile(join(OUT, name), png)
  console.log(`saved ${Object.keys(shots).join(', ')} in ${OUT}`)
} catch (error) {
  console.error(`No screenshots saved: ${error.message}`)
  process.exitCode = 1
} finally {
  await browser.close()
}
