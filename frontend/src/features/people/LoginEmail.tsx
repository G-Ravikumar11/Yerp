import { Button } from '@/components/ui'
import { sendLoginEmail, showEmployeeChange, type EmployeeDetail } from '@/api/people'
import { useQueryClient } from '@tanstack/react-query'
import { useAction } from '@/lib/mutate'
import { toast } from '@/stores/toast'

const STATUS: Record<string, string> = { sending: 'Sending…', sent: 'Sent', failed: 'Could not be sent' }

/** How their login email went, and sending it again. Only ever to the organization email; the password is not in a resend. */
export function LoginEmail({ e }: { e: EmployeeDetail }) {
  const qc = useQueryClient()
  const status = e.credentials_email_status ?? ''
  const send = useAction(() => sendLoginEmail(e.id), {
    success: false,
    onSuccess: (r) => {
      showEmployeeChange(qc, { patch: { id: e.id, credentials_email_status: r.credentials_email_status, credentials_email_at: r.credentials_email_at } })
      if (r.ok) toast.success(r.message)
      else toast.error(r.message)
    },
  })
  return (
    <section aria-label="Login email" className="mt-6 border-t border-border pt-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h4 className="text-sm font-semibold">Login email</h4>
          <p className="mt-1 text-[13px] text-muted-foreground">
            {e.org_email ? `${STATUS[status] ?? 'Not sent yet'}${status && status !== 'sending' && e.credentials_email_at ? ` - ${e.credentials_email_at}` : ''}. A resend goes to ${e.org_email} with a link to set a password.` : 'Add an organization email to send it - it goes only there.'}
          </p>
        </div>
        <Button variant="outline" size="sm" loading={send.isPending} disabled={!e.org_email} onClick={() => send.mutate()}>{status ? 'Resend login email' : 'Send login email'}</Button>
      </div>
    </section>
  )
}
