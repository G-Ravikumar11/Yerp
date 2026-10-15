import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { ArrowRight, ArrowUpToLine, Brush, Car, ChevronDown, CircleCheck, CircleX, ClipboardCheck, Download, GraduationCap, Hand, HardHat, Info, Printer, RotateCcw, ShieldCheck, Siren, TriangleAlert } from 'lucide-react'
import { ProjectPicker } from '@/components/data/ProjectPicker'
import { Badge, Button, Skeleton } from '@/components/ui'
import { useHseCheck, type HseCheckItem, type HseGo } from '@/api/safety'
import { cn } from '@/lib/utils'
import { CHECKS, EMERGENCIES, HSE_DOC, PERMITS, PPE, PPE_ALWAYS, ROLES, RULES, TOPICS, type RuleIcon } from './hseContent'

const RULE_ICON: Record<RuleIcon, typeof HardHat> = { helmet: HardHat, height: ArrowUpToLine, permit: ClipboardCheck, brief: GraduationCap, report: TriangleAlert, vehicle: Car, clean: Brush, stop: Hand }
const pdfUrl = `${import.meta.env.BASE_URL}${HSE_DOC.pdf}`
const SECTIONS = [
  ['hse-check', 'Site check'], ['hse-rules', 'Rules'], ['hse-ppe', 'What to wear'], ['hse-permit', 'Permits'],
  ['hse-emergency', 'Emergencies'], ['hse-roles', 'Who does what'], ['hse-checks', 'Regular checks'], ['hse-topics', 'Safe work'],
] as const

