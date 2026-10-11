import { Capacitor } from '@capacitor/core'
import { App } from '@capacitor/app'
import { StatusBar, Style } from '@capacitor/status-bar'
import { SplashScreen } from '@capacitor/splash-screen'

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
