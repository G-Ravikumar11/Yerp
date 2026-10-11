import { Capacitor } from '@capacitor/core'
import { App } from '@capacitor/app'
import { Camera, CameraResultType, CameraSource } from '@capacitor/camera'
import { StatusBar, Style } from '@capacitor/status-bar'
import { SplashScreen } from '@capacitor/splash-screen'
import { PushNotifications } from '@capacitor/push-notifications'
import { get, post } from '@/lib/api'

/**
 * Initializes mobile-native behaviors when running inside a native
 * Capacitor wrapper (Android / iOS). Does nothing in standard web browsers.
 */
export async function initMobile() {
  if (!Capacitor.isNativePlatform()) return

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
