/**
 * Error codes. Every failure the app reports carries one, so a person can say "it showed YE-SRV-01, ref 7F3A9C21"
 * and support knows exactly what happened: the code says what kind of failure, the ref finds this one failure in
 * the server log (it is written there with the cause). The server sends both with every error; failures that never
 * reached the server get their code here. The same list is in docs/error-codes.md.
 */
export const ERROR_CODES: Record<string, { title: string; help: string }> = {
  // Signing in
  'YE-AUTH-01': { title: 'Wrong email or password', help: 'Check both and try again. Use "Forgot password" if needed.' },
  'YE-AUTH-02': { title: 'Account disabled', help: 'Ask the Master or your administrator to enable it.' },
  'YE-AUTH-03': { title: 'Too many sign-in attempts', help: 'Wait a few minutes before trying again.' },
  'YE-AUTH-04': { title: 'Signed out', help: 'The session ended. Sign in again.' },
  'YE-AUTH-05': { title: 'Access removed', help: 'Your access to this company was taken away. Ask the Master.' },
  'YE-AUTH-06': { title: 'Password not set yet', help: 'Ask your Master to give you a password. They set it from your record.' },
  'YE-AUTH-07': { title: 'Reset link invalid or expired', help: 'Ask for a new reset link.' },
  'YE-AUTH-08': { title: 'Email already registered', help: 'Sign in with it, or use "Forgot password".' },
  'YE-AUTH-09': { title: 'Check that you are a person', help: 'Type the letters shown (or tick the box) and try again. It is asked for after several wrong tries.' },
  'YE-AUTH-10': { title: 'Account locked for a while', help: 'Too many wrong passwords. Wait 15 minutes, or use "Forgot password". The Master has been told.' },
  // Access
  'YE-ACCESS-01': { title: 'Not allowed', help: 'Your access does not include this. Ask the Master to grant it.' },
  'YE-ACCESS-02': { title: 'File link expired', help: 'Open the file again from the app.' },
  // Records
  'YE-DATA-01': { title: 'Not found', help: 'It may have been deleted, or the link is old.' },
  'YE-DATA-02': { title: 'Already exists', help: 'Someone may have entered or changed it. Reload and check.' },
  'YE-DATA-03': { title: 'Locked', help: 'It is signed off or issued, so it cannot change.' },
  'YE-DATA-04': { title: 'Something entered is not right', help: 'The message says what to change.' },
  // Files
  'YE-FILE-01': { title: 'File too large', help: 'Send a smaller file, or split it into parts.' },
  'YE-FILE-02': { title: 'File type not accepted', help: 'Use a photo, a PDF, a drawing, or an Excel or Word file.' },
  'YE-FILE-03': { title: 'File empty or unreadable', help: 'Check the file opens on your device, then try again.' },
  // Busy
  'YE-BUSY-01': { title: 'Too many requests at once', help: 'Wait a moment and try again.' },
  'YE-BUSY-02': { title: 'Server busy or restarting', help: 'Wait a minute, reload, and check before trying again.' },
  'YE-BUSY-03': { title: 'Server took too long', help: 'Nothing may have been saved: reload and check before trying again.' },
  // Faults
  'YE-SRV-01': { title: 'Server fault', help: 'Try again. If it keeps happening, send support the code and ref.' },
  'YE-NET': { title: 'Could not reach the server', help: 'Check the connection. Anything entered is kept on this device and sent when it returns.' },
  'YE-APP': { title: 'This screen hit a problem', help: 'Try again, or go to another screen. Nothing entered elsewhere was lost.' },
}

/**
 * The code for an answer that came without one (a proxy's error page, say): from the status alone. YE-NET when no
 * answer came at all. The server sends a more exact code whenever it answers itself.
 */
export function codeFor(status: number): string {
  if (status <= 0) return 'YE-NET'
  const byStatus: Record<number, string> = {
    401: 'YE-AUTH-04', 403: 'YE-ACCESS-01', 404: 'YE-DATA-01', 409: 'YE-DATA-02', 413: 'YE-FILE-01',
    429: 'YE-BUSY-01', 502: 'YE-BUSY-02', 503: 'YE-BUSY-02', 504: 'YE-BUSY-03',
  }
  return byStatus[status] ?? (status >= 500 ? 'YE-SRV-01' : 'YE-DATA-04')
}

/** A reference for a failure that never reached the server: 8 characters, A-F and 0-9, like the server's. */
export function newRef() {
  const bytes = new Uint8Array(4)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('').toUpperCase()
}

/** "Error YE-SRV-01 · ref 7F3A9C21", the line shown under or after a message. */
export const codeLine = (code: string, ref?: string) => `Error ${code}${ref ? ` · ref ${ref}` : ''}`

/**
 * Whether a message shows its code. "Something entered is not right" (YE-DATA-04) is the person's to fix and the
 * message already says how, so it shows its words alone; every other code - a wrong password, a file too large, a
 * busy server, a fault - shows its code and ref after the message.
 */
export const showsCode = (code: string) => code !== 'YE-DATA-04'
