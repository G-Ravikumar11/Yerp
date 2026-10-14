import type { IntervalType, ServiceStatus } from '@/api/equipment'
import { formatDate, today } from '@/lib/format'

export const INTERVAL_OPTIONS: { value: IntervalType; label: string }[] = [
  { value: 'Both', label: 'Meter reading + calendar days' },
  { value: 'Meter', label: 'Meter reading only' },
  { value: 'Days', label: 'Calendar days only' },
  { value: 'None', label: 'No service schedule' },
]
export const UNIT_OPTIONS = [{ value: 'Hours', label: 'Operating hours' }, { value: 'Km', label: 'Kilometres' }]
export const unitWord = (u: string) => (u === 'Km' ? 'km' : 'hours')

const ORDER: ServiceStatus[] = ['Overdue', 'Service due', 'Due soon', 'Upcoming']
// In UTC throughout, so a date never slips a day in a time zone ahead of it.
const addDays = (iso: string, n: number) => { const d = new Date(`${iso}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10) }
const daysBetween = (a: string, b: string) => Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86400000)
const n = (v: number) => v.toLocaleString('en-IN', { maximumFractionDigits: 1 })

export interface ScheduleDraft {
  type: IntervalType; unit: string; meterNow: number; everyMeter: number; everyDays: number
  lastMeter: number | null; lastOn: string; reminderMeter: number | null; reminderDays: number | null
}

/** What the form would set, read the way the server reads it: the thresholds, the reminders, and where the machine stands today.
 *  Only a preview - the server works it out again, with the same rules, when it is saved. */
export function previewSchedule(d: ScheduleDraft) {
  const unit = unitWord(d.unit)
  const usesMeter = d.type === 'Both' || d.type === 'Meter'
  const usesDays = d.type === 'Both' || d.type === 'Days'
  const remM = d.reminderMeter ?? Math.round(d.everyMeter * 0.1 * 10) / 10
  const remD = d.reminderDays ?? Math.max(3, Math.round(d.everyDays * 0.1))
  const nextMeter = usesMeter && d.everyMeter > 0 && d.lastMeter !== null ? Math.round((d.lastMeter + d.everyMeter) * 10) / 10 : null
  const nextOn = usesDays && d.everyDays > 0 && d.lastOn ? addDays(d.lastOn, d.everyDays) : null
  const found: ServiceStatus[] = []
  let meterLeft: number | null = null
  let daysLeft: number | null = null
  if (nextMeter !== null) {
    meterLeft = Math.round((nextMeter - d.meterNow) * 10) / 10
    found.push(meterLeft < -d.everyMeter * 0.1 ? 'Overdue' : meterLeft <= 0 ? 'Service due' : meterLeft <= remM ? 'Due soon' : 'Upcoming')
  }
  if (nextOn) {
    daysLeft = daysBetween(today(), nextOn)
    found.push(daysLeft < 0 ? 'Overdue' : daysLeft === 0 ? 'Service due' : daysLeft <= remD ? 'Due soon' : 'Upcoming')
  }
  const status: ServiceStatus = d.type === 'None' ? 'Not scheduled' : found.length ? ORDER.find((s) => found.includes(s))! : 'Incomplete'
  const lines: string[] = []
  if (d.type === 'None') lines.push('No service reminders for this machine.')
  else if (status === 'Incomplete') lines.push(`Enter ${[usesMeter && nextMeter === null ? (d.everyMeter > 0 ? 'the meter reading at the last service' : `the ${unit} between services`) : '', usesDays && !nextOn ? (d.everyDays > 0 ? 'the date of the last service' : 'the days between services') : ''].filter(Boolean).join(' and ')} to work out when it is due.`)
  else {
    const at = nextMeter !== null ? `at ${n(nextMeter)} ${unit}` : ''
    const on = nextOn ? `on ${formatDate(nextOn)}` : ''
    lines.push(`Next service due ${[at, on].filter(Boolean).join(' or ')}${at && on ? ', whichever comes first' : ''}.`)
    const rem = [nextMeter !== null ? `${n(Math.max(0, nextMeter - remM))} ${unit}` : '', nextOn ? formatDate(addDays(nextOn, -remD)) : ''].filter(Boolean)
    lines.push(`Reminder from ${rem.join(' or ')}${d.reminderMeter === null && d.reminderDays === null ? ' (a tenth of the interval)' : ''}.`)
    const now = [meterLeft !== null ? (meterLeft >= 0 ? `${n(meterLeft)} ${unit} to go` : `${n(-meterLeft)} ${unit} past`) : '', daysLeft !== null ? (daysLeft >= 0 ? `${daysLeft} days to go` : `${-daysLeft} days past`) : ''].filter(Boolean)
    lines.push(`Today: ${now.join(', ')}.${nextMeter !== null ? ` Overdue once past ${n(nextMeter + d.everyMeter * 0.1)} ${unit}` : ''}${nextOn ? `${nextMeter !== null ? ';' : ''} overdue after ${formatDate(nextOn)}` : ''}${nextMeter !== null || nextOn ? '.' : ''}`)
  }
  return { status, nextMeter, nextOn, remM, remD, lines, usesMeter, usesDays }
}
