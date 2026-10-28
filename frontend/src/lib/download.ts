import { Capacitor } from '@capacitor/core'
import { Directory, Filesystem } from '@capacitor/filesystem'
import { Share } from '@capacitor/share'
import { apiUrl } from '@/lib/api'
import { toast } from '@/stores/toast'

/**
 * Downloads in the phone app.
 *
 * The website's PDF and Excel buttons are plain links ("/api/ra-bills/3/export.xlsx"). In the app a bare "/api/..." address
 * points at the app's own files, not the server, and the phone's own browser has none of the person's sign-in - so such a
 * button did nothing. Here the app does the fetching itself, with the person's sign-in, keeps the file on the phone, and
 * hands it to the phone's own "Open with / Share" choices (a spreadsheet app, a PDF reader, WhatsApp, e-mail).
 *
 * Every button that links to a download is covered at once, without editing any of them: clicks on such links (and
 * window.open, and a script clicking a link it made) are caught here. Only the native app installs any of this, so the
 * website is untouched.
 */

const DOWNLOAD_EXT = /\.(pdf|xlsx|xls|csv|docx|doc|zip)$/i

/** The part of an address after the origin, when the address is on this app's own origin; else null. */
function appPath(href: string, base: string): string | null {
  try {
    const u = new URL(href, base)
    return u.origin === new URL(base).origin ? u.pathname + u.search : null
  } catch {
    return null
  }
}

/**
 * Whether a link is a download the app must fetch itself: an address of this app's server (/api/...) that is a file by its
 * ending, or is marked as one (a `download` attribute, or ?download=1), or a file the page made in memory (blob:) with a
 * `download` attribute. Other links - a page of the app, an outside website - are left alone.
 */
export function isDownloadLink(href: string | null | undefined, downloadAttr: string | null | undefined, base: string): boolean {
  if (!href) return false
  if (href.startsWith('blob:')) return downloadAttr != null
  const path = appPath(href, base)
  if (!path || !path.startsWith('/api/')) return false
  const [onlyPath, query = ''] = path.split('?')
  return DOWNLOAD_EXT.test(onlyPath) || downloadAttr != null || /(^|&)download=1(&|$)/.test(query)
}

/** A name for the saved file: the one the page asked for, else the server's, else the last part of the address. */
export function fileNameFor(downloadAttr: string | null | undefined, contentDisposition: string | null | undefined, href: string): string {
  const clean = (s: string) => s.replace(/[\\/:*?"<>|\u0000-\u001f]+/g, '_').trim().slice(0, 120)
  if (downloadAttr && downloadAttr.trim()) return clean(downloadAttr)
  const star = /filename\*\s*=\s*(?:UTF-8'')?([^;]+)/i.exec(contentDisposition || '')
  if (star) { try { return clean(decodeURIComponent(star[1].trim().replace(/^"|"$/g, ''))) } catch { /* fall through */ } }
  const plain = /filename\s*=\s*"?([^";]+)"?/i.exec(contentDisposition || '')
  if (plain) return clean(plain[1])
  const last = decodeURIComponent((href.split('?')[0].split('/').pop() || '').trim())
  return clean(last) || 'download'
}

function toBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader()
    r.onerror = () => reject(r.error)
    r.onload = () => resolve(String(r.result).split(',')[1] ?? '')
    r.readAsDataURL(blob)
  })
}

const busy = new Set<string>()

/** Fetch the file with the person's sign-in, keep it on the phone, and offer to open or share it. */
export async function downloadAndShare(href: string, downloadAttr?: string | null) {
  if (busy.has(href)) return
  busy.add(href)
  try {
    toast.info('Getting the file...')
    const res = href.startsWith('blob:') ? await fetch(href) : await fetch(apiUrl(appPath(href, location.href) ?? href), { credentials: 'include' })
    if (!res.ok) {
      let why = ''
      try { why = ((await res.json()) as { detail?: unknown }).detail as string } catch { /* not JSON */ }
      toast.error(typeof why === 'string' && why ? why : res.status === 401 ? 'Please sign in again.' : 'That file could not be downloaded.')
      return
    }
    const name = fileNameFor(downloadAttr, res.headers.get('content-disposition'), href)
    const data = await toBase64(await res.blob())
    const saved = await Filesystem.writeFile({ path: `downloads/${Date.now()}/${name}`, data, directory: Directory.Cache, recursive: true })
    await Share.share({ title: name, dialogTitle: `Open or share ${name}`, url: saved.uri })
  } catch (e) {
    const msg = String((e as { message?: unknown })?.message ?? e)
    // Someone dismissing the share sheet is not an error.
    if (/cancel|dismiss/i.test(msg)) return
    toast.error(/not implemented|not available|plugin/i.test(msg)
      ? 'Install the latest version of the app to download files.'
      : 'That file could not be downloaded. Check the connection and try again.')
  } finally {
    busy.delete(href)
  }
}

let installed = false

/** In the native app: route every download link through downloadAndShare. A no-op in a browser. */
export function installDownloads() {
  if (installed || !Capacitor.isNativePlatform()) return
  installed = true
  const base = location.href

  // A tap on a link (the common case; every button on the website's screens).
  document.addEventListener('click', (e) => {
    const a = (e.target as Element | null)?.closest?.('a[href]') as HTMLAnchorElement | null
    if (!a || !isDownloadLink(a.getAttribute('href'), a.getAttribute('download'), base)) return
    e.preventDefault()
    e.stopPropagation()
    void downloadAndShare(a.href, a.getAttribute('download'))
  }, true)

  // A script that makes a link and clicks it (saving a file it built in memory).
  const nativeClick = HTMLAnchorElement.prototype.click
  HTMLAnchorElement.prototype.click = function (this: HTMLAnchorElement) {
    if (isDownloadLink(this.getAttribute('href'), this.getAttribute('download'), base)) {
      void downloadAndShare(this.href, this.getAttribute('download'))
      return
    }
    nativeClick.call(this)
  }

  // window.open(url) for a file.
  const nativeOpen = window.open.bind(window)
  window.open = ((url?: string | URL, ...rest: unknown[]) => {
    const href = url == null ? '' : String(url)
    if (href && isDownloadLink(href, null, base)) {
      void downloadAndShare(href)
      return null
    }
    return nativeOpen(url as string, ...(rest as [string?, string?]))
  }) as typeof window.open
}
