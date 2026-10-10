import { useEffect, useState } from 'react'
import { Button, Field, Input, Textarea } from '@/components/ui'
import { api, ApiError } from '@/lib/api'
import { AuthLayout, Notice } from '@/features/auth/AuthLayout'

interface FormField { label: string; type?: string; required?: boolean; options?: string }
interface FormDef { title: string; description?: string; fields: string | FormField[] }
interface Attached { name: string; type: string; size: number; data: string }

const MAX_FILES = 6
const MAX_MB = 5
const ALLOWED = ['pdf', 'doc', 'docx', 'png', 'jpg', 'jpeg', 'webp', 'txt']

/** The public application form a company's job link opens: its own questions, and up to six documents. */
export default function ApplyPage() {
  const token = new URLSearchParams(window.location.search).get('token')
  const [form, setForm] = useState<FormDef | null>(null)
  const [fields, setFields] = useState<FormField[]>([])
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [files, setFiles] = useState<Attached[]>([])
  const [error, setError] = useState(token ? '' : 'No form link provided.')
  const [fatal, setFatal] = useState(!token)
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState(false)

  useEffect(() => {
    if (!token) return
    api<FormDef>('/api/recruitment/form/' + token, { quiet: true })
      .then((d) => { setForm(d); setFields(typeof d.fields === 'string' ? JSON.parse(d.fields) : d.fields || []) })
      .catch(() => { setFatal(true); setError('Form not found or no longer active.') })
  }, [token])

  const attach = (list: FileList | null) => {
    for (const file of Array.from(list ?? [])) {
      const ext = (file.name.split('.').pop() || '').toLowerCase()
      if (files.length >= MAX_FILES) { setError(`You can attach at most ${MAX_FILES} files.`); break }
      if (!ALLOWED.includes(ext)) { setError(`"${file.name}" is not an accepted file type.`); continue }
      if (file.size > MAX_MB * 1024 * 1024) { setError(`"${file.name}" is larger than ${MAX_MB} MB.`); continue }
      const reader = new FileReader()
      reader.onload = () => setFiles((fs) => (fs.some((f) => f.name === file.name && f.size === file.size) ? fs : [...fs, { name: file.name, type: file.type, size: file.size, data: String(reader.result).split(',')[1] }]))
      reader.readAsDataURL(file)
    }
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    const clean = Object.fromEntries(fields.map((f) => [f.label, (answers[f.label] ?? '').trim()]))
    const email = fields.find((f) => f.type === 'email')
    const name = fields.find((f) => f.label.toLowerCase().includes('name'))
    const body: Record<string, unknown> = { answers: JSON.stringify(clean), candidate_name: name ? clean[name.label] : '', candidate_email: email ? clean[email.label] : '' }
    if (files.length) body.documents = files.map((f, n) => ({ doc_type: n === 0 ? 'resume' : 'supporting', file_name: f.name, file_type: f.type, file_data: f.data }))
    try {
      await api(`/api/recruitment/form/${token}/submit`, { method: 'POST', body, quiet: true })
      setSent(true)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Network error. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  if (sent) return <AuthLayout title="Application submitted" mark="✓"><p className="text-center text-sm text-muted-foreground">Thank you for your application. We&apos;ll review it and get back to you soon.</p></AuthLayout>
  if (fatal) return <AuthLayout title="Application form"><Notice tone="error">{error}</Notice></AuthLayout>
  if (!form) return <AuthLayout title="Application form"><p className="py-6 text-center text-sm text-muted-foreground">Loading application form...</p></AuthLayout>

  return (
    <main className="mx-auto min-h-screen max-w-xl bg-background px-4 py-10">
      <h1 className="text-2xl font-bold">{form.title}</h1>
      {form.description && <p className="mb-5 mt-1 text-sm text-muted-foreground">{form.description}</p>}
      <form onSubmit={submit} className="mt-5 grid gap-4 rounded-xl border border-border bg-card p-6">
        {fields.map((f, i) => {
          const id = `field-${i}`
          const label = f.label + (f.required ? ' *' : '')
          const set = (v: string) => setAnswers((a) => ({ ...a, [f.label]: v }))
          if (f.type === 'file') return (
            <Field key={id} label={label} htmlFor={id} hint={`Up to ${MAX_FILES} files (CV, cover letter, certificates). PDF, Word, images or text, ${MAX_MB} MB each.`}>
              <div className="grid gap-2">
                <input id={id} type="file" multiple accept=".pdf,.doc,.docx,.png,.jpg,.jpeg,.webp,.txt" onChange={(e) => { attach(e.target.files); e.target.value = '' }} />
                {files.map((fl, n) => <div key={fl.name} className="flex items-center justify-between rounded-md bg-muted px-3 py-1.5 text-sm"><span className="truncate">{fl.name}</span><span className="flex items-center gap-3 text-xs text-muted-foreground">{(fl.size / 1024).toFixed(0)} KB<button type="button" aria-label={`Remove ${fl.name}`} onClick={() => setFiles((fs) => fs.filter((_, k) => k !== n))}>&times;</button></span></div>)}
              </div>
            </Field>
          )
          if (f.type === 'textarea') return <Field key={id} label={label} htmlFor={id}><Textarea id={id} rows={3} required={f.required} value={answers[f.label] ?? ''} onChange={(e) => set(e.target.value)} /></Field>
          if (f.type === 'select') return (
            <Field key={id} label={label} htmlFor={id}>
              <select id={id} required={f.required} value={answers[f.label] ?? ''} onChange={(e) => set(e.target.value)} className="h-10 w-full rounded-md border border-input bg-transparent px-3 text-sm">
                <option value="">Select...</option>
                {(f.options || '').split(',').map((o) => o.trim()).filter(Boolean).map((o) => <option key={o}>{o}</option>)}
              </select>
            </Field>
          )
          return <Field key={id} label={label} htmlFor={id}><Input id={id} type={f.type === 'email' ? 'email' : f.type === 'phone' ? 'tel' : 'text'} required={f.required} value={answers[f.label] ?? ''} onChange={(e) => set(e.target.value)} /></Field>
        })}
        {error && <Notice tone="error">{error}</Notice>}
        <Button type="submit" loading={busy}>Submit application</Button>
      </form>
    </main>
  )
}
