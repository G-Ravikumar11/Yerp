import { createContext, useContext } from 'react'
import { COMPANY, SITE } from './data/content'

/** The site's words and pictures. They are kept in our records (Settings -> Website) and arrive with the live figures from
 *  /api/public/site, as last published. Until they arrive, or if they cannot, the page shows the copy it was built with
 *  (data/content.ts), which is also what the records start from - so a first visit looks the same either way. */
export interface SiteContent { COMPANY: typeof COMPANY; SITE: typeof SITE }

export const BUILT_IN: SiteContent = { COMPANY, SITE }

/** The published sections over the built-in copy: a section missing from what arrived keeps the built-in one. */
export function contentFrom(published?: Record<string, unknown> | null): SiteContent {
  if (!published) return BUILT_IN
  const has = (k: string) => published[k] !== undefined && published[k] !== null
  const site = Object.fromEntries(Object.entries(SITE).map(([k, v]) => [k, has(k) ? published[k] : v])) as typeof SITE
  return { COMPANY: has('company') ? (published.company as typeof COMPANY) : COMPANY, SITE: site }
}

const Content = createContext<SiteContent>(BUILT_IN)
export const ContentProvider = Content.Provider
export const useContent = () => useContext(Content)
