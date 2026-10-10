import { useEffect, useState } from 'react'
import { Button, Field, Input } from '@/components/ui'
import { api, ApiError } from '@/lib/api'
import { AuthLayout, Notice } from './AuthLayout'

/** The platform operator's own door, separate from the companies' sign-in. */
export default function SuperadminLoginPage() {
  const [error, setError] = useState(new URLSearchParams(window.location.search).get('error') === 'not_admin' ? 'This Google account is not registered as a super admin.' : '')
  const [identifier, setIdentifier] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    void fetch('/api/superadmin/me').then((r) => r.ok && window.location.assign('/next/superadmin')).catch(() => undefined)
  }, [])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!identifier.trim() || !password) return setError('Enter your email and password.')
    setBusy(true)
    setError('')
    try {
      await api('/api/superadmin/login', { method: 'POST', body: { identifier: identifier.trim(), password }, quiet: true })
      window.location.assign('/next/superadmin')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Network error. Try again.')
      setBusy(false)
    }
  }

  return (
    <AuthLayout title="Super Admin" subtitle="Y ERP platform" mark="SA">
      {error && <Notice tone="error">{error}</Notice>}
      <form onSubmit={submit} className="grid gap-4">
        <Field label="Email or username" htmlFor="login-id"><Input id="login-id" autoComplete="username" placeholder="admin@example.com" value={identifier} onChange={(e) => setIdentifier(e.target.value)} /></Field>
        <Field label="Password" htmlFor="login-password"><Input id="login-password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
        <Button type="submit" loading={busy}>Sign in</Button>
      </form>
      <p className="mt-5 text-center text-sm"><a className="text-muted-foreground hover:text-primary" href="/">&larr; Back to home</a></p>
    </AuthLayout>
  )
}