/** The company's HSE plan, said plainly - and the chosen site held up against it, from what is already recorded. */
export function HseTab({ job, setJob, onGo, onNewPermit }: { job: number; setJob: (j: number) => void; onGo: (go: HseGo) => void; onNewPermit: () => void }) {
  const [printing, setPrinting] = useState(false)
  useEffect(() => {
    if (!printing) return
    document.body.classList.add('printing-hse')
    const done = () => { document.body.classList.remove('printing-hse'); setPrinting(false) }
    window.addEventListener('afterprint', done, { once: true })
    const t = window.setTimeout(() => window.print(), 50)
    return () => { window.clearTimeout(t); window.removeEventListener('afterprint', done); document.body.classList.remove('printing-hse') }
  }, [printing])

  return (
    <div className="grid gap-8">
      <section className="flex flex-wrap items-center gap-4 rounded-xl border border-border bg-card p-5 shadow-card">
        <span className="grid size-12 shrink-0 place-items-center rounded-xl bg-success-soft text-success"><ShieldCheck className="size-6" /></span>
        <div className="min-w-56 flex-1">
          <h2 className="text-lg font-semibold">{HSE_DOC.title}, the short version</h2>
          <p className="text-[13px] text-muted-foreground">The 52-page plan in plain words. Doc. {HSE_DOC.number}, {HSE_DOC.date}.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => setPrinting(true)}><Printer /> Print site rules</Button>
          <Button variant="outline" asChild><a href={pdfUrl} target="_blank" rel="noopener" download="Yalavarti Infra HSE Plan.pdf"><Download /> Full plan (PDF)</a></Button>
        </div>
        <nav aria-label="On this page" className="flex w-full flex-wrap gap-1.5 border-t border-border pt-3">
          {SECTIONS.map(([id, label]) => <a key={id} href={`#${id}`} className="rounded-full border border-border px-3 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground">{label}</a>)}
        </nav>
      </section>

      <SiteCheck job={job} setJob={setJob} onGo={onGo} />

      <Section id="hse-rules" title="Rules for everyone" sub="If people remember only one part of the plan, it should be this.">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {RULES.map((r) => {
            const Icon = RULE_ICON[r.icon]
            return (
              <div key={r.title} className="rounded-xl border border-border bg-card p-4 shadow-card">
                <span className="mb-3 grid size-10 place-items-center rounded-lg bg-primary-soft text-primary"><Icon className="size-5" /></span>
                <h4 className="font-semibold leading-snug">{r.title}</h4>
                <p className="mt-1 text-[13px] text-muted-foreground">{r.text}</p>
                <p className="mt-2 text-[11px] text-subtle">Plan {r.ref}</p>
              </div>
            )
          })}
        </div>
      </Section>

      <Section id="hse-ppe" title="What to wear" sub="Plan 9.1, table 1.">
        <p className="mb-3 flex items-center gap-2 rounded-lg bg-primary-soft px-3 py-2.5 text-sm font-medium text-primary"><HardHat className="size-4 shrink-0" /> {PPE_ALWAYS}</p>
        <div className="overflow-hidden rounded-xl border border-border">
          <table className="w-full text-left text-sm">
            <thead className="bg-muted/60 text-xs uppercase tracking-wide text-muted-foreground"><tr><th className="px-3 py-2 font-medium">The work</th><th className="px-3 py-2 font-medium">Wear</th></tr></thead>
            <tbody>{PPE.map((p) => <tr key={p.work} className="border-t border-border"><td className="px-3 py-2 align-top font-medium">{p.work}</td><td className="px-3 py-2 text-muted-foreground">{p.wear}</td></tr>)}</tbody>
          </table>
        </div>
      </Section>

      <Section id="hse-permit" title="Do I need a permit?" sub="Plan 5.4 and its flowchart, as a few questions.">
        <div className="grid gap-4 lg:grid-cols-[1.1fr_1fr]">
          <PermitQuestions onNewPermit={onNewPermit} />
          <div className="rounded-xl border border-border bg-card p-4 shadow-card">
            <h4 className="mb-2 text-sm font-semibold">The permits</h4>
            <ul className="grid gap-2.5">{PERMITS.map((p) => <li key={p.name} className="text-[13px]"><span className="font-medium">{p.name}</span><span className="text-muted-foreground"> - {p.when}</span></li>)}</ul>
            <p className="mt-3 text-xs text-muted-foreground">Keep the permit at the work spot until the job is done, then close it.</p>
          </div>
        </div>
      </Section>

      <Section id="hse-emergency" title="In an emergency" sub="Plan 8.4 and 14. Read these out at a toolbox talk.">
        <div className="grid gap-3 lg:grid-cols-3">
          {EMERGENCIES.map((e) => (
            <div key={e.title} className={cn('rounded-xl border border-border border-t-4 bg-card p-4 shadow-card', e.tone === 'danger' ? 'border-t-danger' : e.tone === 'warning' ? 'border-t-warning' : 'border-t-info')}>
              <h4 className="mb-2 flex items-center gap-2 font-semibold"><Siren className={cn('size-4', e.tone === 'danger' ? 'text-danger' : e.tone === 'warning' ? 'text-warning' : 'text-info')} /> {e.title}</h4>
              <ol className="grid gap-1.5">{e.steps.map((s, i) => <li key={i} className="flex gap-2 text-[13px]"><span className="tabular grid size-5 shrink-0 place-items-center rounded-full bg-muted text-[11px] font-semibold">{i + 1}</span><span>{s}</span></li>)}</ol>
              {e.note && <p className="mt-3 rounded-lg bg-danger-soft p-2.5 text-xs text-danger">{e.note}</p>}
            </div>
          ))}
        </div>
      </Section>

      <Section id="hse-roles" title="Who does what" sub="Plan 4.">
        <div className="grid gap-4 lg:grid-cols-[16rem_1fr]">
          <div aria-label="Safety organisation" className="flex flex-col items-center gap-1 rounded-xl border border-border bg-card p-4 text-center text-[13px] shadow-card">
            <Box>Project Manager</Box><Down />
            <div className="flex items-center gap-2"><Box>Safety Manager</Box><span className="text-subtle">-</span><Box muted>Project Nurse</Box></div><Down />
            <Box>Safety Engineer</Box><Down />
            <div className="flex gap-2"><Box muted>Safety Officer</Box><Box muted>Safety Officer</Box></div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {ROLES.map((r) => (
              <div key={r.who} className="rounded-xl border border-border bg-card p-4 shadow-card">
                <h4 className="mb-1.5 text-sm font-semibold">{r.who}</h4>
                <ul className="grid gap-1 text-[13px] text-muted-foreground">{r.does.map((d) => <li key={d} className="flex gap-2"><span className="mt-2 size-1 shrink-0 rounded-full bg-subtle" />{d}</li>)}</ul>
              </div>
            ))}
          </div>
        </div>
      </Section>

      <Section id="hse-checks" title="Regular checks" sub="Plan 5.3, 5.5, 9.2, 9.3.6 and 12.">
        <div className="grid gap-2">
          {CHECKS.map((c) => (
            <div key={c.when} className="flex flex-wrap gap-x-4 gap-y-1 rounded-xl border border-border bg-card px-4 py-3 shadow-card">
              <span className="w-28 shrink-0"><Badge tone="info">{c.when}</Badge></span>
              <span className="min-w-0 flex-1 text-[13px]">{c.what}</span>
            </div>
          ))}
        </div>
      </Section>

      <Section id="hse-topics" title="Safe work, topic by topic" sub="Open the one you need.">
        <div className="grid gap-2 lg:grid-cols-2">
          {TOPICS.map((t) => (
            <details key={t.title} className="group rounded-xl border border-border bg-card shadow-card">
              <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-3 [&::-webkit-details-marker]:hidden">
                <span className="flex-1 font-medium">{t.title}</span>
                <span className="text-[11px] text-subtle">Plan {t.ref}</span>
                <ChevronDown className="size-4 text-muted-foreground transition-transform group-open:rotate-180" />
              </summary>
              <ul className="grid gap-1.5 border-t border-border px-4 py-3 text-[13px]">{t.points.map((p) => <li key={p} className="flex gap-2"><CircleCheck className="mt-0.5 size-3.5 shrink-0 text-success" />{p}</li>)}</ul>
            </details>
          ))}
        </div>
      </Section>

      <footer className="rounded-xl border border-border bg-muted/40 p-4 text-xs text-muted-foreground">
        <p className="font-medium text-foreground">{HSE_DOC.title} - Doc. {HSE_DOC.number}, {HSE_DOC.date}</p>
        <p className="mt-1">Prepared by {HSE_DOC.prepared}. Reviewed by {HSE_DOC.reviewed}. Approved by {HSE_DOC.approved}.</p>
        <p className="mt-1">This page is a summary. Where it and the full plan differ, the full plan is what counts.</p>
      </footer>

      <HsePoster />
    </div>
  )
}

