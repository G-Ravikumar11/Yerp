import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Download, KeyRound, RefreshCw } from 'lucide-react'
import { Badge, Button, Card, ConfirmDialog, Input, Modal, Select, Stat, StatGrid } from '@/components/ui'
import { apiUrl, get, post, put } from '@/lib/api'
import { toast } from '@/stores/toast'
import { projectLabel, useProjects } from '@/api/projects'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate } from '@/lib/format'

interface Device { id: number; device_code: string; name: string; job_id: number | null; site: string; last_punch_at: string }
interface Person { id: number; name: string; employee_code: string; biometric_id: string }
interface Status {
  connected: boolean
  last_sync: string
  minutes_since_sync: number | null
  agent: string
  punches_today: number
  people_today: number
  devices: Device[]
  unmatched: { biometric_id: string; punches: number; last: string; name: string; suggestion: { id: number; name: string } | null }[]
  employees: Person[]
}

const KEY = ['attendance', 'biometric']
const INVALIDATE = [KEY, ['attendance']]

/**
 * Attendance from the biometric machines. A small program in the office reads the attendance system (eSSL
 * eTimeTrackLite) and sends each punch here; this tab shows whether it is arriving, which machine stands at which site,
 * and the punches that belong to nobody yet because a person's number on the machine is not their employee code.
 */
