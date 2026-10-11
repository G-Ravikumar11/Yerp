import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Download, Plus, Search, Table2, Trash2 } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardInteractive,
  CardTitle,
  Field,
  Input,
  Modal,
  Skeleton,
  SkeletonRows,
  SkeletonStat,
  StatusBadge,
  Textarea,
} from '@/components/ui'
import { compactINR, formatINR } from '@/lib/utils'

const ember = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950]
const semantic = ['background', 'surface', 'card', 'muted', 'primary', 'success', 'warning', 'danger', 'info']
const statuses = ['Draft', 'Provisional', 'Submitted', 'Approved', 'Certified', 'Paid', 'Rejected', 'Cancelled']

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="mb-12">
      <h2 className="text-xl font-semibold">{title}</h2>
      {hint && <p className="mt-1 text-[13.5px] text-muted-foreground">{hint}</p>}
      <div className="mt-5">{children}</div>
    </section>
  )
}

export default function DesignSystem() {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)

  return (
    <>
      <PageHeader
        eyebrow="Foundation"
        title="Design system"
        description="Every token and base component the modules are built from. If a screen needs something that is not here, it is added here first."
      />

      <div className="mb-10">
        <Button variant="outline" asChild>
          <Link to="/design/grid">
            <Table2 /> Open the data grid
          </Link>
        </Button>
      </div>

      <Section title="Colour" hint="Ember is the one accent. Surfaces rise with the theme; nothing on a screen uses a raw hex value.">
        <div className="grid grid-cols-6 gap-2 sm:grid-cols-11">
          {ember.map((n) => (
            <div key={n} className="text-center">
              <div className="h-14 rounded-lg ring-1 ring-black/5 dark:ring-white/10" style={{ background: `var(--color-ember-${n})` }} />
              <span className="mt-1.5 block text-[11px] tabular text-muted-foreground">{n}</span>
            </div>
          ))}
        </div>
        <div className="mt-6 grid grid-cols-3 gap-3 sm:grid-cols-5 lg:grid-cols-9">
          {semantic.map((s) => (
            <div key={s}>
              <div className="h-16 rounded-lg border border-border" style={{ background: `var(--${s})` }} />
              <span className="mt-1.5 block text-xs text-muted-foreground">{s}</span>
            </div>
          ))}
        </div>
      </Section>

      <Section title="Typography" hint="Outfit for headings, Inter for reading, JetBrains Mono for numbers that are identifiers.">
        <Card className="space-y-4 p-6">
          <p className="font-display text-5xl font-semibold leading-none tracking-tight">
            Measured, <span className="ember-text">not guessed.</span>
          </p>
          <h2 className="text-2xl font-semibold">Subcontract work order WO/2026-27/CIVIL/001</h2>
          <p className="max-w-2xl text-[15px] leading-relaxed text-muted-foreground">
            The app is the book. Every quantity is entered where it is measured, every bill draws only on what was measured, and nothing is billed twice.
          </p>
          <div className="flex flex-wrap items-baseline gap-x-8 gap-y-2">
            <span className="font-mono text-sm">SC-0004 · WO/2026-27/CIVIL/001</span>
            <span className="tabular text-2xl font-semibold">{formatINR(11073940)}</span>
            <span className="tabular text-2xl font-semibold text-success">{compactINR(11073940)}</span>
            <span className="tabular text-2xl font-semibold text-danger">{compactINR(-81820.7)}</span>
          </div>
        </Card>
      </Section>

      <Section title="Buttons" hint="Ember for the one action that matters on a screen; the rest step back.">
        <Card className="space-y-5 p-6">
          <div className="flex flex-wrap items-center gap-3">
            <Button>
              <Plus /> New work order
            </Button>
            <Button variant="secondary">Secondary</Button>
            <Button variant="outline">Outline</Button>
            <Button variant="soft">Soft</Button>
            <Button variant="ghost">Ghost</Button>
            <Button variant="danger">
              <Trash2 /> Cancel order
            </Button>
            <Button variant="link">Link style</Button>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button size="sm">Small</Button>
            <Button size="md">Medium</Button>
            <Button size="lg">Large</Button>
            <Button size="icon" variant="outline" aria-label="Download">
              <Download />
            </Button>
            <Button
              loading={busy}
              onClick={() => {
                setBusy(true)
                setTimeout(() => setBusy(false), 1600)
              }}
            >
              {busy ? 'Saving' : 'Click to see loading'}
            </Button>
            <Button disabled>Disabled</Button>
          </div>
        </Card>
      </Section>

      <Section title="Forms" hint="Focus draws a soft ember ring; errors say what is wrong in words.">
        <Card className="p-6">
          <div className="grid gap-5 md:grid-cols-2">
            <Field label="Search" htmlFor="ds-search">
              <Input id="ds-search" placeholder="Number, contractor, project..." leading={<Search />} />
            </Field>
            <Field label="Vendor code" htmlFor="ds-code" hint="Next in the series if left blank">
              <Input id="ds-code" placeholder="SC-0005" className="font-mono uppercase" />
            </Field>
            <Field label="PAN" htmlFor="ds-pan" error="A PAN is five letters, four digits and a letter.">
              <Input id="ds-pan" defaultValue="SDFGHJK%^&*" aria-invalid />
            </Field>
            <Field label="Disabled" htmlFor="ds-dis">
              <Input id="ds-dis" disabled defaultValue="Locked once approved" />
            </Field>
            <Field label="Scope of work" htmlFor="ds-scope" className="md:col-span-2">
              <Textarea id="ds-scope" placeholder="Shuttering, tower C..." />
            </Field>
          </div>
        </Card>
      </Section>

      <Section title="Status" hint="The same states the backend uses, each with a tone.">
        <div className="flex flex-wrap gap-2.5">
          {statuses.map((s) => (
            <StatusBadge key={s} status={s} />
          ))}
          <Badge tone="ember">Ember</Badge>
          <Badge tone="info">Info</Badge>
        </div>
      </Section>

      <Section title="Cards and loading" hint="Tiles lift to meet the pointer; skeletons hold still where data is on its way.">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <CardInteractive className="p-5">
            <p className="text-[13px] text-muted-foreground">Billed up to date</p>
            <p className="tabular mt-2 font-display text-3xl font-semibold">{compactINR(5600000)}</p>
            <p className="mt-2 text-xs text-success">+12.4% on last bill</p>
          </CardInteractive>
          <SkeletonStat />
          <SkeletonStat />
          <Card>
            <CardHeader>
              <CardTitle>Card title</CardTitle>
              <CardDescription>With a description</CardDescription>
            </CardHeader>
            <CardContent>
              <Skeleton className="h-3.5 w-full" />
              <Skeleton className="mt-2 h-3.5 w-2/3" />
            </CardContent>
          </Card>
        </div>
        <Card className="mt-4 overflow-hidden">
          <SkeletonRows rows={4} cols={5} />
        </Card>
      </Section>

      <Section title="Modal" hint="Rises into place, traps focus, closes on Escape, and becomes a bottom sheet on a phone.">
        <Button variant="outline" onClick={() => setOpen(true)}>
          Open a modal
        </Button>
        <Modal
          open={open}
          onOpenChange={setOpen}
          title="Cancel work order"
          description="Say why - it goes on the order's history."
          footer={
            <>
              <Button variant="ghost" onClick={() => setOpen(false)}>
                Keep it
              </Button>
              <Button variant="danger" onClick={() => setOpen(false)}>
                Cancel the order
              </Button>
            </>
          }
        >
          <Field label="Reason" htmlFor="ds-reason">
            <Textarea id="ds-reason" placeholder="Contractor left site..." autoFocus />
          </Field>
        </Modal>
      </Section>
    </>
  )
}
