#!/usr/bin/env node
/**
 * Headless harness for the hubris desktop half.
 *
 * Loads the REAL desktop/plugin.js against a stub SDK and a fake gateway, then drives the copy
 * routine end to end. What this proves: the off switch is excluded, every RPC carries an explicit
 * profile, the target is read back, and a backend that quietly drops a value gets reported.
 *
 * Usage: node tests/desktop/run.mjs
 */
import assert from 'node:assert/strict'
import { existsSync, lstatSync, mkdirSync, readFileSync, symlinkSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const agentHome = process.env.HERMES_AGENT_HOME || '/root/.hermes/hermes-agent'

for (const pkg of ['react', 'react-dom']) {
  const link = join(here, 'node_modules', pkg)

  // lstat, not exists: a dangling symlink from an earlier layout still occupies the name.
  let linkPresent = false

  try {
    linkPresent = Boolean(lstatSync(link))
  } catch {
    linkPresent = false
  }

  if (linkPresent) {
    continue
  }

  // The app's packages live under apps/desktop in a checkout, and at the root in a packaged
  // tree. Probe both rather than pinning one layout.
  const candidates = [
    join(agentHome, 'apps', 'desktop', 'node_modules', pkg),
    join(agentHome, 'node_modules', pkg)
  ]
  const found = candidates.find(dir => existsSync(join(dir, 'package.json')))

  if (!found) {
    throw new Error(`cannot find ${pkg} under ${candidates.join(' or ')}`)
  }

  mkdirSync(dirname(link), { recursive: true })
  symlinkSync(found, link, 'dir')
}

const source = readFileSync(join(here, '..', '..', 'desktop', 'plugin.js'), 'utf8')
const target = join(here, 'plugin-under-test.mjs')
writeFileSync(target, source)

// The SDK stub ships with the tests, because the real package is a build artefact of the app and
// a fresh clone has none. It records what the pane asks the host for; the assertions read that.
const sdkLink = join(here, 'node_modules', '@hermes', 'plugin-sdk')
let sdkLinkPresent = false
try {
  sdkLinkPresent = Boolean(lstatSync(sdkLink))
} catch {
  sdkLinkPresent = false
}
if (!sdkLinkPresent) {
  mkdirSync(dirname(sdkLink), { recursive: true })
  symlinkSync(join(here, 'stub', '@hermes', 'plugin-sdk'), sdkLink, 'dir')
}

const mod = await import(new URL('./plugin-under-test.mjs', import.meta.url))
const sdk = await import('@hermes/plugin-sdk')
const seam = mod.__hubrisDesktopTestSeam

const results = []

async function check(name, fn) {
  try {
    await fn()
    results.push(['ok  ', name])
  } catch (error) {
    results.push(['FAIL', `${name} :: ${error.message}`])
  }
}

// ─────────────────────────────────────────────────────────────────────── pure seams

const savedRow = {
  key: 'hubris',
  name: 'hubris',
  settings_schema: [
    { key: 'enabled', type: 'boolean', value: true },
    { key: 'topic_games', type: 'boolean', value: false },
    { key: 'disabled_subjects', type: 'string', value: 'money.prices' },
    { key: 'nag_on_explicit', type: 'boolean', value: undefined }
  ],
  status: 'enabled'
}

await check('valuesToCopy keeps saved values and drops the off switch', () => {
  const values = seam.valuesToCopy(savedRow)
  assert.deepEqual(Object.keys(values).sort(), ['disabled_subjects', 'topic_games'])
  assert.equal(values.topic_games, false)
  assert.equal('enabled' in values, false)
})

await check('valuesToCopy on a missing row is empty', () => {
  assert.deepEqual(seam.valuesToCopy(null), {})
})

await check('copyCount counts what would travel', () => {
  assert.equal(seam.copyCount(savedRow), 2)
})

await check('isEnabled reads the backend status words', () => {
  assert.equal(seam.isEnabled({ status: 'enabled' }), true)
  assert.equal(seam.isEnabled({ status: 'not enabled' }), false)
  assert.equal(seam.isEnabled({ enabled: true }), true)
  assert.equal(seam.isEnabled({}), false)
})

await check('findRow matches key or name and tolerates junk', () => {
  assert.equal(seam.findRow([{ key: 'x' }, { name: 'hubris' }]).name, 'hubris')
  assert.equal(seam.findRow(null), null)
  assert.equal(seam.findRow([{ key: 'other' }]), null)
})

await check('mismatches names the keys that did not take', () => {
  const after = {
    settings_schema: [
      { key: 'topic_games', value: true },
      { key: 'disabled_subjects', value: 'money.prices' }
    ]
  }

  assert.deepEqual(seam.mismatches({ disabled_subjects: 'money.prices', topic_games: false }, after), [
    'topic_games'
  ])
})

// ─────────────────────────────────────────────────────────── copy against a fake gateway

function fakeGateway({ dropKey = null } = {}) {
  const profiles = {
    coder: { enabled: false, settings: {} },
    ops: { enabled: false, settings: {} }
  }
  const calls = []

  const row = name => {
    const p = profiles[name]

    return {
      key: 'hubris',
      name: 'hubris',
      settings_schema: [
        { key: 'enabled', type: 'boolean', value: true },
        { key: 'disabled_subjects', type: 'string', value: p.settings.disabled_subjects },
        { key: 'topic_games', type: 'boolean', value: p.settings.topic_games }
      ],
      status: p.enabled ? 'enabled' : 'not enabled'
    }
  }

  const request = async (method, params) => {
    calls.push([method, params])

    if (method !== 'plugins.manage') {
      throw new Error(`unexpected method ${method}`)
    }

    const name = params.profile
    const p = profiles[name]

    if (!p) {
      throw new Error(`unknown profile ${name}`)
    }

    if (params.action === 'settings') {
      for (const [key, value] of Object.entries(params.values ?? {})) {
        if (key === dropKey) {
          continue // a backend that accepts the write and does nothing
        }

        p.settings[key] = value
      }

      return { ok: true }
    }

    if (params.action === 'toggle') {
      p.enabled = true

      return { ok: true, plugin: row(name) }
    }

    if (params.action === 'list') {
      return { plugins: [row(name)] }
    }

    throw new Error(`unexpected action ${params.action}`)
  }

  return { calls, profiles, request }
}

await check('copy writes the values, enables, and verifies from a re-read', async () => {
  const gateway = fakeGateway()
  const expected = { disabled_subjects: 'money.prices', topic_games: false }

  const lines = await mod.copyToProfiles(gateway.request, { enable: true, expected, targets: ['coder'] })

  assert.equal(lines.length, 1)
  assert.deepEqual(lines[0].problems, [])
  assert.equal(lines[0].copied, 2)
  assert.equal(lines[0].enabled, true)

  // The off switch must never travel, on any call.
  for (const [method, params] of gateway.calls) {
    assert.equal(method, 'plugins.manage')
    assert.equal(params.profile, 'coder', 'every RPC must carry the target profile')
    assert.equal(Boolean(params.values && 'enabled' in params.values), false)
  }

  // Order: settings, then toggle, then the verifying read.
  assert.deepEqual(
    gateway.calls.map(([, p]) => p.action),
    ['settings', 'toggle', 'list']
  )
  assert.deepEqual(gateway.profiles.coder.settings, expected)
})

await check('a backend that drops a value is reported, not celebrated', async () => {
  const gateway = fakeGateway({ dropKey: 'topic_games' })
  const expected = { disabled_subjects: 'money.prices', topic_games: false }

  const lines = await mod.copyToProfiles(gateway.request, { enable: false, expected, targets: ['coder'] })

  assert.equal(lines[0].copied, 1)
  assert.match(lines[0].problems.join(' '), /did not take: topic_games/)
})

await check('a profile known to lack the plugin is reported, not written to', async () => {
  const gateway = fakeGateway()
  const lines = await mod.copyToProfiles(gateway.request, {
    enable: true,
    expected: { topic_games: false },
    missing: ['ops'],
    targets: ['ops']
  })

  assert.match(lines[0].problems.join(' '), /not installed for this profile/)
  assert.deepEqual(gateway.calls, [], 'no RPC may be sent for a profile without the plugin')
})

await check('the Settings action deep-links the agent form, already scoped to the profile', () => {
  const params = new URLSearchParams(seam.settingsHref('coder').split('?')[1])

  assert.equal(params.get('tab'), 'plugins')
  assert.equal(params.get('agent'), 'hubris')
  assert.equal(params.get('profile'), 'coder')
})

await check('mapLimit caps concurrency and keeps the input order', async () => {
  let live = 0
  let peak = 0

  const out = await seam.mapLimit([1, 2, 3, 4, 5, 6, 7], 3, async n => {
    live += 1
    peak = Math.max(peak, live)
    await new Promise(resolve => setTimeout(resolve, 5))
    live -= 1

    return n * 2
  })

  assert.equal(peak <= 3, true, `peak concurrency was ${peak}`)
  assert.deepEqual(out, [2, 4, 6, 8, 10, 12, 14])
})

await check('the copy returns the row it verified, so the caller need not re-read', async () => {
  const gateway = fakeGateway()
  const lines = await mod.copyToProfiles(gateway.request, {
    enable: true,
    expected: { topic_games: false },
    targets: ['coder']
  })

  assert.equal(lines[0].row.key, 'hubris')
  assert.equal(lines[0].row.status, 'enabled')
  assert.equal(seam.isEnabled(lines[0].row), true)
})

await check('a failing profile does not stop the others', async () => {
  const gateway = fakeGateway()
  const expected = { topic_games: false }
  const lines = await mod.copyToProfiles(gateway.request, {
    enable: true,
    expected,
    targets: ['coder', 'nope', 'ops']
  })

  assert.equal(lines.length, 3)
  assert.deepEqual(lines[0].problems, [])
  assert.match(lines[1].problems.join(' '), /unknown profile nope/)
  assert.deepEqual(lines[2].problems, [])
})

await check('copying no values still enables and still verifies', async () => {
  const gateway = fakeGateway()
  const lines = await mod.copyToProfiles(gateway.request, { enable: true, expected: {}, targets: ['ops'] })

  assert.equal(lines[0].copied, 0)
  assert.equal(lines[0].enabled, true)
  assert.deepEqual(
    gateway.calls.map(([, p]) => p.action),
    ['toggle', 'list']
  )
})

// ─────────────────────────────────────────────────────────────────────── registration

await check('register installs one settings page and no panes', () => {
  const pages = []
  let notify = null

  mod.default.register({
    notifyError: message => {
      notify = message
    },
    registerSettingsPage: page => pages.push(page)
  })

  assert.equal(pages.length, 1)
  assert.equal(pages[0].id, 'profiles')
  assert.equal(pages[0].title, 'HUBRIS profiles')
  assert.equal(typeof pages[0].render, 'function')
  assert.equal(notify, null)
})

await check('an older build without registerSettingsPage says so instead of failing', () => {
  const notices = []

  sdk.host.notifyError = message => notices.push(message)
  mod.default.register({})
  assert.match(notices.join(' '), /newer Desktop build/)
})

await check('the page renders its loading state without throwing', async () => {
  const { renderToStaticMarkup } = await import('react-dom/server')
  const pages = []

  mod.default.register({ registerSettingsPage: page => pages.push(page) })

  const markup = renderToStaticMarkup(pages[0].render())

  assert.match(markup, /Reading profile settings/)
})

// ─────────────────────────────────────────────────────────────────────────────── report

const failed = results.filter(([status]) => status === 'FAIL')

for (const [status, name] of results) {
  console.log(`${status} ${name}`)
}

console.log(failed.length ? `\n${failed.length} failed` : '\nall checks passed')
process.exit(failed.length ? 1 : 0)
