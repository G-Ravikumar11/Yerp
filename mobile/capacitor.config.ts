import type { CapacitorConfig } from '@capacitor/cli'

const config: CapacitorConfig = {
  appId: 'com.yerp.app',
  appName: 'Y ERP',
  webDir: '../frontend/dist',
  server: {
    androidScheme: 'https',
    cleartext: false,
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
