# backend/app/static

Files the server sends at the root of the site itself, rather than as part of the React app.

| File | Served at | Why it is here |
| --- | --- | --- |
| `legacy-sw.js` | `/sw.js` | The old app's service worker, now one that deletes itself and its caches. Phones that installed the old app still ask for `/sw.js`; this is what stops them showing the old pages. |
| `legacy-manifest.webmanifest` | `/manifest.webmanifest` | The old app's install manifest, for the same phones. |

Everything else the browser loads (the app, its icons, the favicons) comes from the React build in `frontend/dist`.
See `app/core/static.py` for the routes.
