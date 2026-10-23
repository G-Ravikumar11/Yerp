import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button } from '@/components/ui'
import { ApiError, post } from '@/lib/api'
import { queryClient } from '@/lib/query'
import { useSession } from '@/lib/session'
import { Notice } from '@/features/auth/AuthLayout'
import { PASSWORD_RULE, PasswordField, passwordProblem } from '@/features/auth/PasswordField'

type Errors = Partial<Record<'current' | 'next' | 'confirm', string>>

/** A member of staff changes their own password. The Master gave them the first one, so until they have chosen their own this is the only page they can open. */
export default function ChangePasswordPage() {
  const { user, isLoading } = useSession()
  const nav = useNavigate()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [errors, setErrors] = useState<Errors>({})
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)
  const first = !!user?.mustChangePassword

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (busy) return
    const found: Errors = {}
    if (!current) found.current = 'Enter your current password.'
    const weak = passwordProblem(next)
    if (weak) found.next = weak
    else if (next === current) found.next = 'Choose a password different from the current one.'
    if (confirm !== next) found.confirm = 'Those two do not match.'
    setErrors(found)
    setError('')
    if (Object.keys(found).length) return
    setBusy(true)
    try {
      await post('/api/auth/change-password', { current_password: current, new_password: next, confirm_password: confirm })
      setDone(true)
      setCurrent(''); setNext(''); setConfirm('')
      await queryClient.invalidateQueries({ queryKey: ['session'] })
      if (first) nav('/')
    } catch (err) {
      if (!(err instanceof ApiError)) setError('Could not reach the server. Check the connection and try again.')
      else if (err.status === 401) setError('Your session has ended. Sign in again.')
      else if (/current password/i.test(err.message)) setErrors({ current: err.message })
      else if (err.status === 400) setErrors({ next: err.message })
      else setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (!isLoading && user?.type === 'owner')
    return <><PageHeader eyebrow="Account" title="Change password" /><p className="max-w-xl text-sm text-muted-foreground">The Master&apos;s password is changed from the sign-in page, with &ldquo;Forgot password?&rdquo;.</p></>

  return (
    <>
      <PageHeader eyebrow="Account" title="Change password" description={first ? 'Your Master gave you a first password. Choose your own to continue.' : 'Choose a new password. You will use it the next time you sign in.'} />
      <form onSubmit={submit} noValidate className="grid max-w-md gap-4">
        {first && <Notice tone="error">Choose a new password before you carry on. Nothing else opens until you do.</Notice>}
        {error && <Notice tone="error">{error}</Notice>}
        {done && !first && <Notice tone="success">Your password has been changed. Use the new one next time you sign in.</Notice>}
        <PasswordField id="cp-current" label="Current password" value={current} onChange={setCurrent} error={errors.current} autoComplete="current-password" />
        <PasswordField id="cp-new" label="New password" value={next} onChange={setNext} error={errors.next} hint={PASSWORD_RULE} />
        <PasswordField id="cp-confirm" label="Confirm new password" value={confirm} onChange={setConfirm} error={errors.confirm} />
        <div><Button type="submit" loading={busy}>Change password</Button></div>
      </form>
    </>
  )
}
