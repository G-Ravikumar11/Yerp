# mobile/

Everything for the native apps lives here, so `frontend/` and `backend/` stay untouched when merging.

- `capacitor.config.ts` - Capacitor config (web assets come from `../frontend/dist`)
- `android/` - the Android project (generated, committed). Android-only files; see `android/README.md`
- `ios/` - the iOS project, kept apart from Android. Not generated yet (`npm run add:ios`, needs a Mac or the CI macOS runner)
- `assets/` - the iOS app icon (1024) and splash (2732), drawn from the website's icon; CI copies them into the generated iOS project
- `MOBILE_GUIDE.md` - build and publishing guide

Only shared touchpoints outside this folder: `frontend/src/lib/mobile.ts` (native init), the `mobile` mode in `frontend/vite.config.ts`, and `.github/workflows/mobile-build.yml`.

Build: `npm --prefix frontend run build:mobile`, then in `mobile/`: `npm install && npx cap sync`.
