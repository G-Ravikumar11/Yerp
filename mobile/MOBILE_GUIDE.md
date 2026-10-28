# Mobile Apps Guide (Google Play Store & Apple App Store)

This repository is configured to build native **Android** and **iOS** apps from `frontend` using **Capacitor** and **GitHub Actions**.

Because all native compilation happens in the cloud via GitHub Actions:
- **No Android Studio, Java SDK, or heavy tooling is required on your Windows machine.**
- **iOS apps are compiled on hosted Apple Silicon macOS runners in the cloud.**
- Your day-to-day web development stays fast and lightweight with `npm run dev`.

---

## 1. How It Works

```
frontend (Vite + React)
        │
        ├──> npm run build:mobile (outputs to frontend/dist/)
        │
        └──> Capacitor Bridge (syncs web bundle into native platforms)
                ├──> Android (Gradle / Java)  ──>  .apk (testing) & .aab (Play Store)
                └──> iOS (Xcode / Swift)      ──>  .xcarchive / .ipa (App Store & TestFlight)
```

---

## 2. Triggering a Cloud Build

### Option A: From GitHub UI (Recommended)
1. Commit and push your code to GitHub.
2. Go to your repository on GitHub and click the **Actions** tab.
3. In the sidebar, select **Build Mobile Apps (Android & iOS)**.
4. Click **Run workflow**:
   - (Optional) Enter your backend URL into `Backend API Base URL` (e.g. `https://your-yerp.up.railway.app`).
   - Click the green **Run workflow** button.
5. GitHub will spin up an **Ubuntu runner** for Android and a **macOS runner** for iOS in parallel.

### Option B: Automatic Push Trigger
Pushing any changes inside `frontend/` to the `main` branch automatically triggers the build.

---

## 3. Downloading & Testing Builds

Once the workflow run finishes:
1. Open the workflow run summary page.
2. Scroll down to the **Artifacts** section:
   - **`Yerp-Android-Debug-APK`**: Download this `.apk` to test directly on any Android phone (no Play Store account needed!). Just transfer the `.apk` file to your phone via USB, WhatsApp, or Drive and tap "Install".
   - **`Yerp-Android-PlayStore-AAB`**: This is the official Android App Bundle format required by the Google Play Console for store distribution.
   - **`Yerp-iOS-Archive`**: Contains the compiled iOS build archive ready for signing and TestFlight distribution.

---

## 3b. Updating phones without a new APK (over the air)

Most changes are screens. Those reach phones on their own:

1. Push to `abhi` or `master`. The workflow builds the screens and publishes them as a release tagged `web-v<run number>` (a `web-<n>.zip`).
2. The server's `GET /api/app/web/latest` reports the newest one (read from GitHub, cached for 10 minutes).
3. Each phone checks when the app opens and when it is brought back. A newer bundle is downloaded quietly, and a "New screens are ready" message offers **Restart now**. Otherwise the new screens are used the next time the app starts. Nothing to install, and the person stays signed in.
4. If the new screens fail to start, the phone goes back to the last ones that worked, and does not try that bundle again.

What still needs a new APK: anything native (a new plugin, permissions, the icon, `capacitor.config.ts`). When a build adds one, set `mobile/web-min-native.txt` to that build's run number, so phones on an older APK are not handed screens they cannot run; they get the "Update available" prompt instead. The first APK that contains the updater has to be installed by hand once; after that, screens arrive by themselves.

The screens' release is public (the repository is), and the app only accepts a bundle whose address is on `https://github.com/`.

---

## 3c. What the phone app lets people change

The website and the app share one server and one set of accounts, but the app changes less. Signing in from the app stamps
the session `channel = "app"` (in the signed cookie, so it cannot be dropped without signing in again), and from then on the
rules in `backend/app/core/app_limits.py` apply. The website is never held to them.

- **Not held to them:** the Master (the account holder), the account's admins, and staff whose access level is Master. The
  app is the whole website to them.
- **Everyone else, in the app:** can look at everything their access lets them see, and changes only what one of four
  "Phone app" rights allows. The Master gives or takes these away person by person, on the same Access screen as every other
  right (they are a "Phone app" group there):

  | Right | What it allows in the app | Given to, by default |
  |---|---|---|
  | `app.site_edit` | Site work: diary, photos, measurements, material in, safety, quality, task progress | roles that record site work on the website |
  | `app.approve` | Approve and reject | roles that approve bills, subcontracts or site work |
  | `app.download_pdf` | Download a PDF, a stored document or a drawing | everybody |
  | `app.download_excel` | Download an Excel report | nobody (by hand) |

