import { Capacitor } from '@capacitor/core'

// Two apps share one build: the company's public front page at "/" and the ERP under "/next/". Each is its own
// bundle with its own styles, so opening one never downloads or restyles the other.
// In development the ERP owns "/", so the front page is at /site.
// The native app is the ERP alone: it opens at "/", which there is the ERP's home, never the front page.
const onSite = !Capacitor.isNativePlatform() && location.pathname === (import.meta.env.PROD ? '/' : '/site')
if (onSite) void import('./features/site/boot')
else void import('./boot-app')