function Section({ id, title, sub, children }: { id: string; title: string; sub?: string; children: React.ReactNode }) {
  return (
    <section id={id} className="scroll-mt-20">
      <h3 className="text-base font-semibold">{title}</h3>
      {sub && <p className="mb-3 text-[13px] text-muted-foreground">{sub}</p>}
      {children}
    </section>
  )
}

const Box = ({ children, muted }: { children: React.ReactNode; muted?: boolean }) => <span className={cn('rounded-lg border px-3 py-1.5 font-medium', muted ? 'border-border bg-muted/50' : 'border-primary/30 bg-primary-soft text-primary')}>{children}</span>
const Down = () => <span className="text-subtle">|</span>

const STATUS = {
  ok: { icon: CircleCheck, cls: 'text-success', tone: 'success', word: 'In order' },
  warn: { icon: TriangleAlert, cls: 'text-warning', tone: 'warning', word: 'Needs a look' },
  bad: { icon: CircleX, cls: 'text-danger', tone: 'danger', word: 'Act now' },
  info: { icon: Info, cls: 'text-info', tone: 'info', word: 'Note' },
} as const
const GO_LABEL: Record<HseGo, string> = { workers: 'Workers', incidents: 'Incidents', talks: 'Toolbox talks', permits: 'Permits' }

function SiteCheck({ job, setJob, onGo }: { job: number; setJob: (j: number) => void; onGo: (go: HseGo) => void }) {
  const q = useHseCheck(job)
  const d = q.data
  const pct = d && d.total ? Math.round((d.ok / d.total) * 100) : 0
  return (
    <Section id="hse-check" title="This site against the plan" sub="Worked out from what is already recorded here - nothing extra to fill in.">
      <div className="rounded-xl border border-border bg-card p-4 shadow-card">
        <div className="mb-4 flex flex-wrap items-end gap-4">
          <div className="min-w-64 flex-1 sm:max-w-md"><ProjectPicker value={job} onChange={setJob} id="hse-job" allowAll /></div>
          {d && (
            <div className="ml-auto min-w-48 text-right">
              <div className="text-sm"><span className="tabular text-2xl font-semibold">{d.ok}</span><span className="text-muted-foreground"> of {d.total} in order</span></div>
              <div className="mt-1 h-2 overflow-hidden rounded-full bg-muted"><div className={cn('h-full rounded-full', pct === 100 ? 'bg-success' : pct >= 60 ? 'bg-warning' : 'bg-danger')} style={{ width: `${pct}%` }} /></div>
            </div>
          )}
        </div>
        {q.isPending ? <Skeleton className="h-48 w-full" /> : q.error ? <p role="alert" className="text-sm text-danger">{q.error.message}</p> : (
          <ul className="grid gap-2">{d?.items.map((it) => <CheckRow key={it.key} it={it} onGo={onGo} />)}</ul>
        )}
      </div>
    </Section>
  )
}

