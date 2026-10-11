import { useEffect, useState } from 'react'
import { Button, Field, Input } from '@/components/ui'
import { api, ApiError } from '@/lib/api'
import { AuthLayout, Notice } from './AuthLayout'
import { appUrl } from '@/lib/paths'

interface Profile {
  is_onboarded?: boolean
  company_name?: string
  contact_name?: string
  phone_number?: string
  address?: string
  website?: string
  abn?: string
  industry?: string
}

const MAX_LOGO = 2 * 1024 * 1024

/** First sign-in: three short steps - who the business is, where it is, and its logo. */
export default function OnboardPage() {
  const [step, setStep] = useState(1)
  const [form, setForm] = useState({ company_name: '', contact_name: '', phone_number: '', address: '', website: '', abn: '', industry: '' })
  const [logo, setLogo] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, [k]: e.target.value }))

  useEffect(() => {
    api<Profile>('/api/client/me', { quiet: true })
      .then((p) => {
        if (p.is_onboarded) return window.location.assign(appUrl())
        setForm((f) => ({ ...f, ...Object.fromEntries(Object.keys(f).map((k) => [k, (p as Record<string, string | undefined>)[k] ?? ''])) }))
      })
      .catch(() => window.location.assign(appUrl('login')))
  }, [])

  const ready = form.company_name.trim() !== '' && form.contact_name.trim() !== ''

  const pickLogo = (file?: File) => {
    if (!file) return
    if (file.size > MAX_LOGO) return setError('That file is too large. The most is 2 MB.')
    setError('')
    const reader = new FileReader()
    reader.onload = () => setLogo(String(reader.result))
    reader.readAsDataURL(file)
  }

  const finish = async (withLogo: boolean) => {
    setBusy(true)
    setError('')
    try {
      await api('/api/client/onboard', { method: 'POST', body: { ...form, logo_url: withLogo ? logo : '' } })
      window.location.assign(appUrl())
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not save. Try again.')
      setBusy(false)
    }
  }

  return (
    <AuthLayout title={step === 1 ? "Let's set up your business" : step === 2 ? 'Business details' : 'Your logo'} subtitle={step === 1 ? 'This takes a minute. Your details appear on documents and emails.' : undefined}>
      <div className="mb-6 flex gap-1.5" aria-label={`Step ${step} of 3`}>
        {[1, 2, 3].map((n) => <span key={n} className={`h-1 flex-1 rounded-full ${n <= step ? 'bg-primary' : 'bg-border'}`} />)}
      </div>
      {error && <Notice tone="error">{error}</Notice>}
      {step === 1 && (
        <form className="grid gap-4" onSubmit={(e) => { e.preventDefault(); if (ready) setStep(2) }}>
          <Field label="Business name *" htmlFor="ob-company"><Input id="ob-company" autoFocus value={form.company_name} onChange={set('company_name')} placeholder="Your company name" /></Field>
          <Field label="Your name *" htmlFor="ob-name"><Input id="ob-name" value={form.contact_name} onChange={set('contact_name')} /></Field>
          <Field label="Phone number" htmlFor="ob-phone"><Input id="ob-phone" value={form.phone_number} onChange={set('phone_number')} placeholder="+91 90000 00000" /></Field>
          <Button type="submit" disabled={!ready}>Continue</Button>
        </form>
      )}
      {step === 2 && (
        <div className="grid gap-4">
          <Field label="Business address" htmlFor="ob-address"><Input id="ob-address" value={form.address} onChange={set('address')} /></Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Website" htmlFor="ob-website"><Input id="ob-website" value={form.website} onChange={set('website')} placeholder="www.example.com" /></Field>
            <Field label="GSTIN / tax ID" htmlFor="ob-abn"><Input id="ob-abn" value={form.abn} onChange={set('abn')} /></Field>
          </div>
          <Field label="Industry" htmlFor="ob-industry"><Input id="ob-industry" value={form.industry} onChange={set('industry')} placeholder="e.g. Civil construction" /></Field>
          <div className="flex justify-between"><Button variant="ghost" onClick={() => setStep(1)}>Back</Button><Button onClick={() => setStep(3)}>Continue</Button></div>
        </div>
      )}
      {step === 3 && (
        <div className="grid gap-4">
          <label htmlFor="logo-file" className="grid cursor-pointer place-items-center gap-1 rounded-xl border-2 border-dashed border-border p-8 text-center text-sm text-muted-foreground hover:border-primary">
            <input id="logo-file" type="file" accept="image/*" className="sr-only" onChange={(e) => pickLogo(e.target.files?.[0])} />
            {logo ? <img src={logo} alt="Your logo" className="max-h-24" /> : <><span>Click to upload your logo</span><span className="text-xs">PNG, JPG or SVG, up to 2 MB.</span></>}
          </label>
          <div className="flex flex-wrap justify-between gap-2">
            <Button variant="ghost" onClick={() => setStep(2)}>Back</Button>
            <span className="flex gap-2"><Button variant="outline" disabled={busy} onClick={() => finish(false)}>Skip for now</Button><Button loading={busy} disabled={!logo} onClick={() => finish(true)}>Finish setup</Button></span>
          </div>
        </div>
      )}
    </AuthLayout>
  )
}
