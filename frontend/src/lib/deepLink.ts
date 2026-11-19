/**
 * Opening the screen a notification is about. Every notice the server sends carries a link ("/next/approvals", written for
 * the website); tapping it in the phone app must land on that screen, also when the tap is what started the app.
 *
 * The tap can arrive before the app has a signed-in person and a router to go through. Such a link is kept, and opened by
 * the shell the moment it is mounted (that is, once somebody is signed in), by moving inside the app, not by reloading it.
 */
let navigate: ((to: string) => void) | null = null
let waiting = ''

/** The place inside the app a notice's link means: '' for anything that is not a path of this app. */
export function linkTarget(link: unknown): string {
  if (typeof link !== 'string' || !link.startsWith('/') || link.startsWith('//') || link.includes('\\')) return ''
  const path = link.replace(/^\/next(?=[/?#]|$)/, '')
  return !path ? '/' : /^[?#]/.test(path) ? '/' + path : path
}

/** A notice was tapped: go there now, or as soon as the app can. */
export function openLink(link: unknown) {
  const to = linkTarget(link)
  if (!to) return
  if (navigate) navigate(to)
  else waiting = to
}

/** The shell says how to move inside the app. Anything kept from before it was ready is opened now. Returns the way to let go. */
export function attachNavigator(fn: (to: string) => void) {
  navigate = fn
  if (waiting) {
    const to = waiting
    waiting = ''
    fn(to)
  }
  return () => {
    if (navigate === fn) navigate = null
  }
}
