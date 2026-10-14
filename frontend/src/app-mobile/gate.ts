import { Capacitor } from '@capacitor/core'

/**
 * Whether to draw the phone app's own layout (src/app-mobile) instead of the website's.
 *
 * - The website's build defines __MOBILE_UI__ as false, so every use of this folder is removed from it: nothing here
 *   can change the website, whatever is done in this folder.
 * - In the installed app it is always on.
 * - To try it in a browser (a dev server or a "mobile" build): add ?appui=1 once to the address; ?appui=0 turns it off.
 */
export function appUi(): boolean {
  if (typeof __MOBILE_UI__ === 'undefined' || !__MOBILE_UI__) return false
  if (Capacitor.isNativePlatform()) return true
  try {
    const q = new URLSearchParams(location.search).get('appui')
    if (q === '1') localStorage.setItem('yerp.appui', '1')
    if (q === '0') localStorage.removeItem('yerp.appui')
    return localStorage.getItem('yerp.appui') === '1'
  } catch {
    return false
  }
}
