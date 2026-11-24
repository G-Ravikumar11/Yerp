import { SITE, type WorkType } from './data/content'

/** What the visitor has told the enquiry form so far. A "What we build" card can fill in the type of work. */
export interface Plan {
  type: string | null
  city: string
  area: string
  unit: string
  start: string | null
}

export const EMPTY_PLAN: Plan = { type: null, city: '', area: '', unit: SITE.plan.units[0], start: null }

export const typeLabel = (id: string | null, types: WorkType[] = SITE.plan.types) => types.find((t) => t.id === id)?.label ?? ''

export const areaText = (plan: Plan) => (plan.area.trim() ? `${plan.area.trim()} ${plan.unit}` : '')

export function briefText(plan: Plan, company: string, types: WorkType[]) {
  return `Hello ${company},\n\nWe would like to talk to you about the following work.\n\nType of work: ${typeLabel(plan.type, types) || '-'}\nLocation: ${plan.city || '-'}\nPlot or built-up area: ${areaText(plan) || '-'}\nExpected start: ${plan.start || '-'}\n\nName:\nCompany:\nPhone:\n`
}
