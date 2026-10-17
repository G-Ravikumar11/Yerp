import { Link, NavLink, Route, Routes, useParams } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { Skeleton } from '@/components/ui'
import { cn } from '@/lib/utils'
import { StoreShell } from '../StoreShell'
import { kindOf, KINDS, useDoc, type OutwardKind } from './api'
import DocListPage from './DocListPage'
import DocPage from './DocPage'
import IssueForm from './IssueForm'
import { RecoveryPage, ReturnablesPage, WriteoffsPage } from './Reports'
import ReturnForm from './ReturnForm'

const tab = ({ isActive }: { isActive: boolean }) =>
  cn('whitespace-nowrap rounded-lg px-3.5 py-1.5 text-[13px] font-medium', isActive ? 'bg-card text-foreground shadow-xs' : 'text-muted-foreground hover:text-foreground')

function Tabs() {
  return (
    <nav aria-label="Outward" className="mb-4 flex w-fit max-w-full gap-1 overflow-x-auto rounded-xl bg-muted p-1">
      {KINDS.map((k) => <NavLink key={k.key} to={`/store/hub/outward/${k.key}`} className={tab}>{k.plural}</NavLink>)}
      <NavLink to="/store/hub/outward/returnables" className={tab}>Returnables out</NavLink>
      <NavLink to="/store/hub/outward/writeoffs" className={tab}>Write-offs</NavLink>
      <NavLink to="/store/hub/outward/recovery" className={tab}>Subcontractor recovery</NavLink>
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

/** New: a blank form. Edit: the same form filled from the draft, once it has loaded. */
function FormPage({ editing }: { editing: boolean }) {
  const { kind: key, id } = useParams()
  const kind = kindOf(key)
  const q = useDoc((kind?.key ?? 'issue') as OutwardKind, editing ? Number(id) : 0)
  if (!kind) return <p className="text-sm text-muted-foreground">There is no such document type.</p>
  const back = <Link to={editing ? `/store/hub/outward/${kind.key}/${id}` : `/store/hub/outward/${kind.key}`} className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" /> {editing ? 'Back to the document' : kind.plural}</Link>
  if (editing && q.isPending) return <div>{back}<Skeleton className="h-40 w-full" /></div>
  if (editing && (q.isError || !q.data)) return <div>{back}<p role="alert" className="text-sm text-danger">Could not load this document.</p></div>
  if (editing && q.data && q.data.status !== 'DRAFT') return <div>{back}<p className="text-sm text-muted-foreground">Only a draft can be edited. Cancel it and make a new one to correct it.</p></div>
  const doc = editing ? q.data : undefined
  return (
    <div>
      {back}
      <h2 className="mb-4 text-lg font-semibold">{editing ? `Edit ${q.data?.number}` : `New ${kind.label.toLowerCase()}`}</h2>
      {kind.key === 'issue' ? <IssueForm doc={doc} /> : <ReturnForm doc={doc} />}
    </div>
  )
}

/** Store > Outward. Routes under /store/hub/outward/* land here. */
export default function OutwardIndex() {
  return (
    <StoreShell slice="outward">
      <Routes>
        <Route index element={<List />} />
        <Route path="returnables" element={<Page blurb="Returnable items and tools issued and not yet back, who holds them and how late they are."><ReturnablesPage /></Page>} />
        <Route path="writeoffs" element={<Page blurb="Returnables reported lost or damaged, waiting to be written off or recovered."><WriteoffsPage /></Page>} />
        <Route path="recovery" element={<Page blurb="Material issued to a subcontractor, what came back and what is to be recovered from their bill."><RecoveryPage /></Page>} />
        <Route path=":kind" element={<List />} />
        <Route path=":kind/new" element={<FormPage editing={false} />} />
        <Route path=":kind/:id" element={<DocPage />} />
        <Route path=":kind/:id/edit" element={<FormPage editing />} />
      </Routes>
    </StoreShell>
  )
}
