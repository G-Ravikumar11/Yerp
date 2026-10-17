import { Link, NavLink, Route, Routes, useParams } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { Skeleton } from '@/components/ui'
import { cn } from '@/lib/utils'
import { StoreShell } from '../StoreShell'
import { kindOf, KINDS, useDoc, useIndent, type OutwardKind } from './api'
import { RecoveriesPage, SettingsPage } from './Closing'
import DocListPage from './DocListPage'
import DocPage from './DocPage'
import { GatePassForm, GatePassListPage, GatePassPage } from './GatePassPages'
import { IndentForm, IndentListPage, IndentPage } from './IndentPages'
import IssueForm from './IssueForm'
import { RecoveryPage, ReturnablesPage, WriteoffsPage } from './Reports'
import ReturnForm from './ReturnForm'

const tab = ({ isActive }: { isActive: boolean }) =>
  cn('whitespace-nowrap rounded-lg px-3.5 py-1.5 text-[13px] font-medium', isActive ? 'bg-card text-foreground shadow-xs' : 'text-muted-foreground hover:text-foreground')

function Tabs() {
  return (
    <nav aria-label="Outward" className="mb-4 flex w-fit max-w-full gap-1 overflow-x-auto rounded-xl bg-muted p-1">
      <NavLink to="/store/hub/outward/indent" className={tab}>Indents</NavLink>
      {KINDS.map((k) => <NavLink key={k.key} to={`/store/hub/outward/${k.key}`} className={tab}>{k.plural}</NavLink>)}
      <NavLink to="/store/hub/outward/gate-pass" className={tab}>Gate passes</NavLink>
      <NavLink to="/store/hub/outward/returnables" className={tab}>Returnables out</NavLink>
      <NavLink to="/store/hub/outward/writeoffs" className={tab}>Write-offs</NavLink>
      <NavLink to="/store/hub/outward/recoveries" className={tab}>Recoveries</NavLink>
      <NavLink to="/store/hub/outward/recovery" className={tab}>Subcontractor statement</NavLink>
      <NavLink to="/store/hub/outward/settings" className={tab}>Settings</NavLink>
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

const backTo = (to: string, label: string) => <Link to={to} className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" /> {label}</Link>

/** New: a blank form. Edit: the same form filled from the draft, once it has loaded. */
function FormPage({ editing }: { editing: boolean }) {
  const { kind: key, id } = useParams()
  const kind = kindOf(key)
  const q = useDoc((kind?.key ?? 'issue') as OutwardKind, editing ? Number(id) : 0)
  if (!kind) return <p className="text-sm text-muted-foreground">There is no such document type.</p>
  const back = backTo(editing ? `/store/hub/outward/${kind.key}/${id}` : `/store/hub/outward/${kind.key}`, editing ? 'Back to the document' : kind.plural)
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

function IndentFormPage({ editing }: { editing: boolean }) {
  const { id } = useParams()
  const q = useIndent(editing ? Number(id) : 0)
  const back = backTo(editing ? `/store/hub/outward/indent/${id}` : '/store/hub/outward/indent', editing ? 'Back to the indent' : 'Indents')
  if (editing && q.isPending) return <div>{back}<Skeleton className="h-40 w-full" /></div>
  if (editing && (q.isError || !q.data)) return <div>{back}<p role="alert" className="text-sm text-danger">Could not load this indent.</p></div>
  if (editing && q.data && q.data.status !== 'DRAFT') return <div>{back}<p className="text-sm text-muted-foreground">Only a draft can be edited. Cancel it and raise a new one to correct it.</p></div>
  return <div>{back}<h2 className="mb-4 text-lg font-semibold">{editing ? `Edit ${q.data?.number}` : 'New indent'}</h2><IndentForm indent={editing ? q.data : undefined} /></div>
}

/** Store > Outward. Routes under /store/hub/outward/* land here. */
export default function OutwardIndex() {
  return (
    <StoreShell slice="outward">
      <Routes>
        <Route index element={<Page blurb="Material asked for by site engineers, approved by the project manager and filled by issues."><IndentListPage /></Page>} />
        <Route path="indent" element={<Page blurb="Material asked for by site engineers, approved by the project manager and filled by issues."><IndentListPage /></Page>} />
        <Route path="indent/new" element={<IndentFormPage editing={false} />} />
        <Route path="indent/:id" element={<IndentPage />} />
        <Route path="indent/:id/edit" element={<IndentFormPage editing />} />
        <Route path="gate-pass" element={<Page blurb="Material that has left, or is leaving, the store's premises."><GatePassListPage /></Page>} />
        <Route path="gate-pass/new" element={<div>{backTo('/store/hub/outward/gate-pass', 'Gate passes')}<h2 className="mb-4 text-lg font-semibold">New gate pass</h2><GatePassForm /></div>} />
        <Route path="gate-pass/:id" element={<GatePassPage />} />
        <Route path="returnables" element={<Page blurb="Returnable items and tools issued and not yet back, who holds them and how late they are. Close what will not come back by charging for it or asking for a write-off."><ReturnablesPage /></Page>} />
        <Route path="writeoffs" element={<Page blurb="Returnables reported lost or written off, waiting to be dealt with under Control."><WriteoffsPage /></Page>} />
        <Route path="recoveries" element={<Page blurb="What has been charged to subcontractors and holders, to be recovered from their bills."><RecoveriesPage /></Page>} />
        <Route path="recovery" element={<Page blurb="Material issued to one subcontractor, what came back and what is to be recovered from their bill."><RecoveryPage /></Page>} />
        <Route path="settings" element={<Page blurb="Defaults for recovering material from subcontractors."><SettingsPage /></Page>} />
        <Route path=":kind" element={<List />} />
        <Route path=":kind/new" element={<FormPage editing={false} />} />
        <Route path=":kind/:id" element={<DocPage />} />
        <Route path=":kind/:id/edit" element={<FormPage editing />} />
      </Routes>
    </StoreShell>
  )
}
