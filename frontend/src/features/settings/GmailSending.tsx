import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Mail } from 'lucide-react'
import { Badge, Button, Field, Input, Skeleton } from '@/components/ui'
import { get, post } from '@/lib/api'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { Section } from './Section'

interface GmailStatus { gmail_ready: boolean; gmail_authorized_email: string | null }
const KEY = ['settings', 'gmail'] as const

const NOTICE: Record<string, string> = {
  connected: 'Gmail is connected. The company’s email now goes out from it.',
  master_only: 'Only the Master can connect the company’s Gmail.',
}

/** The Gmail the company's email goes out from: invoices, alerts, reminders and password resets. Separate from signing in -
 * nobody signs in with it, and people receive these emails at any address (Yahoo, Gmail, Outlook...). The key to the
 * mailbox stays on the server. */
export function GmailSending() {
  const { isOwner } = useSession()
  const q = useQuery({ queryKey: KEY, queryFn: () => get<GmailStatus>('/api/gmail/status'), enabled: isOwner })
  const [to, setTo] = useState('')
  const notice = NOTICE[new URLSearchParams(window.location.search).get('gmail') ?? '']
  const disconnect = useAction(() => post<{ message?: string }>('/api/gmail/disconnect'), { invalidate: [[...KEY], ['settings']], success: 'Gmail disconnected.' })
  const test = useAction(() => post<{ message?: string }>('/api/gmail/test', { to: to.trim() }), { success: (r) => r.message ?? 'Test email sent.' })
  if (!isOwner) return null
  const connect = () => window.location.assign('/api/auth/login?portal=settings')
  return (
    <Section title="Company email (Gmail)" description="The Gmail account the company's emails are sent from - invoices, alerts, reminders and password resets. People receive them at whatever address they have.">
      {notice && <p role="status" className="mb-3 rounded-lg border border-border bg-muted/50 px-3 py-2 text-sm">{notice}</p>}
      {q.isPending || !q.data ? <Skeleton className="h-16 w-full" /> : (
        <div className="grid gap-4">
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <Mail className="size-4 text-muted-foreground" />
            {q.data.gmail_ready
              ? <><Badge tone="success" dot>Connected</Badge><span>{q.data.gmail_authorized_email ? `Sending from ${q.data.gmail_authorized_email}` : 'Sending from the connected Gmail'}</span></>
              : <><Badge tone="warning" dot>Not connected</Badge><span className="text-muted-foreground">Emails are not sent until a Gmail account is connected.</span></>}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant={q.data.gmail_ready ? 'outline' : 'primary'} onClick={connect}>{q.data.gmail_ready ? 'Connect a different Gmail' : 'Connect Gmail'}</Button>
            {q.data.gmail_ready && <Button variant="outline" loading={disconnect.isPending} onClick={() => disconnect.mutate()}>Disconnect</Button>}
          </div>
          {q.data.gmail_ready && (
            <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (to.trim()) test.mutate() }}>
              <Field label="Send a test email to" htmlFor="gm-test" className="w-72"><Input id="gm-test" type="email" placeholder="someone@yahoo.com" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
              <Button type="submit" variant="outline" loading={test.isPending} disabled={!to.trim()}>Send test</Button>
            </form>
          )}
        </div>
      )}
    </Section>
  )
}
