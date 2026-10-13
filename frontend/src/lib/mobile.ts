import { Capacitor } from '@capacitor/core'
import { App } from '@capacitor/app'
import { Browser } from '@capacitor/browser'
import { Camera, CameraResultType, CameraSource } from '@capacitor/camera'
import { CapacitorUpdater } from '@capgo/capacitor-updater'
import { StatusBar, Style } from '@capacitor/status-bar'
import { SplashScreen } from '@capacitor/splash-screen'
import { PushNotifications } from '@capacitor/push-notifications'
import { api, get, post } from '@/lib/api'
import { toast } from '@/stores/toast'

/**
 * Initializes mobile-native behaviors when running inside a native
 * Capacitor wrapper (Android / iOS). Does nothing in standard web browsers.
 */
export async function initMobile() {
  if (!Capacitor.isNativePlatform()) return

  // Screens downloaded over the air are on trial until this runs: one that never gets this far is dropped, and the
  // plugin goes back to the last screens that did.
  void CapacitorUpdater.notifyAppReady().catch(() => undefined)

  try {
    // 1. Android physical & gesture back button handling
    await App.addListener('backButton', ({ canGoBack }) => {
      // If there's an open dialog/drawer or history to pop, go back; otherwise minimize/exit
      if (canGoBack && window.location.pathname !== '/' && window.location.pathname !== '') {
        window.history.back()
      } else {
        void App.exitApp()
      }
    })

    // 2. Configure native Status Bar to match dark theme
    await StatusBar.setStyle({ style: Style.Dark })
    if (Capacitor.getPlatform() === 'android') {
      await StatusBar.setBackgroundColor({ color: '#0b0b0e' })
    }

    // 3. Hide native splash screen once web app has mounted
    await SplashScreen.hide({ fadeOutDuration: 300 })
  } catch (err) {
    console.warn('Native mobile initialization encountered an issue:', err)
  }

  void checkForUpdate()
  void checkForWebUpdate()
  // A phone left with the app open for days still hears about a new build when it is brought back.
  void App.addListener('resume', () => {
    void checkForUpdate()
    void checkForWebUpdate()
  })
}

/** The build number of the screens inside this APK; the workflow stamps it (VITE_WEB_VERSION). 0 for a laptop build. */
const BAKED_WEB = Number(import.meta.env.VITE_WEB_VERSION) || 0
let offeredWeb = 0

/**
 * Over the air: when screens newer than the ones this phone runs have been published, fetch them quietly. They are
 * used the next time the app opens; "Restart now" switches straight away. Nothing to install and the person stays
 * signed in. Only screens: anything that needs a newer APK (a new native plugin) says so in its min_native and is
 * left for the "Update available" prompt above.
 */
async function checkForWebUpdate() {
  try {
    const [{ build }, latest, now, listed] = await Promise.all([
      App.getInfo(),
      api<{ version: number; zip_url?: string; min_native?: number }>('/api/app/web/latest', { quiet: true }),
      CapacitorUpdater.current(),
      CapacitorUpdater.list(),
    ])
    const running = Math.max(BAKED_WEB, Number(now.bundle.version) || 0)
    const url = latest.zip_url
    if (!url || latest.version <= running || latest.version === offeredWeb) return
    if ((Number(build) || 0) < (latest.min_native ?? 0)) return
    // Only ever our own releases, over https.
    if (!url.startsWith('https://github.com/')) return

    const version = String(latest.version)
    const have = listed.bundles.find((b) => b.version === version)
    // One that already failed on this phone is not tried again; the next build replaces it.
    if (have?.status === 'error') return
    const bundle = have ?? (await CapacitorUpdater.download({ url, version }))
    await CapacitorUpdater.next({ id: bundle.id })
    offeredWeb = latest.version
    toast.withAction('New screens are ready for Y ERP.', 'Restart now', () => {
      void CapacitorUpdater.set({ id: bundle.id })
    })

    // Older downloads are no longer needed.
    for (const old of listed.bundles) {
      if (old.id !== bundle.id && old.id !== now.bundle.id && (Number(old.version) || 0) < latest.version) {
        void CapacitorUpdater.delete({ id: old.id }).catch(() => undefined)
      }
    }
  } catch (err) {
    // No signal, an APK from before this existed, or the server has nothing published: try again next time.
    console.warn('Checking for new screens did not complete:', err)
  }
}

let offered = 0

/**
 * Android only: when a newer signed build has been published, offer it. "Update" opens the APK's download in the
 * browser; the person then taps the downloaded file and Android asks to install it over this one. (Outside the Play
 * Store, Android always asks; it cannot be done silently.) Builds are signed with one key, so it installs as an
 * update and keeps the person signed in.
 */
async function checkForUpdate() {
  if (Capacitor.getPlatform() !== 'android') return
  try {
    const [{ build }, latest] = await Promise.all([
      App.getInfo(),
      api<{ version_code: number; version_name?: string; apk_url?: string }>('/api/app/android/latest', { quiet: true }),
    ])
    const current = Number(build) || 0
    if (!latest.apk_url || latest.version_code <= current || latest.version_code === offered) return
    offered = latest.version_code
    const url = latest.apk_url
    toast.withAction(`A new version of Y ERP is available${latest.version_name ? ` (${latest.version_name})` : ''}.`, 'Update', () => {
      void Browser.open({ url })
    })
  } catch {
    // No signal, or the server is older than this check: try again next time the app opens.
  }
}

/**
 * "Take a photo": the native camera inside the iOS / Android app, the capture input in a browser.
 * `fallback` is the hidden <input capture> the web version already uses.
 */
export async function takePhoto(fallback: HTMLInputElement | null, onFiles: (files: File[]) => void) {
  if (!Capacitor.isNativePlatform()) {
    fallback?.click()
    return
  }
  try {
    const shot = await Camera.getPhoto({ quality: 80, resultType: CameraResultType.Uri, source: CameraSource.Camera, correctOrientation: true })
    if (!shot.webPath) return
    const blob = await (await fetch(shot.webPath)).blob()
    const ext = shot.format === 'png' ? 'png' : 'jpg'
    onFiles([new File([blob], `photo-${Date.now()}.${ext}`, { type: blob.type || `image/${ext === 'jpg' ? 'jpeg' : ext}` })])
  } catch {
    // The person closed the camera without a photo, or refused access: nothing to attach.
  }
}

let pushStarted = false

/**
 * Once someone is signed in, in the native app: ask permission for notifications and give this phone's token to the
 * server. Does nothing in a browser, or while the server has no push service set up (no permission is asked for nothing).
 */
export async function registerPush() {
  if (!Capacitor.isNativePlatform() || pushStarted) return
  try {
    const { enabled } = await get<{ enabled: boolean }>('/api/devices/status')
    if (!enabled) return
    pushStarted = true
    await PushNotifications.addListener('registration', ({ value }) => {
      void post('/api/devices', { token: value, platform: Capacitor.getPlatform() })
    })
    await PushNotifications.addListener('pushNotificationActionPerformed', ({ notification }) => {
      const link = notification.data?.link
      if (typeof link === 'string' && link.startsWith('/')) window.location.assign(link.replace(/^\/next/, '') || '/')
    })
    let status = await PushNotifications.checkPermissions()
    if (status.receive === 'prompt') status = await PushNotifications.requestPermissions()
    if (status.receive === 'granted') await PushNotifications.register()
  } catch (err) {
    pushStarted = false
    console.warn('Push registration did not complete:', err)
  }
}
