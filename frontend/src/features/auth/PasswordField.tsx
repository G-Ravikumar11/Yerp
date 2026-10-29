import { useState } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import { Field, Input } from '@/components/ui'

/** The rule the server enforces, said once so every form shows the same words. */
export const PASSWORD_RULE = 'At least 8 characters, with one capital letter and one number.'

/** The first thing wrong with a new password, or '' - the server checks again, this only saves a round trip. */
export const passwordProblem = (p: string) => (p.length < 8 || !/[A-Z]/.test(p) || !/\d/.test(p) ? PASSWORD_RULE : '')

/** A password box with the show/hide eye, and the message for it beside it. "new-password" by default: these boxes set
    somebody's password, and with "off" (which Chrome ignores on a password box) the browser filled in the signed-in
    Master's own saved login - their email and password - on the form for a new employee. */
export function PasswordField({ id, label, value, onChange, error, hint, autoComplete = 'new-password', placeholder }: {
  id: string; label: string; value: string; onChange: (v: string) => void; error?: string; hint?: string; autoComplete?: string; placeholder?: string
}) {
  const [show, setShow] = useState(false)
  return (
    <Field label={label} htmlFor={id} error={error} hint={error ? undefined : hint}>
      <Input id={id} type={show ? 'text' : 'password'} autoComplete={autoComplete} placeholder={placeholder} value={value} onChange={(e) => onChange(e.target.value)} aria-invalid={!!error}
        trailing={<button type="button" onClick={() => setShow((v) => !v)} aria-label={show ? 'Hide password' : 'Show password'} aria-pressed={show} className="grid size-6 place-items-center rounded-md text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-primary">{show ? <Eye className="size-4" /> : <EyeOff className="size-4" />}</button>} />
    </Field>
  )
}

/** A password and the same again: what is wrong with each, so a form can show it beside the box and hold the button. */
export function checkNewPassword(password: string, confirm: string) {
  const pass = passwordProblem(password)
  const again = confirm && confirm !== password ? 'Those two do not match.' : !confirm ? 'Type it again.' : ''
  return { pass, again, ok: !pass && !again }
}
