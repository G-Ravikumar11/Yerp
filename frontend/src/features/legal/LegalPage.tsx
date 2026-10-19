import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { appUrl } from '@/lib/paths'

// Placeholder details: fill these in, and have the text reviewed, before relying on it.
const COMPANY = 'Yalavarti Projects Pvt. Ltd.'
const UPDATED = '[Date]'
const CONTACT = '[email]'

type Section = { heading: string; body: string[] }

const TERMS: Section[] = [
  { heading: '1. Acceptance of these terms', body: [`These Terms of Service govern your use of Y ERP, provided by ${COMPANY} By signing in or using the service you agree to them. If you do not agree, do not use the service.`] },
  { heading: '2. The service', body: ['Y ERP is a construction management system for measurement books, work orders, billing, stores, site records and related work. Features may change from time to time.'] },
  { heading: '3. Accounts', body: ['Accounts are issued by your company administrator. You are responsible for keeping your sign-in details private and for everything done under your account. Tell us at once if you think your account has been used without your permission.'] },
  { heading: '4. Your data', body: ['The records you and your company enter remain yours. You allow us to store and process them only as needed to run the service for you. Your company administrator decides who in your company can see or change them.'] },
  { heading: '5. Acceptable use', body: ['Do not misuse the service: do not try to break into it, interfere with it, copy it, or use it to break the law or the rights of others.'] },
  { heading: '6. Availability', body: ['We aim to keep the service available but do not promise it will be uninterrupted or free of errors. We may suspend it for maintenance.'] },
  { heading: '7. Limits of liability', body: ['To the extent the law allows, we are not liable for indirect or consequential loss arising from use of the service. Keep your own checks on figures that matter, such as bills and payments.'] },
  { heading: '8. Changes to these terms', body: ['We may update these terms. The date at the top shows when they last changed. Using the service after a change means you accept the new terms.'] },
  { heading: '9. Governing law', body: ['These terms are governed by the laws of India. [Court or city to be confirmed.]'] },
  { heading: '10. Contact', body: [`Questions about these terms: ${CONTACT}.`] },
]

const PRIVACY: Section[] = [
  { heading: '1. Who we are', body: [`This Privacy Policy explains how ${COMPANY} handles personal information in Y ERP.`] },
  { heading: '2. What we collect', body: ['Account details such as name, work email, phone number and role. Records you enter, such as attendance, measurements, bills and site diaries. Technical data such as sign-in times and error logs.'] },
  { heading: '3. How we use it', body: ['To run the service, secure accounts, support users, fix faults and meet legal and tax duties. We do not sell personal information.'] },
  { heading: '4. Who can see it', body: ['People in your company, according to the access your administrator gives them. Service providers who host or support the system, under duties to protect it. Authorities where the law requires it.'] },
  { heading: '5. Cookies and local storage', body: ['We use a sign-in cookie and store some data on your device so the app works with a weak connection. We do not use advertising cookies.'] },
  { heading: '6. Security and keeping data', body: ['We protect data with access controls and encrypted connections. We keep records for as long as your company uses the service and as the law requires, then delete or anonymise them.'] },
  { heading: '7. Your rights', body: ['You can ask to see, correct or delete personal information we hold about you, subject to legal limits. Ask your company administrator first, or contact us.'] },
  { heading: '8. Changes to this policy', body: ['We may update this policy. The date at the top shows when it last changed.'] },
  { heading: '9. Contact', body: [`Questions about privacy: ${CONTACT}.`] },
]

/** A plain page of text for the Terms of Service or the Privacy Policy: no cards, no decoration. */
export function LegalPage({ kind }: { kind: 'terms' | 'privacy' }) {
  const terms = kind === 'terms'
  const title = terms ? 'Terms of Service' : 'Privacy Policy'
  const sections = terms ? TERMS : PRIVACY
  useEffect(() => { document.title = `${title} - Y ERP` }, [title])
  return (
    <main className="min-h-screen bg-background px-6 py-12">
      <article className="mx-auto max-w-2xl">
        <Link to="/login" className="text-sm text-muted-foreground hover:underline">Back to sign in</Link>
        <h1 className="mt-6 text-2xl font-semibold text-foreground">{title}</h1>
        <p className="mt-1 text-sm text-muted-foreground">Last updated: {UPDATED}</p>
        <p className="mt-6 text-[15px] leading-relaxed text-body">{title} for {COMPANY} Last updated: {UPDATED}. Contact: {CONTACT}.</p>
        {sections.map((s) => (
          <section key={s.heading} className="mt-8">
            <h2 className="text-base font-semibold text-foreground">{s.heading}</h2>
            {s.body.map((t) => <p key={t} className="mt-2 text-[15px] leading-relaxed text-body">{t}</p>)}
          </section>
        ))}
        <p className="mt-10 text-sm text-muted-foreground">
          <a href={appUrl(terms ? 'privacy' : 'terms')} className="hover:underline">{terms ? 'Privacy Policy' : 'Terms of Service'}</a>
        </p>
      </article>
    </main>
  )
}

export const TermsPage = () => <LegalPage kind="terms" />
export const PrivacyPage = () => <LegalPage kind="privacy" />
