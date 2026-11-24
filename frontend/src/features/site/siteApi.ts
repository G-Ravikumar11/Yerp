import { useEffect, useState } from 'react'

/** What the site reads from our records: public totals and the projects ticked "show on website". Plain fetch - this page is its
 *  own bundle and never loads the staff app's API layer. */
export interface LiveProject { id: number; name: string; client: string; sector: string; location: string; scope: string; status: 'Completed' | 'Ongoing'; year: string; photos: string[] }
/** `content`: the website's sections as last published from Settings -> Website (siteContent.ts reads them). */
/** An opening on the Careers section: Recruitment's open, published job, and the token its application form is opened with. */
export interface Opening { id: number; title: string; location: string; experience: string; description: string; apply_token: string | null }
export interface Live { openings?: Opening[]; company_id: number; numbers: { projects_delivered: number; ongoing_sites: number; safe_man_hours: number }; projects: LiveProject[]; content?: Record<string, unknown> }

const base = () => (import.meta.env.VITE_API_BASE_URL || '').trim().replace(/\/$/, '')
export const apiPath = (path: string) => base() + path

/** The page is the preview inside Settings -> Website: shown in a frame there, with ?preview=1. It then shows the draft, not
 *  what is published, and sends nothing. */
export const isPreview = () => {
  try {
    return new URLSearchParams(location.search).get('preview') === '1' && window.parent !== window
  } catch {
    return false
  }
}

/** Null until it arrives, and stays null if the server cannot be reached: every section using it has its own text without
 *  it. In the preview it is the draft (`reload` changes when the panel says the saved draft has moved on). */
export function useLive(preview = false, reload = 0) {
  const [live, setLive] = useState<Live | null>(null)
  useEffect(() => {
    let gone = false
    fetch(apiPath(preview ? '/api/website/preview' : '/api/public/site'), preview ? { credentials: 'include' } : undefined)
      .then((r) => (r.ok ? r.json() : null)).then((d) => { if (!gone && d) setLive(d) }).catch(() => undefined)
    return () => { gone = true }
  }, [preview, reload])
  return live
}

/** In the preview: the panel's unsaved draft, sent as it is typed, and a count that goes up when the saved draft changes. */
export function usePreviewMessages(preview: boolean) {
  const [draft, setDraft] = useState<Record<string, unknown> | null>(null)
  const [reload, setReload] = useState(0)
  useEffect(() => {
    if (!preview) return
    const on = (e: MessageEvent) => {
      if (e.origin !== location.origin || e.source !== window.parent) return
      const m = e.data as { type?: string; content?: Record<string, unknown> }
      if (m?.type === 'website-preview' && m.content) setDraft(m.content)
      if (m?.type === 'website-preview-reload') setReload((n) => n + 1)
    }
    addEventListener('message', on)
    window.parent.postMessage({ type: 'website-preview-ready' }, location.origin)
    return () => removeEventListener('message', on)
  }, [preview])
  return { draft, reload }
}

export interface Enquiry { name: string; company: string; phone: string; email: string; city: string; project_type?: string; scopes?: string[]; message: string; website: string }

/** Sends an enquiry. Resolves to the thank-you, or throws what the server said was wrong. */
export async function sendEnquiry(e: Enquiry): Promise<string> {
  if (isPreview()) throw new Error('This is the preview: enquiries are not sent from here.')
  const r = await fetch(apiPath('/api/public/enquiry'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(e) })
  const d = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'We could not send that. Please call us instead.')
  return d.message || 'Thank you. We will be in touch.'
}
