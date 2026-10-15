import { loadEnv, type Plugin } from 'vite'

/**
 * Switches the phone app's own layout (src/app-mobile) on or off for a build.
 *
 * It is on for the mobile build (`vite build --mode mobile`) and the dev server, so it can be tried; it is off for the
 * website's build, which then leaves that folder out of the bundle altogether. Kept in its own file so that the build
 * settings in vite.config.ts need no line for it other than this plugin's name.
 */
export function mobileUi(): Plugin {
  return {
    name: 'yerp-mobile-ui',
    config(_user, { mode, command }) {
      const env = loadEnv(mode, process.cwd(), '')
      const on = mode === 'mobile' || env.VITE_MOBILE === 'true' || command === 'serve'
      return { define: { __MOBILE_UI__: JSON.stringify(on) } }
    },
  }
}
