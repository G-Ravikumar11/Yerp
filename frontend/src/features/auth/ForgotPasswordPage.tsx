import { useState } from 'react'
import { Button, Field, Input } from '@/components/ui'
import { api, ApiError } from '@/lib/api'
import { AuthLayout, Notice } from './AuthLayout'
import { appUrl } from '@/lib/paths'

/** Asks for the address and says the same thing whether or not an account has it, so the page cannot be used to find out who banks here. */
export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [error, setError] = useState('')
  const [sent, setSent] = useState(false)
  const [busy, setBusy] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (busy || !email.trim()) return
    setBusy(true)
    setError('')
    try {
      // One door for owners and staff, as on the sign-in page: the server knows which of the two holds the address.
      // Both always answer alike, so asking both reveals nothing; a throttled or unreachable one is the only failure.
      const body = { email: email.trim() }
      await Promise.all(['/api/client/forgot-password', '/api/employee/forgot-password'].map((url) => api(url, { method: 'POST', body, quiet: true })))
      setSent(true)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not reach the server. Check the connection and try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout title="Forgot your password?" subtitle="Enter your email and we will send you a link to choose a new one.">
      {sent ? (
        <div className="grid gap-3 text-center">
          <Notice tone="success">If an account exists with this email, you will receive password reset instructions.</Notice>
          <p className="text-sm text-muted-foreground">The link works once and expires in an hour.</p>
        </div>
      ) : (
        <form onSubmit={submit} className="grid gap-4">
          {error && <Notice tone="error">{error}</Notice>}
          <Field label="Email address" htmlFor="email"><Input id="email" type="email" autoComplete="username" autoFocus required placeholder="you@company.com" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
          <Button type="submit" loading={busy} className="w-full">Send reset link</Button>
        </form>
      )}
      <p className="mt-5 text-center text-sm"><a className="text-muted-foreground hover:text-primary" href={appUrl('login')}>&larr; Back to sign in</a></p>
    </AuthLayout>
  )
}
