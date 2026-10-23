import { useState } from 'react'
import { Button, Modal } from '@/components/ui'
import { useAction } from '@/lib/mutate'
import { PASSWORD_RULE, PasswordField, checkNewPassword } from '@/features/auth/PasswordField'

/** The Master gives somebody a password to sign in with. Nothing is emailed: the Master hands it over. */
export function SetPasswordModal({ who, email, hasPassword, save, invalidate, onClose }: {
  who: string; email: string; hasPassword: boolean; save: (password: string) => Promise<{ message?: string }>; invalidate: (readonly unknown[])[]; onClose: () => void
}) {
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [tried, setTried] = useState(false)
  const check = checkNewPassword(password, confirm)
  const run = useAction(() => save(password), { invalidate, success: () => `${who} can now sign in with ${email} and the password you gave.`, onSuccess: onClose })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={hasPassword ? `New password for ${who}` : `Give ${who} a password`}
      description={`They sign in with ${email || 'their email'} and this password. Tell it to them yourself - nothing is emailed.${hasPassword ? ' Their old password stops working.' : ''}`}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button loading={run.isPending} onClick={() => { setTried(true); if (check.ok) run.mutate() }}>Set password</Button></>}>
      <div className="grid gap-4">
        <PasswordField id="sp-pass" label="Password" value={password} onChange={setPassword} error={tried || password ? check.pass || undefined : undefined} hint={PASSWORD_RULE} />
        <PasswordField id="sp-pass2" label="Confirm password" value={confirm} onChange={setConfirm} error={tried || confirm ? check.again || undefined : undefined} placeholder="Type it again" />
        {run.error && <p role="alert" className="text-[13px] text-danger">{run.error.message}</p>}
      </div>
    </Modal>
  )
}