- **Never from the app, for anyone but the above:** billing, orders, settings, people, deleting. Their own things (sign in/out,
  clock in, leave, chat, the push token) are always open.
- **To change the policy**, edit the tables at the top of `app_limits.py`. To change a person, use the Access screen.
- The app sends `channel: "app"` in its sign-in request only. An older app (or a browser) sends nothing and is the website.

---

## 3d. Downloads (PDF, Excel) in the app

The website's download buttons are plain links to the server. In the app a bare `/api/...` address points at the app's own
files, and the phone's browser has none of the person's sign-in, so they did nothing. `frontend/src/lib/download.ts` fixes
every such button at once, without editing any of them: in the native app it catches a tap on a link to an `/api/` file
(`.pdf .xlsx .xls .csv .docx .zip`, or marked `download`), a `window.open` of one, and a script clicking a link it made;
fetches the file itself with the person's sign-in; keeps it in the phone's cache; and opens Android's Open / Share choices.
The server's refusals (the app rights in 3c) show as a message. The website never runs any of this.

It uses two native plugins, `@capacitor/filesystem` and `@capacitor/share`, so it needs one new APK. On an older APK the screens
still load, and a download says "Install the latest version of the app to download files." Once the new APK is out, set
`mobile/web-min-native.txt` to its build number if older phones should stop receiving screens that rely on it.

---

## 4. Connecting the Mobile App to Your Backend

When running inside a native mobile wrapper (Android / iOS), the app needs to know where your live API lives:

1. **Via GitHub Repository Secrets (Permanent):**
   - In GitHub: **Settings** → **Secrets and variables** → **Actions** → **New repository secret**.
   - Name: `VITE_API_BASE_URL`
   - Value: `https://your-yerp.up.railway.app` (your Railway backend URL)
2. **Via Workflow Dispatch Input (Per-Run):**
   - You can enter the API URL dynamically each time you trigger the workflow manually.

---

## 5. Publishing to Google Play Store

### Step 1: Create a Google Play Console Account
- Register at [play.google.com/console](https://play.google.com/console) ($25 one-time registration fee).
- Complete developer identity verification.

### Step 2: Generate an Upload Keystore (One-time)
Run this command in PowerShell or terminal once to generate your private signing key:
```bash
keytool -genkey -v -keystore yerp-release-key.jks -keyalg RSA -keysize 2048 -validity 10000 -alias yerp
```
*(Keep this keystore file and its password in a secure location! Google requires this key for all future app updates).*

### Step 3: Upload to Play Console
1. In Google Play Console, click **Create app** (App name: *Y ERP*, Default language, App or Game: *App*, Free/Paid).
2. Go to **Testing** → **Internal testing** (or **Closed testing**).
3. Create a new release and upload the `app-release.aab` from GitHub Actions.
4. Add tester email addresses to test internally before promoting to Production.

---

## 6. Publishing to Apple App Store

### Step 1: Apple Developer Program
- Enroll at [developer.apple.com](https://developer.apple.com) ($99/year membership).
- Create an **App ID** (e.g. `com.yerp.app`) under Certificates, Identifiers & Profiles.

### Step 2: TestFlight Beta Distribution
1. Create a new App in [App Store Connect](https://appstoreconnect.apple.com).
2. Upload the build to TestFlight using Transporter or the Xcode organizer.
3. Invite internal and external testers to test the app seamlessly on iPhones and iPads before public release.

---

## 7. Key Project Files Configured

- [frontend/capacitor.config.ts](file:///c:/Users/choco/Music/git%20proj/Yerp/frontend/capacitor.config.ts) – Capacitor app identification & native plugins.
- [frontend/src/lib/mobile.ts](file:///c:/Users/choco/Music/git%20proj/Yerp/frontend/src/lib/mobile.ts) – Native hardware back-button, status bar, and splash screen handling.
- [frontend/src/lib/api.ts](file:///c:/Users/choco/Music/git%20proj/Yerp/frontend/src/lib/api.ts) – Dynamic API resolution supporting remote backend URLs (`VITE_API_BASE_URL`).
- [frontend/vite.config.ts](file:///c:/Users/choco/Music/git%20proj/Yerp/frontend/vite.config.ts) – Dual-mode build support (web served by FastAPI `/next/` vs mobile webview).
- [.github/workflows/mobile-build.yml](file:///c:/Users/choco/Music/git%20proj/Yerp/.github/workflows/mobile-build.yml) – CI/CD pipeline building Android & iOS in the cloud.
