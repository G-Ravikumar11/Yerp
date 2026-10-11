import { PLAN_TYPES, SITE } from './data/content'
import { PROJECTS, type Project } from './data/projects'
import { inr } from './lib'

/** What the visitor has said about their project so far. The capabilities, the 3D building and the planner all feed it. */
export interface Plan {
  type: string | null
  scopes: string[]
  size: number
  city: string
  stage: string | null
}

export const EMPTY_PLAN: Plan = { type: null, scopes: [], size: 40, city: '', stage: null }

/** 10,000 to 50 lakh sq ft on a log scale. */
export const sizeOf = (p: number) => Math.round((10000 * Math.pow(500, p / 100)) / 5000) * 5000

export const scopeLabel = (id: string) => SITE.plan.scopes.find((s) => s.id === id)?.label ?? id

export function briefText(plan: Plan) {
  const T = PLAN_TYPES.find((t) => t.id === plan.type)
  const sc = SITE.plan.scopes.filter((s) => plan.scopes.includes(s.id))
  return `Hello Yalavarti team,\n\nWe would like a quote for the following project.\n\nProject type: ${T ? T.label : '-'}\nScope: ${sc.map((s) => s.label).join(', ') || '-'}\nBuilt-up area: about ${inr(sizeOf(plan.size))} sq ft\nSite: ${plan.city || '-'}\nStage: ${plan.stage || '-'}\n\nName:\nCompany:\nPhone:\n`
}

/** Comparable finished work for the chosen kind of project, near the stated city when there is some. */
export function similarProjects(plan: Plan): { total: number; local: boolean; list: Project[] } {
  const T = PLAN_TYPES.find((t) => t.id === plan.type)
  if (!T) return { total: 0, local: false, list: [] }
  let list = PROJECTS.filter((p) => p.s === T.sector && (!T.match || T.match.test(p.n)))
  let local = false
  if (plan.city) {
    const c = plan.city.toLowerCase()
    const near = list.filter((p) => p.l.toLowerCase().includes(c))
    if (near.length) { list = near; local = true }
  }
  const total = list.length
  return { total, local, list: list.slice().sort((a, b) => (b.y || '').localeCompare(a.y || '')).slice(0, 3) }
}
