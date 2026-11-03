import type { CapacitorConfig } from '@capacitor/cli'

const config: CapacitorConfig = {
  appId: 'com.yerp.app',
  appName: 'Y ERP',
  webDir: '../frontend/dist',
  // Behind the page and the system bars: dark like the status bar, so the gesture bar and the side margin in landscape are not
  // left as a white strip.
  backgroundColor: '#0b0b0e',
  server: {
    androidScheme: 'https',
    cleartext: false,
  },
  android: {
    // The page sits between the status bar and the gesture bar on every Android version, instead of drawing under them
    // (where the top row and the bottom tab bar were hidden behind them).
    adjustMarginsForEdgeToEdge: 'force',
  },
  plugins: {
    SplashScreen: {
      launchShowDuration: 1500,
      launchAutoHide: true,
      backgroundColor: '#ffffff',
      showSpinner: false,
    },
    // Over-the-air screens, driven by the app itself (lib/mobile.ts) from our own server: no Capgo account, and the
    // plugin's own checks and usage reports to Capgo's servers are off.
    CapacitorUpdater: {
      autoUpdate: false,
      statsUrl: '',
      // New screens are kept once the app has loaded and a person is signed in (markScreensGood in lib/mobile.ts), which on a
      // slow connection takes longer than the plugin's 10 seconds: a good build was dropped for being slow.
      appReadyTimeout: 60000,
    },
    // An iPhone shows a notice that arrives while the app is open only if told to; Android is handled in lib/mobile.ts.
    PushNotifications: {
      presentationOptions: ['badge', 'sound', 'alert'],
    },
    StatusBar: {
      style: 'DARK',
      backgroundColor: '#0b0b0e',
    },
  },
}

export default config
