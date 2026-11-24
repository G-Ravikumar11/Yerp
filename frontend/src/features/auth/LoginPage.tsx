import { forgetLocalData } from '@/lib/query'
import { useEffect, useState } from 'react'
import { Button, Field, Input } from '@/components/ui'
import { Capacitor, registerPlugin } from '@capacitor/core'
import { Eye, EyeOff } from 'lucide-react'
import { api, ApiError } from '@/lib/api'
import { Notice, YahooMark, nextTarget } from './AuthLayout'
import { LoginScene } from './LoginScene'
import { codeLine } from '@/lib/errorCodes'
import { markScreensGood } from '@/lib/mobile'
import { appUrl } from '@/lib/paths'
import { CaptchaBox, type CaptchaValue } from './CaptchaBox'

const ERRORS: Record<string, string> = {
  auth_failed: 'Authentication failed. Please try again.',
  account_disabled: 'That account has been disabled.',
  google_retired: 'Sign in with Google is no longer offered. Continue with Yahoo, or sign in with your email and password.',
  yahoo_failed: 'Yahoo sign-in did not complete. Try again.',
  yahoo_no_email: 'Yahoo did not share an email address.',
  yahoo_unverified: 'That Yahoo address is not verified.',
  yahoo_unknown: 'No account here uses that Yahoo address. Ask whoever set up your access.',
  yahoo_unconfigured: 'Yahoo sign-in is not set up on this server yet.',
  yahoo_denied: 'Yahoo sign-in was cancelled. Try again, or sign in with your email and password.',
  yahoo_state: 'That Yahoo sign-in did not start here, so it was stopped for your safety. Please try again.',
  yahoo_expired: 'That Yahoo sign-in took too long or was used already. Please try again.',
  gmail_sign_in_first: 'Sign in first, then connect Gmail from inside the app.',
}

const go = (to: string) => window.location.assign(to)
// A fresh sign-in: whatever the last person left in this phone's saved copy (who is signed in, their screens) is dropped first,
// so the next screens are read for the person who just signed in and never drawn from somebody else's.
const goSignedIn = (to: string) => { void forgetLocalData().catch(() => undefined).finally(() => go(to)) }
// Inside the native app there is no website to go back to, and Yahoo's sign-in page cannot hand its cookie back.
const native = Capacitor.isNativePlatform()

