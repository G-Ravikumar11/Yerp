import { useEffect, useState } from 'react'
import { Button, Field, Input } from '@/components/ui'
import { api, ApiError } from '@/lib/api'
import { AuthLayout, Notice } from './AuthLayout'
import { appUrl } from '@/lib/paths'

type Stage = 'checking' | 'dead' | 'form' | 'done'

/** The page a "reset your password" email opens. The link is checked before the form shows, so nobody types a password into a dead link. */
export default function ResetPasswordPage() {
  const token = new URLSearchParams(window.location.search).get('token') || ''
  const [stage, setStage] = useState<Stage>('checking')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!token) return setStage('dead')
    api<{ valid?: boolean }>('/api/client/reset-password?token=' + encodeURIComponent(token), { quiet: true })
      .then((d) => setStage(d?.valid ? 'form' : 'dead'))
      .catch(() => setStage('dead'))
  }, [token])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (password !== confirm) return setError('Those two do not match.')
    setBusy(true)
    try {
      await api('/api/client/reset-password', { method: 'POST', body: { token, password }, quiet: true })
      setStage('done')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong. Try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout title="Choose a new password">
      {stage === 'checking' && <p className="py-6 text-center text-sm text-muted-foreground">Checking your link...</p>}
      {stage === 'dead' && (
        <div className="grid gap-3 text-center">
          <Notice tone="error">That reset link is invalid or has expired.</Notice>
          <p className="text-sm text-muted-foreground">Links work once and last an hour.</p>
          <div><Button asChild><a href={appUrl('login')}>Back to sign in</a></Button></div>
        </div>
      )}
      {stage === 'form' && (
        <form onSubmit={submit} className="grid gap-4" autoComplete="off">
          <Field label="New password" htmlFor="password"><Input id="password" type="password" required autoComplete="new-password" placeholder="At least 8 characters" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
          <Field label="Confirm password" htmlFor="confirm" hint="Needs at least 8 characters, one capital letter and one number."><Input id="confirm" type="password" required autoComplete="new-password" placeholder="Type it again" value={confirm} onChange={(e) => setConfirm(e.target.value)} /></Field>
          {error && <Notice tone="error">{error}</Notice>}
          <Button type="submit" loading={busy}>Set new password</Button>
        </form>
      )}
      {stage === 'done' && (
        <div className="grid gap-3 text-center">
          <Notice tone="success">Password updated.</Notice>
          <div><Button asChild><a href={appUrl('login')}>Sign in</a></Button></div>
        </div>
      )}
    </AuthLayout>
  )
}