function CheckRow({ it, onGo }: { it: HseCheckItem; onGo: (go: HseGo) => void }) {
  const s = STATUS[it.status]
  return (
    <li className="flex flex-wrap items-center gap-3 rounded-lg border border-border px-3 py-2.5">
      <s.icon className={cn('size-5 shrink-0', s.cls)} />
      <div className="min-w-48 flex-1">
        <div className="text-sm font-medium">{it.label} <span className="text-[11px] font-normal text-subtle">Plan {it.rule}</span></div>
        <div className="text-[13px] text-muted-foreground">{it.detail}</div>
      </div>
      <Badge tone={s.tone}>{s.word}</Badge>
      {it.status !== 'ok' && <Button size="sm" variant="ghost" onClick={() => onGo(it.go)}>{GO_LABEL[it.go]} <ArrowRight /></Button>}
    </li>
  )
}

type Step = 'type' | 'risk' | 'assess' | 'left' | 'method' | 'write' | 'still' | 'need' | 'none'
const QUESTIONS: Partial<Record<Step, { q: string; hint?: string; yes: Step; no: Step }>> = {
  type: { q: 'Is it hot work, work above 1.8 m, work on live electrics, or digging?', hint: 'Welding, cutting, grinding and open flame are all hot work.', yes: 'need', no: 'risk' },
  risk: { q: 'Has a risk assessment been done for this job?', yes: 'left', no: 'assess' },
  left: { q: 'With your safety measures in place, is there still a serious risk?', yes: 'method', no: 'none' },
  method: { q: 'Is there a written safe method of work for this job?', yes: 'still', no: 'write' },
  still: { q: 'With the safe method followed, is there still a serious risk, or does it need more measures?', yes: 'need', no: 'none' },
}
const PAUSES: Partial<Record<Step, { text: string; next: Step }>> = {
  assess: { text: 'Do a risk assessment first: write down what could go wrong and what will stop it. Then carry on.', next: 'left' },
  write: { text: 'Write a safe method of work first, to control the risks that are left. Then carry on.', next: 'still' },
}

function PermitQuestions({ onNewPermit }: { onNewPermit: () => void }) {
  const [step, setStep] = useState<Step>('type')
  const q = QUESTIONS[step]
  const pause = PAUSES[step]
  return (
    <div className="rounded-xl border border-border bg-card p-4 shadow-card">
      {q && (
        <>
          <p className="font-medium">{q.q}</p>
          {q.hint && <p className="mt-1 text-[13px] text-muted-foreground">{q.hint}</p>}
          <div className="mt-4 flex gap-2"><Button onClick={() => setStep(q.yes)}>Yes</Button><Button variant="outline" onClick={() => setStep(q.no)}>No</Button></div>
        </>
      )}
      {pause && (
        <>
          <p className="flex gap-2 rounded-lg bg-warning-soft p-3 text-[13px]"><TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning" />{pause.text}</p>
          <Button className="mt-4" variant="outline" onClick={() => setStep(pause.next)}>Done - carry on</Button>
        </>
      )}
      {step === 'need' && (
        <>
          <p className="flex items-center gap-2 text-lg font-semibold text-danger"><ClipboardCheck className="size-5" /> You need a permit to work.</p>
          <p className="mt-1 text-[13px] text-muted-foreground">Ask a supervisor to issue it before anyone starts.</p>
          <Button className="mt-4" onClick={onNewPermit}>Issue a permit <ArrowRight /></Button>
        </>
      )}
      {step === 'none' && (
        <>
          <p className="flex items-center gap-2 text-lg font-semibold text-success"><CircleCheck className="size-5" /> No permit needed.</p>
          <p className="mt-1 text-[13px] text-muted-foreground">Keep following the safety measures and the PPE rules.</p>
        </>
      )}
      {step !== 'type' && <Button className="mt-4 ml-2" size="sm" variant="ghost" onClick={() => setStep('type')}><RotateCcw /> Start again</Button>}
    </div>
  )
}

