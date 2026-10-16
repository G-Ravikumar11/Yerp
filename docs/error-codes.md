# Error codes

Every failure the app reports shows a code, and most show a reference:

> That email and password did not match an account. (Error YE-AUTH-01)
>
> The server had a problem with that. (Error YE-SRV-01 · ref 7F3A9C21)

- **Code**: what happened, named by area. It always means the same thing.
- **Ref**: this one failure. The server writes the same ref to its log with the cause (the full traceback for a
  fault), so searching the log for `ref=7F3A9C21` finds exactly what went wrong.

When someone reports a problem, ask for both.

## Signing in

| Code | Means | What to do |
|---|---|---|
| YE-AUTH-01 | Wrong email or password | Check both. Use "Forgot password" if needed. |
| YE-AUTH-02 | Account disabled | The Master or an administrator can enable it. |
| YE-AUTH-03 | Too many sign-in attempts | Wait a few minutes before trying again. |
| YE-AUTH-04 | Signed out (session ended or never started) | Sign in again. |
| YE-AUTH-05 | Access removed | The person's access to the company was taken away. |
| YE-AUTH-06 | Password not set yet | Send the set-password email. |
| YE-AUTH-07 | Reset link invalid or expired | Ask for a new reset link. |
| YE-AUTH-08 | Email already registered | Sign in with it, or use "Forgot password". |

## Access

| Code | Means | What to do |
|---|---|---|
| YE-ACCESS-01 | Not allowed | The person's access does not include this. The Master can grant it. |
| YE-ACCESS-02 | File link expired, or for another file | Open the file again from the app. |

## Records

| Code | Means | What to do |
|---|---|---|
| YE-DATA-01 | Not found | It may have been deleted, or the link is old. |
| YE-DATA-02 | Already exists / conflicts with an existing record | Someone may have changed it. Reload and check. |
| YE-DATA-03 | Locked: signed off or issued | It cannot change. |
| YE-DATA-04 | Something entered is not right | The message says what to change. Shown without a code. |

## Files

| Code | Means | What to do |
|---|---|---|
| YE-FILE-01 | File too large | Send a smaller file, or split it. |
| YE-FILE-02 | File type not accepted | A photo, a PDF, a drawing, or an Excel or Word file. |
| YE-FILE-03 | File empty or could not be read | Check the file opens, then try again. |

## Busy

| Code | Means | What to do |
|---|---|---|
| YE-BUSY-01 | Too many requests at once | Wait a moment. |
| YE-BUSY-02 | Server busy or restarting | Wait a minute, reload, and check before trying again. |
| YE-BUSY-03 | Server took too long | Nothing may have been saved: reload and check. |

## Faults

| Code | Means | What to do |
|---|---|---|
| YE-SRV-01 | Server fault | Try again. If it repeats, send support the code and ref. |
| YE-NET | The app could not reach the server | Check the connection. Entries are kept on the device and sent when it returns. |
| YE-APP | The screen itself hit a problem (in the browser) | Try again or go to another screen. The ref is in the browser console with the error. |

## Where it lives

- Server: `backend/app/core/errors.py` works out the code from each error's status and message (`CODES` lists them),
  adds `code` and `ref` to every error and the `X-Error-Code` and `X-Error-Ref` headers, and logs the ref.
- App: `frontend/src/lib/errorCodes.ts` has this list, and `ApiError` (`frontend/src/lib/api.ts`) adds the code and
  ref to the message every screen shows.
- A new kind of error: add its code to all three (server `CODES` and `error_code`, app `ERROR_CODES`, this page).
  The tests check every code is reachable and explained.
