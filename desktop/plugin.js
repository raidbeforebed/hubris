/**
 * hubris desktop half: copy this plugin's settings between profiles, enable or disable it there.
 *
 * The need: settings are per profile and profiles inherit nothing, so a fleet tunes the same
 * eleven topics seven times by hand. This page reads the values a profile is actually running,
 * writes them onto the profiles you pick, and flips the plugin on or off per profile.
 *
 * Everything goes through the gateway's own `plugins.manage` RPC with an explicit `profile`
 * parameter. That RPC is profile-scoped and writes through the same seam the settings form
 * uses, so this page adds no privileged server code and no second config writer.
 *
 * Styling uses the app's own tokens (`--ui-accent`, `--ui-text-*`, `--ui-stroke-*`,
 * `--ui-bg-elevated`). The widget tokens (`--accent`, `--border`, `--card`) do not exist in this
 * tree, and drawing with them renders nothing, which is how a progress bar and every chip went
 * invisible on first ship.
 *
 * Deliberate choices:
 *   - The roster is one fast call and paints the page. Each profile's plugin state then fills in
 *     as it arrives, with a determinate bar.
 *   - The last roster and rows are cached in this module, so returning paints at once.
 *   - The source's `enabled` switch is never copied: carrying a saved "off" onto a profile you
 *     just enabled would silently undo the enable. Enabling and disabling are explicit actions.
 *   - Every write is read back and compared, and the result stays on screen afterwards.
 *   - A target that does not carry the plugin is reported and skipped rather than written to.
 */
import * as sdk from '@hermes/plugin-sdk'
import { createElement as h, useCallback, useEffect, useMemo, useState } from 'react'

const PLUGIN_ID = 'hubris'
const RPC = 'plugins.manage'

/** Settings key that is the plugin's own off switch, not a preference to copy. */
const OFF_SWITCH = 'enabled'

/** Last read roster and rows, so a remount has something to paint before the network moves. */
const cache = { roster: [], rows: {}, total: 0 }

/** The desktop socket's default is 30 s, and a profile with a full plugin tree can exceed it. */
const READ_TIMEOUT = 90_000

/** Reads in flight at once. Twelve at once queue behind each other in the gateway, and the ones
 *  at the tail are what hit the socket deadline; three keeps every read short. */
const READ_CONCURRENCY = 3

/** Run `task` over `items` with at most `limit` in flight. */
async function mapLimit(items, limit, task) {
  const out = new Array(items.length)
  let next = 0

  const workers = Array.from({ length: Math.max(1, Math.min(limit, items.length)) }, async () => {
    while (next < items.length) {
      const at = next++

      out[at] = await task(items[at], at)
    }
  })

  await Promise.all(workers)

  return out
}

// ────────────────────────────────────────────────────────────── pure seams (tested headlessly)

/** The hubris row from a `plugins.manage list` answer, or null. */
export function findRow(rows, key = PLUGIN_ID) {
  if (!Array.isArray(rows)) {
    return null
  }

  return rows.find(row => row && (row.key === key || row.name === key)) ?? null
}

/** A row's current values keyed by setting name, with the off switch left out. */
export function valuesToCopy(row) {
  const fields = Array.isArray(row?.settings_schema) ? row.settings_schema : []
  const out = {}

  for (const field of fields) {
    const key = field?.key

    if (!key || key === OFF_SWITCH) {
      continue
    }

    // `undefined` means the schema declared no value; `null` is not a valid setting here.
    if (field.value === undefined || field.value === null) {
      continue
    }

    out[key] = field.value
  }

  return out
}

/** How many values the source would actually carry. */
export function copyCount(row) {
  return Object.keys(valuesToCopy(row)).length
}

/** Keys whose value on `target` does not match `expected` after a write. */
export function mismatches(expected, targetRow) {
  const fields = Array.isArray(targetRow?.settings_schema) ? targetRow.settings_schema : []
  const current = Object.fromEntries(fields.filter(Boolean).map(f => [f.key, f.value]))

  return Object.keys(expected).filter(key => current[key] !== expected[key])
}

