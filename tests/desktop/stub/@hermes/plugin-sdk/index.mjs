/**
 * Stub of the Desktop plugin SDK, for the headless harness only.
 *
 * The real module lives inside the app bundle. A stub keeps the test honest about which SDK
 * doors the plugin actually uses: if the plugin reaches for something missing here, the harness
 * fails instead of silently depending on the app.
 */
const listeners = []

export const host = {
  /** Swapped per test. */
  request: async () => {
    throw new Error('host.request called before the harness installed a fake')
  },
  state: {
    profile: {
      get: () => 'default',
      listen: fn => {
        listeners.push(fn)

        return () => listeners.splice(listeners.indexOf(fn), 1)
      }
    }
  },
  notify: () => undefined,
  notifyError: () => undefined
}

export const ROUTES_AREA = 'routes'
export const SIDEBAR_NAV_AREA = 'sidebar.nav'
export const PALETTE_AREA = 'palette'
export const SETTINGS_PLUGINS_AREA = 'settings.plugins'
