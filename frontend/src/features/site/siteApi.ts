import { useEffect, useState } from 'react'

/** What the site reads from the ERP: public totals and the projects ticked "show on website". Plain fetch - this page is its
 *  own bundle and never loads the ERP's API layer. */
export interface LiveProject { id: number; name: string; client: string; sector: string; location: string; scope: string; status: 'Completed' | 'Ongoing'; year: string; photos: string[] }
export interface Live { company_id: number; numbers: { projects_delivered: number; ongoing_sites: number; safe_man_hours: number }; projects: LiveProject[] }

const base = () => (import.meta.env.VITE_API_BASE_URL || '').trim().replace(/\/$/, '')
export const apiPath = (path: string) => base() + path

/** Null until it arrives, and stays null if the ERP cannot be reached: every section using it has its own text without it. */
export function useLive() {
  const [live, setLive] = useState<Live | null>(null)
  useEffect(() => {
    let gone = false
    fetch(apiPath('/api/public/site')).then((r) => (r.ok ? r.json() : null)).then((d) => { if (!gone && d) setLive(d) }).catch(() => undefined)
    return () => { gone = true }
  }, [])
  return live
}

export interface Enquiry { name: string; company: string; phone: string; email: string; city: string; project_type?: string; scopes?: string[]; message: string; website: string }

/** Sends an enquiry. Resolves to the thank-you, or throws what the server said was wrong. */
export async function sendEnquiry(e: Enquiry): Promise<string> {
  const r = await fetch(apiPath('/api/public/enquiry'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(e) })
  const d = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'We could not send that. Please call us instead.')
  return d.message || 'Thank you. We will be in touch.'
}
