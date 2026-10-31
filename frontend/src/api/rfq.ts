import { useQuery } from '@tanstack/react-query'
import { api, get, post, put } from '@/lib/api'

export const rfqKeys = { all: ['rfq'] as const }

export interface Rfq {
  id: number; number: string; title: string; project: string; job_id: number | null; lines: number; quotes: number; needed_by: string; status: string
  notes?: string; award_reason?: string; created_by_name?: string; created_at?: string; awarded_at?: string; work_order_id?: number | null
  /** Suppliers who have not quoted are reminded before this, and the buyer gets the L1 summary on it. */
  quotes_due?: string
}
/** A row of the list: how far the enquiry has got - suppliers asked, still to answer, and the best full quote so far. */
export interface RfqRow extends Rfq { asked: number; waiting: number; best: { supplier_name: string; landed: number } | null; awarded_to: string[]; orders: number }
interface Offer { supplier_name: string; rate: number; amount: number; tax_percent: number; remarks?: string }
export interface RfqLine { rfq_line_id: number; description: string; item_code: string; uom: string; qty: number; spread_percent: number; awarded_supplier: string; awarded_rate: number; po_id: number | null; po_number: string; lowest: string; lowest_rate: number; offers: Offer[] }
interface QuoteDocument { id: number; name: string; size: number }
export interface RfqSupplier {
  quote_id: number; supplier_name: string; quote_ref: string; quote_date: string; rank?: string; is_l1: boolean; basic: number; tax: number; freight: number; landed: number
  delivery_days: number; payment_terms: string; valid_until: string; notes: string; complete: boolean; lines_quoted: number
  /** "vendor" when the supplier sent it through his own link; else the buyer typed it. */
  source?: string
  /** The supplier's own quotation file, as he sent it. */
  document?: QuoteDocument | null
}
/** A link sent to a supplier to quote on his own: sent, opened, quoted, or his file sent without rates (document). */
export interface RfqInvite {
  id: number; supplier_name: string; phone: string; email: string; status: 'sent' | 'opened' | 'quoted' | 'document'
  opened_at: string; submitted_at: string; quote_id: number | null; document_id: number | null; message: string; link: string; created_at: string
  document?: QuoteDocument | null
  /** When the server emailed the link, and how many reminders have gone since. */
  emailed_at?: string; reminders?: number
}
/** A purchase order the award made. */
export interface RfqOrder { id: number; number: string; supplier_name: string; total: number; status: string }
export interface Statement { rfq: Rfq; lines: RfqLine[]; suppliers: RfqSupplier[]; l1: string; l1_landed: number; saving_vs_l2: number; lowest_per_line_basic: number; invites?: RfqInvite[]; orders?: RfqOrder[] }

// Quotes come in from outside - a supplier answering through their link - so an enquiry is asked for afresh every time
// it is opened or come back to, never shown from what the screen saw a minute ago.
const fresh = { staleTime: 0, refetchOnWindowFocus: true } as const
export const useRfqs = () => useQuery({ ...fresh, queryKey: ['rfq', 'list'], queryFn: () => get<{ rfqs: RfqRow[]; summary: { open: number; waiting_for_quotes: number; awarded: number; cancelled: number } }>('/api/rfqs') })
export const useStatement = (id: number | null) => useQuery({ ...fresh, queryKey: ['rfq', 'one', id], enabled: !!id, queryFn: () => get<Statement>(`/api/rfqs/${id}/statement`) })
export const useSupplierNames = () => useQuery({ queryKey: ['rfq', 'suppliers'], staleTime: 5 * 60_000, queryFn: async () => ((await get<{ suppliers: { name: string; phone?: string; email?: string }[] }>('/api/suppliers')).suppliers ?? []) })

export interface RfqInput { title: string; job_id: number | null; needed_by: string; notes?: string; quotes_due?: string; lines: { item_code: string; description: string; uom: string; qty: number; indent_line_id?: number | null }[] }
export const openRfq = (b: RfqInput) => post<{ rfq: { id: number }; message: string; skipped?: string[] }>('/api/rfqs', b)
/** Correct an open enquiry. Its items can change only until the first quote is in. */
export const editRfq = (id: number, b: RfqInput) => put<{ rfq: Rfq; message: string }>(`/api/rfqs/${id}`, b)
export const cancelRfq = (id: number, reason: string) => post<{ message: string }>(`/api/rfqs/${id}/cancel`, { reason })
export const openRfqFromOrder = (wo: number) => post<{ rfq: { id: number }; message: string }>(`/api/rfqs/from-work-order/${wo}`)
export const recordQuote = (id: number, b: Record<string, unknown>) => post<{ message: string; quote_id: number }>(`/api/rfqs/${id}/quotes`, b)
export const awardRfq = (id: number, b: { mode: string; supplier_name: string; reason: string; awards?: { rfq_line_id: number; supplier_name: string }[] }) => post<{ message: string }>(`/api/rfqs/${id}/award`, b)

/** Keep the supplier's own quotation file with his quote. */
export const keepQuoteDocument = (id: number, quoteId: number, file: File) => {
  const form = new FormData()
  form.append('file', file)
  return api<{ message: string }>(`/api/rfqs/${id}/quotes/${quoteId}/document`, { method: 'POST', body: form })
}
export const inviteSupplier = (id: number, b: { supplier_name: string; phone?: string; email?: string }) => post<{ invite: RfqInvite; message: string }>(`/api/rfqs/${id}/invites`, b)
export const withdrawInvite = (id: number, inviteId: number) => api<{ message: string }>(`/api/rfqs/${id}/invites/${inviteId}`, { method: 'DELETE' })
/** The server emails the supplier his link (again). */
export const emailInvite = (id: number, inviteId: number) => post<{ message: string; invite: RfqInvite }>(`/api/rfqs/${id}/invites/${inviteId}/email`)