/** A row's enable state, tolerant of the several words the backend uses. */
export function isEnabled(row) {
  const status = String(row?.status ?? '').toLowerCase()

  if (status) {
    return status === 'enabled' || status === 'active' || status === 'on'
  }

  return Boolean(row?.enabled)
}

/** Deep link to the plugin's own settings form, already scoped to one profile.
 *
 *  The route contract (settings-pages.ts): `?tab=plugins&agent=<key>` opens an agent plugin's
 *  schema form, and `&profile=<name>` is the hand-off Settings adopts into its scope and then
 *  drops from the URL. The SDK exports only the desktop-page helper, so this builds the agent
 *  form's route directly rather than making the user re-pick the profile by hand.
 */
export function settingsHref(profile) {
  const params = new URLSearchParams({ agent: PLUGIN_ID, tab: 'plugins' })

  if (profile) {
    params.set('profile', profile)
  }

  return `/settings?${params}`
}

/** Copy `expected` onto each target profile, optionally enabling the plugin, then verify each.
 *  `missing` names targets the caller already knows do not carry the plugin: those are reported
 *  and skipped, because the settings writer would fail with "plugin not found" after a pointless
 *  round trip. */
export async function copyToProfiles(request, { targets, expected, enable, missing = [] }) {
  const absent = new Set(missing)
  const lines = []

  for (const name of targets) {
    const line = { copied: 0, enabled: null, name, problems: [], row: null }

    if (absent.has(name)) {
      line.problems.push('hubris is not installed for this profile, so there is nothing to write')
      lines.push(line)
      continue
    }

    try {
      if (Object.keys(expected).length) {
        await request(RPC, { action: 'settings', key: PLUGIN_ID, profile: name, values: expected })
      }

      if (enable) {
        await request(RPC, { action: 'toggle', enable: true, key: PLUGIN_ID, profile: name })
      }

      // Read the profile back: the only proof that matters.
      const answer = await request(RPC, { action: 'list', profile: name })
      const after = findRow(answer?.plugins)
      line.row = after

      if (!after) {
        line.problems.push('the plugin was not listed for this profile afterwards')
      } else {
        line.copied = Object.keys(expected).length - mismatches(expected, after).length
        line.enabled = isEnabled(after)

        const wrong = mismatches(expected, after)

        if (wrong.length) {
          line.problems.push(`did not take: ${wrong.join(', ')}`)
        }

        if (enable && !line.enabled) {
          line.problems.push('still not enabled')
        }
      }
    } catch (e) {
      line.problems.push(String(e?.message ?? e))
    }

    lines.push(line)
  }

  return lines
}

// ────────────────────────────────────────────────────────────────────────────────── page

/** The app's own CSS tokens. Anything outside this list renders as nothing. */
const ACCENT = 'var(--ui-accent)'
const BORDER = 'var(--ui-stroke-secondary)'
const TEXT = 'var(--ui-text-primary)'
const DIM = 'var(--ui-text-secondary)'
const FAINT = 'var(--ui-text-tertiary)'
const ELEVATED = 'var(--ui-bg-elevated)'
const RED = 'var(--ui-red)'
const GREEN = 'var(--ui-green)'

const chip = active => ({
  background: active ? ACCENT : 'transparent',
  border: `1px solid ${active ? ACCENT : BORDER}`,
  borderRadius: '999px',
  color: active ? 'var(--ui-base)' : TEXT,
  cursor: 'pointer',
  font: 'inherit',
  fontSize: '0.78rem',
  padding: '0.15rem 0.65rem'
})

const smallButton = colour => ({
  background: 'transparent',
  border: `1px solid ${BORDER}`,
  borderRadius: '0.3rem',
  color: colour,
  cursor: 'pointer',
  font: 'inherit',
  fontSize: '0.72rem',
  padding: '0.1rem 0.5rem'
})

