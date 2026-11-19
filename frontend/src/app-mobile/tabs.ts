/** The four places the phone's tab bar goes to: these screens are tabs. Every other screen gets a back bar and a title. */
export const TABS = new Set(['/', '/projects', '/approvals', '/more'])
export const TAB_TITLES: Record<string, string> = { '/': 'Home', '/projects': 'Projects', '/approvals': 'Approvals', '/more': 'Menu' }
