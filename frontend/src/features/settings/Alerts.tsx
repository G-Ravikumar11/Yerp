import { useEffect, useState } from 'react'
import { Button, Field, Input, Skeleton } from '@/components/ui'
import { useAction } from '@/lib/mutate'
import { saveAlertSettings, sendTestAlert, settingsKeys, useAlertSettings } from '@/api/settings'
import { Section } from './Section'

const split = (s: string) => s.split(/[,;]+/).map((x) => x.trim()).filter(Boolean)

/** Who is told by email or WhatsApp when something needs them. */
export function Alerts() {
  const q = useAlertSettings()
  const [emails, setEmails] = useState('')
  const [wa, setWa] = useState('')
  const [channels, setChannels] = useState<Record<string, string[]>>({})
  const [waId, setWaId] = useState('')
  const [waToken, setWaToken] = useState('')
  useEffect(() => {
    const d = q.data
    if (!d) return
    setEmails(d.emails.join(', '))
    setWa(d.whatsapp.join(', '))
    setChannels(d.channels)
    setWaId(d.wa_phone_id)
  }, [q.data])
  const save = useAction(
    () => saveAlertSettings({ emails: split(emails), whatsapp: split(wa), channels, wa_phone_id: waId.trim(), ...(waToken.trim() ? { wa_token: waToken.trim() } : {}) }),
    { invalidate: [settingsKeys.all], success: 'Alert settings saved.', onSuccess: () => setWaToken('') },
  )
  const test = useAction(() => sendTestAlert(), { invalidate: [['alerts']] })
  const toggle = (kind: string, ch: string, on: boolean) => setChannels((c) => ({ ...c, [kind]: on ? [...(c[kind] ?? []).filter((x) => x !== ch), ch] : (c[kind] ?? []).filter((x) => x !== ch) }))
  if (q.isPending || !q.data) return <Skeleton className="h-64 w-full" />
  const d = q.data
  return (
    <Section title="Alerts" description="Say who is told by email or WhatsApp when something happens. The bell always shows them.">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Email to" htmlFor="al-emails" hint={d.email_ready ? 'Sent from the Gmail connected to this account.' : 'Gmail is not connected, so these are not sent yet.'}><Input id="al-emails" placeholder="Master@..., accounts@..." value={emails} onChange={(e) => setEmails(e.target.value)} /></Field>
        <Field label="WhatsApp to" htmlFor="al-wa" hint={d.whatsapp_ready ? 'Sent through your WhatsApp Business number.' : 'Needs a WhatsApp Business number, below.'}><Input id="al-wa" placeholder="98480 12345, ..." value={wa} onChange={(e) => setWa(e.target.value)} /></Field>
      </div>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="text-left text-xs text-muted-foreground"><th className="py-1.5 font-medium">When</th><th className="w-20 text-center font-medium">Email</th><th className="w-24 text-center font-medium">WhatsApp</th></tr></thead>
          <tbody>
            {Object.entries(d.kinds).map(([kind, label]) => (
              <tr key={kind} className="border-t border-border">
                <td className="py-2">{label}</td>
                {(['email', 'whatsapp'] as const).map((ch) => (
                  <td key={ch} className="text-center"><input type="checkbox" aria-label={`${label} by ${ch}`} checked={(channels[kind] ?? []).includes(ch)} onChange={(e) => toggle(kind, ch, e.target.checked)} /></td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <details className="mt-4">
        <summary className="cursor-pointer text-sm">WhatsApp Business number</summary>
        <p className="mt-1 text-xs text-muted-foreground">From Meta Business, WhatsApp, API setup: the phone number ID and a permanent access token.</p>
        <div className="mt-3 grid gap-4 sm:grid-cols-2">
          <Field label="Phone number ID" htmlFor="al-waid"><Input id="al-waid" value={waId} onChange={(e) => setWaId(e.target.value)} /></Field>
          <Field label="Access token" htmlFor="al-watok"><Input id="al-watok" type="password" placeholder={d.wa_token_set ? 'Saved - type to replace' : ''} value={waToken} onChange={(e) => setWaToken(e.target.value)} /></Field>
        </div>
      </details>
      <div className="mt-4 flex gap-2"><Button loading={save.isPending} onClick={() => save.mutate()}>Save alerts</Button><Button variant="outline" loading={test.isPending} onClick={() => test.mutate()}>Send a test</Button></div>
    </Section>
  )
}