const POSTER_CSS = `
#hse-print-root { display: none; }
@media print {
  @page { size: A4 portrait; margin: 0; }
  html, body { background: #fff !important; margin: 0 !important; padding: 0 !important; height: auto !important; }
  body.printing-hse > *:not(#hse-print-root) { display: none !important; }
  body.printing-hse #hse-print-root { display: block !important; }
}
#hse-print-root { color: #111; background: #fff; font: 10.5pt/1.35 "Segoe UI", Arial, sans-serif; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
#hse-print-root .pp { padding: 12mm 13mm; width: 210mm; box-sizing: border-box; }
#hse-print-root .pp-head { display: flex; align-items: center; gap: 6mm; border-bottom: 2pt solid #0b2a52; padding-bottom: 4mm; margin-bottom: 5mm; }
#hse-print-root .pp-head img { height: 20mm; }
#hse-print-root h1 { margin: 0; font-size: 24pt; color: #0b2a52; letter-spacing: .02em; }
#hse-print-root .pp-sub { margin: 1mm 0 0; font-size: 9pt; color: #444; }
#hse-print-root .pp-always { background: #fde68a; border: 1pt solid #b45309; padding: 3mm 4mm; font-weight: 700; font-size: 12pt; margin-bottom: 5mm; }
#hse-print-root .pp-rules { display: grid; grid-template-columns: 1fr 1fr; gap: 3.5mm 6mm; margin-bottom: 6mm; }
#hse-print-root .pp-rule { display: flex; gap: 3mm; break-inside: avoid; }
#hse-print-root .pp-n { flex: none; width: 8mm; height: 8mm; border-radius: 50%; background: #0b2a52; color: #fff; font-weight: 700; display: grid; place-items: center; font-size: 11pt; }
#hse-print-root .pp-rule b { display: block; font-size: 11.5pt; }
#hse-print-root .pp-rule span { font-size: 9.5pt; color: #333; }
#hse-print-root .pp-em { display: grid; grid-template-columns: 1fr 1fr; gap: 5mm; }
#hse-print-root .pp-box { border: 1.2pt solid #b91c1c; padding: 3mm 4mm; break-inside: avoid; }
#hse-print-root .pp-box h2 { margin: 0 0 2mm; font-size: 12.5pt; color: #b91c1c; }
#hse-print-root .pp-box ol { margin: 0; padding-left: 5mm; font-size: 9.5pt; }
#hse-print-root .pp-box li { margin-bottom: 1mm; }
#hse-print-root .pp-foot { margin-top: 6mm; padding-top: 2mm; border-top: .75pt solid #999; font-size: 8pt; color: #555; display: flex; justify-content: space-between; }
`

/** One A4 sheet for the site notice board: the rules, what to wear always, and what to do if someone is hurt or there is a fire. */
function HsePoster() {
  const hurt = EMERGENCIES[0]
  const fire = EMERGENCIES[1]
  return createPortal(
    <div id="hse-print-root">
      <style>{POSTER_CSS}</style>
      <div className="pp">
        <div className="pp-head">
          <img src={`${import.meta.env.BASE_URL}logo.png`} alt="" />
          <div><h1>SITE SAFETY RULES</h1><p className="pp-sub">Everyone on this site follows these rules. From the {HSE_DOC.title}.</p></div>
        </div>
        <div className="pp-always">{PPE_ALWAYS}</div>
        <div className="pp-rules">
          {RULES.map((r, i) => <div key={r.title} className="pp-rule"><span className="pp-n">{i + 1}</span><div><b>{r.title}</b><span>{r.text}</span></div></div>)}
        </div>
        <div className="pp-em">
          <div className="pp-box"><h2>IF SOMEONE IS HURT</h2><ol>{hurt.steps.map((s) => <li key={s}>{s}</li>)}</ol></div>
          <div className="pp-box"><h2>IF THERE IS A FIRE</h2><ol>{fire.steps.map((s) => <li key={s}>{s}</li>)}</ol></div>
        </div>
        <div className="pp-foot"><span>Doc. {HSE_DOC.number} - {HSE_DOC.date}</span><span>Approved by {HSE_DOC.approved}</span></div>
      </div>
    </div>,
    document.body,
  )
}
