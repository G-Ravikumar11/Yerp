/** An address inside the app. Built, the app lives under /next/; in development it owns the root. */
export const appUrl = (path = '') => import.meta.env.BASE_URL + path.replace(/^\//, '')