export function BiometricTab() {
  const { can, user } = useSession()
  const master = user?.type === 'owner' && user.teamRole === 'owner'       // only the Master makes the key
  const q = useQuery({ queryKey: KEY, queryFn: () => get<Status>('/api/biometric/status'), refetchInterval: 60_000 })
  const projects = useProjects()
  const [key, setKey] = useState('')
  const [asking, setAsking] = useState(false)
  const make = useAction(() => post<{ key: string }>('/api/biometric/key'), { invalidate: [KEY], success: false, onSuccess: (r) => { setKey(r.key); setAsking(false) } })
  const [downloading, setDownloading] = useState(false)
  const [confirmPackage, setConfirmPackage] = useState(false)
  // The set-up package: the office program with this company's address and a new key already in it.
  const downloadPackage = async () => {
    setDownloading(true)
    try {
      const res = await fetch(apiUrl('/api/biometric/setup-package'), { method: 'POST', credentials: 'include' })
      if (!res.ok) throw new Error(res.status === 403 ? 'Only the Master can make the set-up package.' : 'Could not make the package. Try again.')
      const blob = await res.blob()
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = 'YERP-biometric-setup.zip'
      document.body.appendChild(a)
      a.click()
      a.remove()
      setTimeout(() => URL.revokeObjectURL(a.href), 10_000)
      toast.success('Downloaded. Unzip it on the office computer and double-click SETUP.bat.')
      void q.refetch()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not make the package.')
    } finally {
      setDownloading(false)
      setConfirmPackage(false)
    }
  }
  const match = useAction((v: { id: number; number: string }) => put<{ message: string }>(`/api/biometric/employees/${v.id}`, { biometric_id: v.number }), { invalidate: INVALIDATE })
  const rematch = useAction(() => post<{ message: string }>('/api/biometric/rematch'), { invalidate: INVALIDATE })
  const s = q.data
  const manage = can('people.manage')
  const late = s?.minutes_since_sync ?? null
  const sites = (projects.data ?? []).map((p) => ({ value: p.id, label: projectLabel(p) }))

  return (
    <>
      <StatGrid className="xl:grid-cols-4">
        <Stat label="Sync program" loading={q.isPending}
          value={!s?.connected ? 'Not set up' : late === null ? 'No punches yet' : late <= 10 ? 'Working' : `Silent ${late >= 120 ? `${Math.round(late / 60)} h` : `${late} min`}`}
          tone={!s?.connected ? undefined : late !== null && late <= 10 ? 'success' : 'warning'}
          sub={s?.last_sync ? `Last heard ${formatDate(s.last_sync)} ${s.last_sync.slice(11, 16)}` : 'Make a key and start the program in the office'} />
        <Stat label="Punches today" value={String(s?.punches_today ?? 0)} loading={q.isPending} />
        <Stat label="People in by machine today" value={String(s?.people_today ?? 0)} loading={q.isPending} />
        <Stat label="Punches belonging to nobody" value={String((s?.unmatched ?? []).reduce((n, u) => n + u.punches, 0))}
          tone={(s?.unmatched ?? []).length ? 'warning' : undefined} sub={(s?.unmatched ?? []).length ? `${s!.unmatched.length} number${s!.unmatched.length === 1 ? '' : 's'} to match below` : undefined} loading={q.isPending} />
      </StatGrid>

      <Card className="mb-5 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">The office sync program</h2>
            <p className="text-[13px] text-muted-foreground">
              It runs on the computer that holds the attendance system's database and sends new punches every minute.
              {s?.agent ? ` Last sent by: ${s.agent}.` : ''}
            </p>
            {master && !s?.connected && (
              <ol className="mt-2 list-decimal space-y-0.5 pl-5 text-[13px] text-muted-foreground">
                <li>On the office computer that holds the attendance database, open this page and press <strong>Download set-up package</strong>.</li>
                <li>Unzip it, double-click <strong>SETUP.bat</strong> and click Yes. It does the rest in about a minute, on any Windows from 7 to 11, with nothing to download.</li>
                <li>This page then says <strong>Working</strong>, and attendance arrives by itself.</li>
              </ol>
            )}
          </div>
          {master && (
            <div className="flex flex-wrap gap-2">
              <Button loading={downloading} onClick={() => (s?.connected ? setConfirmPackage(true) : void downloadPackage())}><Download /> Download set-up package</Button>
              <Button variant="ghost" onClick={() => setAsking(true)}><KeyRound /> Key only</Button>
            </div>
          )}
        </div>
      </Card>

      <h2 className="mb-2 text-base font-semibold">Machines</h2>
      <Card className="mb-5 overflow-hidden">
        {(s?.devices ?? []).length === 0 ? <p className="p-4 text-sm text-muted-foreground">No machine has sent a punch yet. Each appears here the first time it does.</p> : (
          <table className="w-full text-sm">
            <thead><tr className="border-b border-border text-left text-xs text-muted-foreground"><th className="px-3 py-2">Machine</th><th className="px-3 py-2">Name</th><th className="px-3 py-2">Stands at</th><th className="px-3 py-2">Last punch</th></tr></thead>
            <tbody>{(s?.devices ?? []).map((d) => <DeviceRow key={d.id} d={d} sites={sites} manage={manage} />)}</tbody>
          </table>
        )}
      </Card>

      {(s?.unmatched ?? []).length > 0 && (
        <>
          <div className="mb-2 flex items-center justify-between gap-3">
            <h2 className="text-base font-semibold">Punches belonging to nobody</h2>
            {manage && <Button size="sm" variant="outline" loading={rematch.isPending} onClick={() => rematch.mutate()}><RefreshCw /> Match again</Button>}
          </div>
          <Card className="mb-5 p-4">
            <p className="mb-3 text-[13px] text-muted-foreground">These numbers came from the machines and match no employee code. Put each number against its person below; their punches are counted at once.</p>
            <ul className="divide-y divide-border">
              {(s?.unmatched ?? []).map((u) => (
                <li key={u.biometric_id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                  <span>
                    <Badge tone="warning">{u.biometric_id}</Badge>{' '}
                    <span className="font-medium">{u.name || 'No name on the machine'}</span>
                    <span className="ml-2 text-xs text-muted-foreground">{u.punches} punch{u.punches === 1 ? '' : 'es'}, last {u.last.slice(0, 16)}</span>
                  </span>
                  {manage && u.suggestion && (
                    <Button size="sm" variant="outline" loading={match.isPending && match.variables?.number === u.biometric_id}
                      onClick={() => match.mutate({ id: u.suggestion!.id, number: u.biometric_id })}>
                      Looks like {u.suggestion.name} - match
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          </Card>
        </>
      )}

      <h2 className="mb-2 text-base font-semibold">People and their number on the machine</h2>
      <Card className="overflow-hidden">
        <p className="border-b border-border p-3 text-[13px] text-muted-foreground">A punch is matched on the employee code. Fill a number here only where the machine knows the person by a different one.</p>
        <table className="w-full text-sm">
          <thead><tr className="border-b border-border text-left text-xs text-muted-foreground"><th className="px-3 py-2">Employee</th><th className="px-3 py-2">Employee code</th><th className="px-3 py-2">Number on the machine</th></tr></thead>
          <tbody>{(s?.employees ?? []).map((p) => <PersonRow key={p.id} p={p} manage={manage} />)}</tbody>
        </table>
      </Card>

      <ConfirmDialog open={confirmPackage} onOpenChange={setConfirmPackage} title="Make a new set-up package?" confirmLabel="Download"
        description="It carries a new key, so the key in use stops working: the program on the office computer sends nothing until it is set up again from this package." loading={downloading} onConfirm={() => void downloadPackage()} />
      <ConfirmDialog open={asking} onOpenChange={setAsking} title={s?.connected ? 'Make a new key?' : 'Make the key'} confirmLabel="Make the key"
        description={s?.connected ? 'The key in use stops working at once: the office program sends nothing until the new key is put in its settings.' : 'It is shown once. Put it in the sync program\'s settings file on the office computer.'}
        loading={make.isPending} onConfirm={() => make.mutate()} />
      <Modal open={!!key} onOpenChange={(o) => !o && setKey('')} title="The key for the sync program" size="md"
        description="Copy it now into the program's settings (config.ini, api_key). It is not shown again; anybody holding it can send attendance, so do not share it."
        footer={<Button onClick={() => { void navigator.clipboard?.writeText(key) }}>Copy</Button>}>
        <Input readOnly value={key} className="font-mono text-xs" onFocus={(e) => e.currentTarget.select()} />
      </Modal>
    </>
  )
}

function DeviceRow({ d, sites, manage }: { d: Device; sites: { value: number; label: string }[]; manage: boolean }) {
  const [name, setName] = useState(d.name)
  const [job, setJob] = useState<number | null>(d.job_id)
  const save = useAction(() => put<{ message: string }>(`/api/biometric/devices/${d.id}`, { name, job_id: job }), { invalidate: [KEY] })
  const dirty = name !== d.name || job !== d.job_id
  return (
    <tr className="border-b border-border last:border-0">
      <td className="px-3 py-2 font-mono text-xs">{d.device_code}</td>
      <td className="px-3 py-2"><Input aria-label={`Name of machine ${d.device_code}`} disabled={!manage} value={name} onChange={(e) => setName(e.target.value)} /></td>
      <td className="px-3 py-2"><Select aria-label={`Site of machine ${d.device_code}`} disabled={!manage} value={job ?? ''} onChange={(e) => setJob(Number(e.target.value) || null)} placeholder="Head office" options={sites} /></td>
      <td className="px-3 py-2 text-xs text-muted-foreground">
        <span className="mr-3">{d.last_punch_at ? d.last_punch_at.slice(0, 16) : '-'}</span>
        {manage && dirty && <Button size="sm" loading={save.isPending} onClick={() => save.mutate()}>Save</Button>}
      </td>
    </tr>
  )
}

function PersonRow({ p, manage }: { p: Person; manage: boolean }) {
  const [id, setId] = useState(p.biometric_id)
  const save = useAction(() => put<{ message: string }>(`/api/biometric/employees/${p.id}`, { biometric_id: id }), { invalidate: INVALIDATE })
  return (
    <tr className="border-b border-border last:border-0">
      <td className="px-3 py-2">{p.name}</td>
      <td className="px-3 py-2 font-mono text-xs">{p.employee_code || '-'}</td>
      <td className="px-3 py-2">
        <div className="flex items-center gap-2">
          <Input aria-label={`Number on the machine for ${p.name}`} disabled={!manage} className="w-40 font-mono" value={id} placeholder={p.employee_code || ''} onChange={(e) => setId(e.target.value)} />
          {manage && id !== p.biometric_id && <Button size="sm" loading={save.isPending} onClick={() => save.mutate()}>Save</Button>}
        </div>
      </td>
    </tr>
  )
}
