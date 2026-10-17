import { Link, NavLink, Route, Routes, useParams } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { Skeleton } from '@/components/ui'
import { cn } from '@/lib/utils'
import { StoreShell } from '../StoreShell'
import { kindOf, KINDS, useDoc, type ControlKind } from './api'
import DocListPage from './DocListPage'
import DocPage from './DocPage'
import { CountForm, ScrapForm, TransferForm } from './Forms'
import { InTransitPage, RealisationPage, VariancesPage } from './Reports'

const tab = ({ isActive }: { isActive: boolean }) =>
  cn('whitespace-nowrap rounded-lg px-3.5 py-1.5 text-[13px] font-medium', isActive ? 'bg-card text-foreground shadow-xs' : 'text-muted-foreground hover:text-foreground')

function Tabs() {
  return (
    <nav aria-label="Control" className="mb-4 flex w-fit max-w-full gap-1 overflow-x-auto rounded-xl bg-muted p-1">
      {KINDS.map((k) => <NavLink key={k.key} to={`/store/hub/control/${k.key}`} className={tab}>{k.plural}</NavLink>)}
      <NavLink to="/store/hub/control/in-transit" className={tab}>In transit</NavLink>
      <NavLink to="/store/hub/control/variances" className={tab}>Count differences</NavLink>
      <NavLink to="/store/hub/control/realisation" className={tab}>Scrap realised</NavLink>
    </nav>
  )
}

function List() {
  const { kind: key } = useParams()
  const kind = kindOf(key) ?? KINDS[0]
  return (
    <>
      <Tabs />
      <p className="mb-4 text-sm text-muted-foreground">{kind.blurb}</p>
      <DocListPage key={kind.key} kind={kind.key} label={kind.label} plural={kind.plural} />
    </>
  )
}

function Page({ children, blurb }: { children: React.ReactNode; blurb: string }) {
  return <><Tabs /><p className="mb-4 text-sm text-muted-foreground">{blurb}</p>{children}</>
}

/** New: a blank form. Edit: the same form filled from the draft, once it has loaded. A count is only ever created; it is filled in on its own page. */
function FormPage({ editing }: { editing: boolean }) {
  const { kind: key, id } = useParams()
  const kind = kindOf(key)
  const q = useDoc((kind?.key ?? 'transfer') as ControlKind, editing ? Number(id) : 0)
  if (!kind) return <p className="text-sm text-muted-foreground">There is no such document type.</p>
  const back = <Link to={editing ? `/store/hub/control/${kind.key}/${id}` : `/store/hub/control/${kind.key}`} className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" /> {editing ? 'Back to the document' : kind.plural}</Link>
  if (editing && kind.key === 'count') return <div>{back}<p className="text-sm text-muted-foreground">A count is entered on its own page.</p></div>
  if (editing && q.isPending) return <div>{back}<Skeleton className="h-40 w-full" /></div>
  if (editing && (q.isError || !q.data)) return <div>{back}<p role="alert" className="text-sm text-danger">Could not load this document.</p></div>
  if (editing && q.data && q.data.status !== 'DRAFT') return <div>{back}<p className="text-sm text-muted-foreground">Only a draft can be edited. Cancel it and make a new one to correct it.</p></div>
  const doc = editing ? q.data : undefined
  return (
    <div>
      {back}
      <h2 className="mb-4 text-lg font-semibold">{editing ? `Edit ${q.data?.number}` : `New ${kind.label.toLowerCase()}`}</h2>
      {kind.key === 'transfer' ? <TransferForm doc={doc} /> : kind.key === 'count' ? <CountForm /> : <ScrapForm doc={doc} />}
    </div>
  )
}

/** Store > Control. Routes under /store/hub/control/* land here. */
export default function ControlIndex() {
  return (
    <StoreShell slice="control">
      <Routes>
        <Route index element={<List />} />
        <Route path="in-transit" element={<Page blurb="Stock sent from one store and not yet received at the other."><InTransitPage /></Page>} />
        <Route path="variances" element={<Page blurb="What posted stock counts found against the books."><VariancesPage /></Page>} />
        <Route path="realisation" element={<Page blurb="Scrap sold or written off: what it was worth in the books against what it fetched."><RealisationPage /></Page>} />
        <Route path=":kind" element={<List />} />
        <Route path=":kind/new" element={<FormPage editing={false} />} />
        <Route path=":kind/:id" element={<DocPage />} />
        <Route path=":kind/:id/edit" element={<FormPage editing />} />
      </Routes>
    </StoreShell>
  )
}