/** One door for the whole business: the server decides whether the address is the account holder's or a member of staff's. */
export default function LoginPage() {
  const params = new URLSearchParams(window.location.search)
  const code = params.get('error')
  const [error, setError] = useState(code ? (ERRORS[code] ?? 'Something went wrong. Please try again.') : '')
  const [company, setCompany] = useState('')
  // The Yalavarti logo, always: the sign-in page shows the company's own artwork, not the logo uploaded in Settings.
  const logo = `${import.meta.env.BASE_URL}brand/yalavarti-logo.png`
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  // A phone stays signed in unless the person unticks this; the website asks every time.
  const [rememberMe, setRememberMe] = useState(native)
  const [busy, setBusy] = useState(false)
  // The check (CAPTCHA), once the server has asked for one; a new one is drawn after every try.
  const [askCheck, setAskCheck] = useState(false)
  const [check, setCheck] = useState<CaptchaValue | null>(null)
  const [round, setRound] = useState(0)

  useEffect(() => {
    api<{ company_name?: string }>('/api/public/brand', { quiet: true }).then((b) => { if (b?.company_name) setCompany(b.company_name) }).catch(() => undefined)
    if (params.get('signedout')) {
      // Arrived from Sign out: end whatever sign-in this browser still holds, and show the form.
      for (const u of ['/api/client/logout', '/api/employee/auth/logout', '/api/portal/logout']) void api(u, { method: 'POST', quiet: true }).catch(() => undefined)
      markScreensGood()
      return
    }
    // Already signed in: go straight on. All three kinds of account are asked at once, so a signed-in person leaves
    // after one round trip; the first that answers yes, in this order, says where to.
    void (async () => {
      const doors: [string, string][] = [['/api/client/me', nextTarget(appUrl())], ['/api/employee/auth/me', nextTarget(appUrl())], ['/api/superadmin/me', appUrl('superadmin')]]
      // Through api(): in the native app a bare '/api/...' is answered by the app's own files, not the server.
      const answers = await Promise.all(doors.map(([url]) => api(url, { quiet: true }).then(() => true, () => false)))
      const door = answers.indexOf(true)
      if (door >= 0) go(doors[door][1])
      // Nobody is signed in on this phone: the form is as far as these screens can be shown to work.
      else markScreensGood()
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // The phone's keyboard is drawn over the page without shrinking it. The native Keyboard plugin says how tall it is: that much
  // room is added under the form so the page can scroll, and the field being typed in (with the button below it) is brought into view.
  useEffect(() => {
    const root = document.documentElement
    const keepInView = () => {
      const el = document.activeElement
      if (el instanceof HTMLInputElement) {
        // Placed in the upper part of what the keyboard leaves visible, so the field after it and the button are also in sight.
        window.setTimeout(() => {
          const kb = parseFloat(root.style.getPropertyValue('--kb')) || 0
          window.scrollBy({ top: el.getBoundingClientRect().top - (window.innerHeight - kb) * 0.25, behavior: 'smooth' })
        }, 120)
      }
    }
    const handles: Promise<{ remove: () => Promise<void> }>[] = []
    if (native) {
      const kb = registerPlugin<{ addListener: (event: string, fn: (e: { keyboardHeight?: number }) => void) => Promise<{ remove: () => Promise<void> }> }>('Keyboard')
      handles.push(kb.addListener('keyboardWillShow', (e) => { root.style.setProperty('--kb', `${e.keyboardHeight ?? 0}px`); keepInView() }))
      handles.push(kb.addListener('keyboardWillHide', () => root.style.removeProperty('--kb')))
    }
    document.addEventListener('focusin', keepInView)
    return () => {
      document.removeEventListener('focusin', keepInView)
      root.style.removeProperty('--kb')
      handles.forEach((h) => void h.then((x) => x.remove()).catch(() => undefined))
    }
  }, [])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (busy) return
    if (!email.trim() || !password) return setError('Enter your email or employee ID, and your password.')
    if (askCheck && !check) return setError('Complete the check below, then sign in.')
    setBusy(true)
    setError('')
    try {
      // A refused password is an answer; no answer at all (no signal, server down) is a different problem,
      // and so is a server that answers with something other than "no such account".
      let unreachable = false
      let other: ApiError | null = null
      const none = (e: unknown) => {
        if (!(e instanceof ApiError)) unreachable = true
        else if (e.status !== 401 && !other) other = e
        return null
      }
      // The check, once the server has asked for it, goes with both doors: one solved check covers one sign-in.
      const extra = check ?? {}
      // The Master and their colleagues sign in by email; an employee ID (no @) is staff's alone, so it never goes to their door.
      const owner = email.includes('@')
        ? await api<{ is_onboarded?: boolean }>('/api/client/login', { method: 'POST', body: { email: email.trim(), password, rememberMe, channel: native ? 'app' : 'web', ...extra }, quiet: true }).catch(none)
        : null
      if (owner) return goSignedIn(owner.is_onboarded === false ? nextTarget(appUrl('onboard')) : nextTarget(appUrl()))
      const staff = await api('/api/employee/auth/login', { method: 'POST', body: { email: email.trim(), password, rememberMe, channel: native ? 'app' : 'web', device_info: navigator.userAgent.slice(0, 200), ...extra }, quiet: true }).catch(none)
      if (staff) return goSignedIn(nextTarget(appUrl()))
      const refusal = other as ApiError | null
      // Too many wrong tries from here, or against this account: from now on every try needs the check.
      if (refusal?.status === 428 || askCheck) {
        setAskCheck(true)
        setRound((n) => n + 1)
      }
      setError(
        unreachable ? `Could not reach the server. Check the connection and try again. (${codeLine('YE-NET')})`
          : refusal && refusal.status >= 500 ? `The server had a problem. Please try again in a moment. (${codeLine(refusal.code, refusal.ref)})`
          : refusal ? refusal.message
          : `That email or employee ID and password did not match an account. (${codeLine('YE-AUTH-01')})`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <LoginScene title="Y ERP" subtitle="Sign in to your account" logo={logo} logoAlt={company || 'Y ERP'}>
      {params.get('reset') && !error && <Notice tone="success">Your password has been updated. Sign in with the new one.</Notice>}
      {error && <Notice tone="error">{error}</Notice>}
      <form onSubmit={submit} className="grid gap-5">
        <Field label="Email or employee ID" htmlFor="email"><Input id="email" type="text" inputMode="email" autoCapitalize="none" autoCorrect="off" spellCheck={false} autoComplete="username" autoFocus required placeholder="you@company.com or EMP-0002" className="ls-input" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <Field label="Password" htmlFor="password"><Input id="password" type={showPassword ? 'text' : 'password'} autoComplete="current-password" required placeholder="Enter your password" className="ls-input pr-12" value={password} onChange={(e) => setPassword(e.target.value)}
          trailing={<button type="button" onClick={() => setShowPassword((v) => !v)} aria-label={showPassword ? 'Hide password' : 'Show password'} aria-pressed={showPassword} className="grid size-7 place-items-center rounded-md text-white/70 hover:text-white focus-visible:outline-2 focus-visible:outline-primary">{showPassword ? <Eye className="size-[18px]" /> : <EyeOff className="size-[18px]" />}</button>} /></Field>
        {askCheck && <CaptchaBox round={round} onChange={setCheck} />}
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 text-[15px]">
          <label htmlFor="rememberMe" className="flex w-fit cursor-pointer items-center gap-2.5 font-normal text-foreground">
            <input id="rememberMe" type="checkbox" className="size-[18px] cursor-pointer rounded-md border-border accent-primary" checked={rememberMe} onChange={(e) => setRememberMe(e.target.checked)} />
            Remember me
          </label>
          <a href={appUrl('forgot-password')} className="font-medium text-foreground hover:text-primary">Forgot password?</a>
        </div>
        <Button type="submit" loading={busy} className="h-12 w-full rounded-[0.6rem] text-[15px]">Sign in</Button>
      </form>
      {/* Always offered on the website. A server without Yahoo keys answers a click with "not set up yet" (yahoo_unconfigured). */}
      {!native && (
        <>
          <div className="my-5 flex items-center gap-4 text-sm uppercase text-muted-foreground"><span className="h-px flex-1 bg-[#cfc9bc]" />or<span className="h-px flex-1 bg-[#cfc9bc]" /></div>
          <div className="grid gap-2">
            <Button type="button" variant="outline" className="h-12 w-full items-center justify-center gap-3 rounded-[0.6rem] [&>svg]:!size-[22px] border-white/10 bg-[#1f2633] text-[15px] text-white hover:border-white/20 hover:bg-[#283041]" onClick={() => go('/api/auth/yahoo/start?next=' + encodeURIComponent(nextTarget(appUrl())))}><YahooMark /> Continue with Yahoo</Button>
          </div>
        </>
      )}
      {!native && <p className="mt-6 text-center text-[15px]"><a className="text-foreground hover:text-primary" href="/">&larr; Back to website</a></p>}
      {/* The legal pages belong to the ERP, so they are linked from its door, not from the company website. */}
      <nav aria-label="Legal" className="mt-4 flex justify-center gap-5 text-sm text-muted-foreground">
        <a className="hover:text-foreground" href={appUrl('terms')}>Terms of Service</a>
        <a className="hover:text-foreground" href={appUrl('privacy')}>Privacy Policy</a>
      </nav>
    </LoginScene>
  )
}
