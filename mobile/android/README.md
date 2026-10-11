# Android

The generated Android Studio / Gradle project. Everything here is Android only; iOS lives in `../ios/`.

- Package: `com.yerp.app` (`app/build.gradle`)
- Permissions: `app/src/main/AndroidManifest.xml` (internet, camera, notifications)
- Push: put Firebase's `app/google-services.json` here (git-ignored). Without it the app builds and push stays off.
- Release signing: copy `keystore.properties.example` to `keystore.properties` (git-ignored), or let CI use the secrets below.

Build on a laptop with the Android SDK: `cd mobile && npx cap sync android && cd android && ./gradlew assembleDebug`.
CI needs no setup: `.github/workflows/mobile-build.yml` builds the debug APK and the release AAB.

CI secrets (all optional): `ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD`, `GOOGLE_SERVICES_JSON`.
