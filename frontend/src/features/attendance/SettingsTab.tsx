import { useState } from 'react'
import { Button, Field, Input, NumField, Skeleton } from '@/components/ui'
import { attKeys, saveAttSettings, useAttSettings, type AttSettings } from '@/api/attendance'
import { useAction } from '@/lib/mutate'

const DAYS = [['1', 'Mon'], ['2', 'Tue'], ['3', 'Wed'], ['4', 'Thu'], ['5', 'Fri'], ['6', 'Sat'], ['7', 'Sun']] as const

export function SettingsTab() {
  const q = useAttSettings()
  if (q.isPending || !q.data) return <Skeleton className="h-64 w-full max-w-2xl" />
  return <Form initial={q.data} />
}

function Form({ initial }: { initial: AttSettings }) {
  const [s, setS] = useState(initial)
  const set = <K extends keyof AttSettings>(k: K, v: AttSettings[K]) => setS((x) => ({ ...x, [k]: v }))
  const days = s.working_days.split(',').filter(Boolean)
  const toggle = (d: string) => set('working_days', (days.includes(d) ? days.filter((x) => x !== d) : [...days, d]).sort().join(',') || '1,2,3,4,5')
  const save = useAction(() => saveAttSettings(s), { invalidate: [attKeys.all], success: 'Settings saved' })
  return (
    <section aria-label="Attendance settings" className="max-w-2xl rounded-xl border border-border bg-card p-5 shadow-card">
      <h2 className="mb-4 text-sm font-semibold">Geofence and work hours</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Office name" htmlFor="as-name"><Input id="as-name" value={s.office_name} onChange={(e) => set('office_name', e.target.value)} /></Field>
        <Field label="Geofence radius (metres)" htmlFor="as-radius"><NumField id="as-radius" value={s.geofence_radius} onValue={(n) => set('geofence_radius', n)} /></Field>
        <Field label="Office latitude" htmlFor="as-lat"><NumField id="as-lat" value={s.office_lat} onValue={(n) => set('office_lat', n)} /></Field>
        <Field label="Office longitude" htmlFor="as-lng"><NumField id="as-lng" value={s.office_lng} onValue={(n) => set('office_lng', n)} /></Field>
        <Field label="Work starts" htmlFor="as-start"><Input id="as-start" type="time" value={s.work_start} onChange={(e) => set('work_start', e.target.value)} /></Field>
        <Field label="Work ends" htmlFor="as-end"><Input id="as-end" type="time" value={s.work_end} onChange={(e) => set('work_end', e.target.value)} /></Field>
        <Field label="Grace period (minutes)" htmlFor="as-grace"><NumField id="as-grace" value={s.grace_minutes} onValue={(n) => set('grace_minutes', n)} /></Field>
        <Field label="Auto clock-out after (hours)" htmlFor="as-auto"><NumField id="as-auto" value={s.auto_clockout_hours} onValue={(n) => set('auto_clockout_hours', n)} /></Field>
        <Field label="Longest overtime (hours)" htmlFor="as-ot"><NumField id="as-ot" value={s.max_overtime_hours} onValue={(n) => set('max_overtime_hours', n)} /></Field>
        <div className="flex flex-col justify-end gap-2 text-sm">
          <label className="flex items-center gap-2"><input type="checkbox" checked={s.allow_remote} onChange={(e) => set('allow_remote', e.target.checked)} /> Allow remote clock-in</label>
          <label className="flex items-center gap-2"><input type="checkbox" checked={s.require_location} onChange={(e) => set('require_location', e.target.checked)} /> Require location</label>
        </div>
      </div>
      <div className="mt-5 border-t border-border pt-4">
        <p className="mb-2 text-sm font-medium">Working days</p>
        <div className="flex flex-wrap gap-4 text-sm">{DAYS.map(([v, l]) => <label key={v} className="flex items-center gap-1.5"><input type="checkbox" checked={days.includes(v)} onChange={() => toggle(v)} /> {l}</label>)}</div>
        <label className="mt-4 flex items-center gap-2 text-sm"><input type="checkbox" checked={s.auto_clock_in} onChange={(e) => set('auto_clock_in', e.target.checked)} /> Signing in to the portal starts a shift</label>
        <p className="mt-1.5 text-[13px] text-muted-foreground">Leave this off and staff clock in themselves. Either way, signing in on a non-working day never records attendance, so someone opening the portal on a Sunday to read a payslip is not marked present. They can still clock in by hand if they really are working.</p>
      </div>
      <div className="mt-5 flex justify-end">
        <Button loading={save.isPending} onClick={() => save.mutate()}>Save settings</Button>
      </div>
    </section>
  )
}
