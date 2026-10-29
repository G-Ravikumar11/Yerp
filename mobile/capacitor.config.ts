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
    },
    StatusBar: {
      style: 'DARK',
      backgroundColor: '#0b0b0e',
    },
  },
}

export default config