const wrap = { color: TEXT, display: 'grid', gap: '1.1rem', maxWidth: '46rem' }
const muted = { color: DIM, fontSize: '0.8rem', lineHeight: 1.5 }
const faint = { color: FAINT, fontSize: '0.8rem', lineHeight: 1.5 }
const rowStyle = { alignItems: 'center', display: 'flex', gap: '0.6rem', padding: '0.28rem 0' }
const sectionLabel = {
  color: DIM,
  fontSize: '0.72rem',
  letterSpacing: '0.04em',
  textTransform: 'uppercase'
}

/** The row being copied from: same column rhythm, marked rather than moved out of the list. */
const currentRow = { borderLeft: `2px solid ${ACCENT}`, paddingLeft: '0.45rem' }
const currentTag = {
  border: `1px solid ${BORDER}`,
  borderRadius: '999px',
  color: DIM,
  fontSize: '0.62rem',
  letterSpacing: '0.03em',
  padding: '0 0.35rem',
  textTransform: 'uppercase'
}

/** Determinate bar with a percentage, so a slow read reads as progress and not as a freeze. */
function Progress({ done, total }) {
  const pct = total ? Math.round((done / total) * 100) : 0

  return h(
    'div',
    { style: { display: 'grid', gap: '0.35rem' } },
    h(
      'div',
      { style: { ...muted, display: 'flex', justifyContent: 'space-between' } },
      h('span', null, `Reading profile settings, ${done} of ${total}`),
      h('span', { style: faint }, `${pct}%`)
    ),
    h(
      'div',
      {
        style: {
          background: ELEVATED,
          border: `1px solid ${BORDER}`,
          borderRadius: '999px',
          height: '6px',
          overflow: 'hidden',
          width: '100%'
        }
      },
      h('div', {
        style: {
          background: ACCENT,
          height: '100%',
          transition: 'width 160ms linear',
          width: `${pct}%`
        }
      })
    )
  )
}