/** The full address of a supplier's link, for sending. */
export const inviteUrl = (inv: RfqInvite) => `${window.location.origin}${inv.link}`

/** A WhatsApp message to the supplier with his link: opens WhatsApp, nothing is sent until the buyer presses send. */
export function whatsappLink(inv: RfqInvite, company: string, rfq: Rfq) {
  const digits = (inv.phone || '').replace(/\D/g, '')
  const to = digits.length === 10 ? `91${digits}` : digits
  const text = `Dear ${inv.supplier_name},\n\n${company ? `${company} requests` : 'Please send'} your quotation for ${rfq.title} (${rfq.number})${rfq.needed_by ? `, needed by ${rfq.needed_by}` : ''}.\n\nSee the items and send your rates or your quotation file (PDF, Word, Excel or a photo) here:\n${inviteUrl(inv)}\n\nThank you.`
  return `https://wa.me/${to}?text=${encodeURIComponent(text)}`
}

export function emailLink(inv: RfqInvite, company: string, rfq: Rfq) {
  const subject = `Request for quotation ${rfq.number}: ${rfq.title}`
  const body = `Dear ${inv.supplier_name},\n\n${company || 'We'} request your quotation for ${rfq.title} (${rfq.number})${rfq.needed_by ? `, needed by ${rfq.needed_by}` : ''}.\n\nSee the items and send your rates or your quotation file (PDF, Word, Excel or a photo) here:\n${inviteUrl(inv)}\n\nThank you.`
  return `mailto:${encodeURIComponent(inv.email || '')}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`
}

// --- the supplier's side: the page his link opens, no login ------------------------------------------------------

export interface VendorQuotePage {
  company: string
  supplier_name: string
  rfq: { number: string; title: string; project: string; site: string; needed_by: string; notes: string }
  open: boolean
  lines: { rfq_line_id: number; item_code: string; description: string; uom: string; qty: number; rate?: number; tax_percent?: number; remarks?: string }[]
  answer: { quote_ref: string; quote_date: string; delivery_days: number; payment_terms: string; freight: number; valid_until: string; notes: string } | null
  submitted_at: string
  document_sent: boolean
  can_read: boolean
  accept: string
}

export const vendorQuotePage = (token: string) => api<VendorQuotePage>(`/api/vendor-quote/${encodeURIComponent(token)}`, { quiet: true })
export const vendorReadQuote = (token: string, file: File) => {
  const form = new FormData()
  form.append('file', file)
  return api<{ available: boolean; message?: string; quote_ref?: string; quote_date?: string; valid_until?: string; delivery_days?: number; payment_terms?: string; freight?: number; lines?: { rfq_line_id: number; rate: number; tax_percent: number | null; remarks: string }[]; lines_priced?: number; lines_in_enquiry?: number; low_confidence?: boolean }>(`/api/vendor-quote/${encodeURIComponent(token)}/read`, { method: 'POST', body: form, quiet: true })
}
export const vendorSendQuote = (token: string, quote: Record<string, unknown>, file: File | null) => {
  const form = new FormData()
  form.append('quote', JSON.stringify(quote))
  if (file) form.append('file', file)
  return api<{ ok: boolean; message: string }>(`/api/vendor-quote/${encodeURIComponent(token)}`, { method: 'POST', body: form, quiet: true })
}

/** What a quotation file can be: shown in every file chooser for quotes. */
export const QUOTE_FILES = '.pdf,.doc,.docx,.docm,.xls,.xlsx,.xlsm,.csv,.txt,.rtf,.odt,.ods,.jpg,.jpeg,.png,.webp,.gif,.bmp,.tif,.tiff,image/*'

// --- quotation files kept on their own, to open side by side ------------------------------------------------------

/** A supplier's quotation kept on its own, not on any enquiry: nothing is read from it, it is there to be looked at. */
export interface QuoteFile { id: number; name: string; content_type: string; size: number; supplier_name: string; added_by: string; added_at: string; url: string }
export const quoteFileKeys = { all: ['quote-files'] as const }
export const useQuoteFiles = () => useQuery({ queryKey: quoteFileKeys.all, queryFn: () => get<{ files: QuoteFile[] }>('/api/quote-files') })
export const addQuoteFile = (file: File, supplier: string) => {
  const form = new FormData()
  form.append('file', file)
  form.append('supplier_name', supplier)
  return api<{ message: string; file: { id: number; name: string } }>('/api/quote-files', { method: 'POST', body: form })
}
export const removeQuoteFile = (id: number) => api<{ ok: boolean }>(`/api/quote-files/${id}`, { method: 'DELETE' })
/** A Word or Excel quotation as text, for reading beside the others (a PDF or a photo is shown as it is). */
export const useQuoteFileText = (id: number, enabled: boolean) =>
  useQuery({ queryKey: ['quote-files', 'text', id], enabled, staleTime: Infinity, queryFn: () => get<{ text: string; kind: string }>(`/api/quote-files/${id}/text`) })
