/** What can pop up: the same few fields whether it came from a member of staff's notifications or the Master's alerts. */
export interface Popup { id: number; title: string; body: string; tone: 'info' | 'error'; read: boolean }

/** The most that pop up at once; the rest are folded into one line so a returning user is not buried. */
export const MOST_AT_ONCE = 3

/**
 * Which of `items` are new since `last` (the newest id already shown): unread, newer, oldest first.
 * With no `last` (first time this person is seen on this device) nothing is new - what was waiting is in the bell, not thrown at them.
 */
export function freshOnes(items: Popup[], last: number | null): Popup[] {
  if (last === null) return []
  return items.filter((i) => i.id > last && !i.read).sort((a, b) => a.id - b.id)
}

export const newestId = (items: Popup[]) => items.reduce((m, i) => Math.max(m, i.id), 0)

/** The text of a pop-up: the title, and what it says. */
export const popupText = (p: Popup) => (p.body ? `${p.title} - ${p.body}` : p.title)
