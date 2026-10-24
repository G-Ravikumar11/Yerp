import { useEffect, useRef, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { Field, Input } from '@/components/ui'
import { api } from '@/lib/api'

/** What a sign-in sends beside the email and password once the server has asked for a check. */
export interface CaptchaValue { captcha_token: string; captcha_answer: string }

type Challenge = { provider: 'turnstile'; site_key: string } | { provider: 'builtin'; token: string; image: string } | { provider: 'off' }

declare global {
  interface Window {
    turnstile?: { render: (el: HTMLElement, o: Record<string, unknown>) => string; remove: (id: string) => void }
  }
}

let turnstileScript: Promise<void> | null = null
function loadTurnstile() {
  turnstileScript ??= new Promise((resolve, reject) => {
    const s = document.createElement('script')
    s.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit'
    s.async = true
    s.onload = () => resolve()
    s.onerror = () => { turnstileScript = null; reject(new Error('turnstile')) }
    document.head.appendChild(s)
  })
  return turnstileScript
}

/**
 * The check a sign-in page shows once the server has reason to doubt the visitor (or always, on Forgot password):
 * Cloudflare Turnstile where the company has set it up, otherwise a picture of five letters to type. Each one is good
 * for one try, so `round` is moved on after every attempt and a fresh one is drawn.
 */
export function CaptchaBox({ round, onChange }: { round: number; onChange: (v: CaptchaValue | null) => void }) {
  const [challenge, setChallenge] = useState<Challenge | null>(null)
  const [answer, setAnswer] = useState('')
  const [failed, setFailed] = useState(false)
  const [again, setAgain] = useState(0)
  const widget = useRef<HTMLDivElement>(null)
  const changed = useRef(onChange)
  useEffect(() => { changed.current = onChange }, [onChange])

  useEffect(() => {
    let live = true
    changed.current(null)
    api<Challenge>('/api/captcha', { quiet: true }).then((c) => { if (live) { setChallenge(c); setAnswer(''); setFailed(false) } }, () => live && setFailed(true))
    return () => { live = false }
  }, [round, again])

  useEffect(() => {
    if (challenge?.provider !== 'turnstile' || !widget.current) return
    let id = ''
    const el = widget.current
    loadTurnstile().then(() => {
      if (!window.turnstile || !el.isConnected) return
      id = window.turnstile.render(el, {
        sitekey: challenge.site_key,
        callback: (token: string) => changed.current({ captcha_token: token, captcha_answer: '' }),
        'expired-callback': () => changed.current(null),
      })
    }, () => setFailed(true))
    return () => { if (id) window.turnstile?.remove(id) }
  }, [challenge])

  if (failed) return <p role="alert" className="text-[13px] text-danger">The check could not be loaded. Check the connection and try again.</p>
  if (!challenge || challenge.provider === 'off') return null
  if (challenge.provider === 'turnstile') return <div ref={widget} aria-label="Check that you are a person" className="min-h-[65px]" />
  return (
    <Field label="Type the 5 characters you see" htmlFor="captcha-answer" hint="Capital or small letters both work. Hard to read? Press ↻ for new ones.">
      <div className="flex items-center gap-2">
        <img src={challenge.image} alt="Five characters to type" width={176} height={56} draggable={false}
          className="block h-14 w-44 shrink-0 select-none rounded-lg border border-border shadow-sm" />
        <button type="button" onClick={() => setAgain((n) => n + 1)} aria-label="Show different characters" title="Different characters"
          className="grid size-9 shrink-0 place-items-center rounded-full text-muted-foreground transition hover:rotate-90 hover:bg-accent hover:text-foreground">
          <RefreshCw className="size-4" />
        </button>
        <Input id="captcha-answer" autoComplete="off" autoCapitalize="characters" spellCheck={false} maxLength={5} placeholder="•••••"
          className="h-14 min-w-0 flex-1 text-center font-mono text-lg font-semibold uppercase tracking-[0.35em]"
          value={answer} onChange={(e) => { setAnswer(e.target.value); changed.current(e.target.value.trim() ? { captcha_token: challenge.token, captcha_answer: e.target.value.trim() } : null) }} />
      </div>
    </Field>
  )
}