function ProfilesPage() {
  const request = sdk.host.request
  const [roster, setRoster] = useState(cache.roster)
  const [rows, setRows] = useState(cache.rows)
  const [total, setTotal] = useState(cache.total)
  const [done, setDone] = useState(0)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState(null)
  const [source, setSource] = useState(null)
  const [targets, setTargets] = useState(() => new Set())
  const [copyValues, setCopyValues] = useState(true)
  const [enable, setEnable] = useState(true)
  const [busy, setBusy] = useState(false)
  const [pending, setPending] = useState(() => new Set())
  const [results, setResults] = useState(null)

  const entryFor = name => rows[name] ?? null

  /** One profile's plugin row. Never throws: a failure becomes a row state you can retry. */
  const readProfile = useCallback(
    async name => {
      try {
        const answer = await request(RPC, { action: 'list', profile: name }, READ_TIMEOUT)

        return { row: findRow(answer?.plugins) }
      } catch (e) {
        return { failed: String(e?.message ?? e) }
      }
    },
    [request]
  )

  const applyRow = (name, entry) =>
    setRows(prev => {
      const next = { ...prev, [name]: entry }
      cache.rows = next

      return next
    })

  const load = useCallback(async () => {
    setRefreshing(true)
    setError(null)

    try {
      // One fast call draws the whole page: chips, every target row, the checkboxes.
      const listed = await request('profiles.list', {})
      const names = (listed?.profiles ?? []).map(p => p?.name).filter(Boolean)
      const active = sdk.host.state.profile?.get?.() ?? null

      setRoster(names)
      setTotal(names.length)
      setDone(0)
      setSource(prev =>
        prev && names.includes(prev) ? prev : names.includes(active) ? active : (names[0] ?? null)
      )

      // Then each profile's plugin state, painted as it lands, a few at a time.
      await mapLimit(names, READ_CONCURRENCY, async name => {
        applyRow(name, await readProfile(name))
        setDone(n => n + 1)
      })

      cache.roster = names
      cache.total = names.length
    } catch (e) {
      setError(String(e?.message ?? e))
    }

    setRefreshing(false)
  }, [readProfile, request])

  useEffect(() => {
    void load()
  }, [load])

  const sourceRow = source ? (entryFor(source)?.row ?? null) : null
  const sourceValues = useMemo(() => valuesToCopy(sourceRow), [sourceRow])
  const targetList = useMemo(() => roster.filter(name => name !== source), [roster, source])
  const reading = refreshing && done < total

  const setPendingFor = (name, on) =>
    setPending(prev => {
      const next = new Set(prev)

      if (on) {
        next.add(name)
      } else {
        next.delete(name)
      }

      return next
    })

  /** Flip the plugin on or off for one profile, then read it back. */
  const toggleProfile = async name => {
    const row = entryFor(name)?.row

    if (!row || pending.has(name)) {
      return
    }

    const want = !isEnabled(row)
    setPendingFor(name, true)

    try {
      await request(RPC, { action: 'toggle', enable: want, key: PLUGIN_ID, profile: name }, READ_TIMEOUT)

      let after = await readProfile(name)

      // A profile that has never loaded resolves its state from config, which the toggle just
      // wrote. If the first read lands before that write is visible, confirm once more before
      // telling the user anything.
      if (!after.row || isEnabled(after.row) !== want) {
        await new Promise(resolve => setTimeout(resolve, 800))
        const again = await readProfile(name)

        if (again.row && isEnabled(again.row) === want) {
          after = again
        }
      }

      applyRow(name, after)

      if (after.row && isEnabled(after.row) !== want) {
        setResults([
          {
            copied: 0,
            enabled: isEnabled(after.row),
            name,
            problems: [`asked to ${want ? 'enable' : 'disable'}, but it still reads ${isEnabled(after.row) ? 'enabled' : 'not enabled'}`]
          }
        ])
      }
    } catch (e) {
      setResults([{ copied: 0, enabled: null, name, problems: [String(e?.message ?? e)] }])
    }

    setPendingFor(name, false)
  }

  /** Re-read one profile after a failed read, showing "reading…" while it runs. */
  const retryProfile = async name => {
    setRows(prev => {
      const next = { ...prev }
      delete next[name]

      return next
    })
    applyRow(name, await readProfile(name))
  }

  /** Re-read every profile whose last read failed, a few at a time. */
  const retryAllFailed = async () => {
    const failed = roster.filter(name => entryFor(name)?.failed)

    await mapLimit(failed, READ_CONCURRENCY, name => retryProfile(name))
  }

  const toggleTarget = name => {
    setTargets(prev => {
      const next = new Set(prev)

      if (next.has(name)) {
        next.delete(name)
      } else {
        next.add(name)
      }

      return next
    })
  }

  const run = async () => {
    const chosen = targetList.filter(name => targets.has(name))

    if (!chosen.length) {
      return
    }

    setBusy(true)
    setResults(null)

    const lines = await copyToProfiles(request, {
      enable,
      expected: copyValues ? sourceValues : {},
      missing: chosen.filter(name => !entryFor(name)?.row),
      targets: chosen
    })

    setResults(lines)
    setBusy(false)
    // Clearing the selection stops the next click from repeating an identical copy.
    setTargets(new Set())
    // Merge the verified rows back instead of re-reading all twelve profiles: the copy already
    // read each target back, and a full rescan made the page flash a fresh 0 of 12.
    setRows(prev => {
      const next = { ...prev }

      for (const line of lines) {
        if (line.row !== undefined) {
          next[line.name] = { row: line.row }
        }
      }

      cache.rows = next

      return next
    })
  }

  if (error) {
    return h(
      'div',
      { style: wrap },
      h('div', { style: { color: RED } }, `Could not read the profile list: ${error}`),
      h(
        'button',
        { onClick: () => void load(), style: { ...smallButton(TEXT), justifySelf: 'start' } },
        'Try again'
      )
    )
  }

  if (!roster.length) {
    return h('div', { style: wrap }, h(Progress, { done: 0, total: 1 }))
  }

  const chosenCount = targetList.filter(name => targets.has(name)).length
  const failedCount = roster.filter(name => entryFor(name)?.failed).length
  const anyMissing = roster.some(name => !entryFor(name)?.row && !entryFor(name)?.failed)

  /** Enable or disable this profile's copy, or nothing when it does not carry the plugin. */
  const action = name => {
    const entry = entryFor(name)

    if (!entry || entry.failed || !entry.row) {
      return null
    }

    const on = isEnabled(entry.row)
    const working = pending.has(name)

    return h(
      'span',
      { style: { display: 'flex', gap: '0.3rem' } },
      h(
        'button',
        {
          onClick: () => sdk.host.navigate(settingsHref(name)),
          style: smallButton(DIM),
          title: `Edit hubris settings for ${name}`
        },
        'Settings'
      ),
      h(
        'button',
        {
          disabled: working,
          onClick: () => void toggleProfile(name),
          style: { ...smallButton(on ? RED : ACCENT), opacity: working ? 0.5 : 1 }
        },
        working ? '…' : on ? 'Disable' : 'Enable'
      )
    )
  }

  return h(
    'div',
    { style: wrap },
    h(
      'p',
      { style: muted },
      'Copy the values this profile is using onto other profiles, then enable or disable hubris per ' +
        'profile. Each profile keeps its own copy, so you can tune one without touching the rest.'
    ),

    reading && h(Progress, { done, total }),

    h(
      'div',
      null,
      h('div', { style: { ...sectionLabel, marginBottom: '0.4rem' } }, 'Copy from'),
      h(
        'div',
        { style: { display: 'flex', flexWrap: 'wrap', gap: '0.4rem' } },
        roster.map(name =>
          h(
            'button',
            {
              key: name,
              onClick: () => {
                setSource(name)
                setTargets(new Set())
                setResults(null)
              },
              style: chip(name === source)
            },
            name
          )
        )
      )
    ),

    h(
      'div',
      null,
      h(
        'div',
        {
          style: {
            ...sectionLabel,
            alignItems: 'center',
            display: 'flex',
            gap: '0.6rem',
            marginBottom: '0.4rem'
          }
        },
        h('span', null, 'Profiles'),
        failedCount > 0 &&
          h(
            'button',
            { onClick: () => void retryAllFailed(), style: smallButton(ACCENT) },
            `Retry ${failedCount} failed read${failedCount === 1 ? '' : 's'}`
          )
      ),
      h(
        'p',
        { style: { ...faint, margin: '0 0 0.35rem' } },
        'The row marked current is the profile being copied from. Tick others to copy onto them.'
      ),
      roster.length === 0
        ? h('div', { style: muted }, 'No profiles.')
        : roster.map(name => {
            const entry = entryFor(name)
            const isSource = name === source
            const label = !entry
              ? 'reading…'
              : entry.failed
                ? `could not read: ${entry.failed}`
                : entry.row
                  ? `${isEnabled(entry.row) ? 'enabled' : 'not enabled'}, ${copyCount(entry.row)} value(s) in effect`
                  : 'not installed for this profile'

            return h(
              'div',
              { key: name, style: { ...rowStyle, ...(isSource ? currentRow : null) } },
              isSource
                ? h('span', { style: { display: 'inline-block', width: '13px' } })
                : h('input', {
                    checked: targets.has(name),
                    disabled: !entry?.row,
                    id: `hubris-target-${name}`,
                    onChange: () => toggleTarget(name),
                    type: 'checkbox'
                  }),
              h(
                'label',
                {
                  htmlFor: isSource ? undefined : `hubris-target-${name}`,
                  style: {
                    color: entry?.row ? TEXT : FAINT,
                    fontWeight: isSource ? 600 : 400,
                    minWidth: '7rem'
                  }
                },
                name
              ),
              isSource && h('span', { style: currentTag }, 'current'),
              h(
                'span',
                { style: { ...faint, color: entry?.row && isEnabled(entry.row) ? GREEN : FAINT } },
                label
              ),
              h(
                'span',
                { style: { display: 'flex', gap: '0.3rem', marginLeft: 'auto' } },
                entry?.failed &&
                  h(
                    'button',
                    { onClick: () => void retryProfile(name), style: smallButton(ACCENT) },
                    'Retry'
                  ),
                action(name)
              )
            )
          }),
      anyMissing &&
        h(
          'p',
          { style: { ...faint, marginTop: '0.3rem' } },
          'A profile marked "not installed" has no copy of the plugin, so its checkbox stays off: ' +
            'there is nothing there to write to. Give that profile the plugin first, then it becomes ' +
            'a target like any other.'
        )
    ),

    h(
      'div',
      { style: { display: 'grid', gap: '0.1rem' } },
      h(
        'label',
        { style: rowStyle },
        h('input', { checked: copyValues, onChange: e => setCopyValues(e.target.checked), type: 'checkbox' }),
        h('span', { style: { ...muted, color: TEXT } }, `Copy the setting values (${copyCount(sourceRow)})`)
      ),
      h(
        'label',
        { style: rowStyle },
        h('input', { checked: enable, onChange: e => setEnable(e.target.checked), type: 'checkbox' }),
        h('span', { style: { ...muted, color: TEXT } }, 'Enable hubris on each target')
      )
    ),

    h(
      'button',
      {
        disabled: busy || chosenCount === 0,
        onClick: () => void run(),
        style: {
          background: chosenCount ? ACCENT : ELEVATED,
          border: `1px solid ${chosenCount ? ACCENT : BORDER}`,
          borderRadius: '0.4rem',
          color: chosenCount ? 'var(--ui-base)' : FAINT,
          cursor: chosenCount ? 'pointer' : 'default',
          font: 'inherit',
          fontSize: '0.82rem',
          fontWeight: 600,
          justifySelf: 'start',
          opacity: busy ? 0.6 : 1,
          padding: '0.4rem 1rem'
        }
      },
      busy ? 'Copying…' : chosenCount ? `Copy to ${chosenCount} profile(s)` : 'Pick at least one target'
    ),

    results &&
      h(
        'div',
        {
          style: {
            background: ELEVATED,
            border: `1px solid ${BORDER}`,
            borderRadius: '0.4rem',
            padding: '0.6rem 0.8rem'
          }
        },
        h('div', { style: { ...sectionLabel, marginBottom: '0.35rem' } }, 'Result'),
        results.map(r =>
          h(
            'div',
            { key: r.name, style: muted },
            h('strong', { style: { color: r.problems.length ? RED : TEXT } }, `${r.name}: `),
            r.problems.length
              ? r.problems.join('; ')
              : `${r.copied} value(s) landed, ${r.enabled ? 'enabled' : 'not enabled'}`
          )
        )
      )
  )
}

export default {
  id: PLUGIN_ID,
  name: 'HUBRIS profiles',
  description: 'Copy HUBRIS settings between profiles and enable or disable the plugin there.',
  defaultEnabled: true,
  register(ctx) {
    if (typeof ctx.registerSettingsPage !== 'function') {
      // An older desktop build: say so once rather than rendering a dead entry.
      sdk.host.notifyError(
        'HUBRIS profiles needs a newer Desktop build (no registerSettingsPage in this one).'
      )

      return
    }

    ctx.registerSettingsPage({
      icon: 'organization',
      id: 'profiles',
      order: 20,
      render: () => h(ProfilesPage),
      title: 'HUBRIS profiles'
    })
  }
}

/** Pure seams for the headless harness. */
export const __hubrisDesktopTestSeam = {
  copyCount,
  findRow,
  isEnabled,
  mapLimit,
  mismatches,
  settingsHref,
  valuesToCopy
}
