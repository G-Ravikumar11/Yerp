import { Link, NavLink, Route, Routes, useParams } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { Skeleton } from '@/components/ui'
import { cn } from '@/lib/utils'
import { StoreShell } from '../StoreShell'
import { kindOf, KINDS, useDoc, type InwardKind } from './api'
import DocListPage from './DocListPage'
import DocPage from './DocPage'
import GrnForm from './GrnForm'
import ItemLinesForm from './ItemLinesForm'
import ReturnForm from './ReturnForm'

const tab = ({ isActive }: { isActive: boolean }) =>
  cn('whitespace-nowrap rounded-lg px-3.5 py-1.5 text-[13px] font-medium', isActive ? 'bg-card text-foreground shadow-xs' : 'text-muted-foreground hover:text-foreground')

function List() {
  const { kind: key } = useParams()
  const kind = kindOf(key) ?? KINDS[0]
  return (
    <>
      <nav aria-label="Inward documents" className="mb-4 flex w-fit max-w-full gap-1 overflow-x-auto rounded-xl bg-muted p-1">
        {KINDS.map((k) => <NavLink key={k.key} to={`/store/hub/inward/${k.key}`} className={tab}>{k.plural}</NavLink>)}
      </nav>
      <p className="mb-4 text-sm text-muted-foreground">{kind.blurb}</p>
      <DocListPage key={kind.key} kind={kind.key} label={kind.label} plural={kind.plural} />
    </>
  )
}

function FormFor({ kind, doc }: { kind: InwardKind; doc?: Parameters<typeof GrnForm>[0]['doc'] }) {
  if (kind === 'grn') return <GrnForm doc={doc} />
  if (kind === 'returns') return <ReturnForm doc={doc} />
  return <ItemLinesForm kind={kind} doc={doc} />
}

/** New: a blank form. Edit: the same form filled from the draft, once it has loaded. */
function FormPage({ editing }: { editing: boolean }) {
  const { kind: key, id } = useParams()
  const kind = kindOf(key)
  const q = useDoc((kind?.key ?? 'grn') as InwardKind, editing ? Number(id) : 0)
  if (!kind) return <p className="text-sm text-muted-foreground">There is no such document type.</p>
  const back = <Link to={editing ? `/store/hub/inward/${kind.key}/${id}` : `/store/hub/inward/${kind.key}`} className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" /> {editing ? 'Back to the document' : kind.plural}</Link>
  if (editing && q.isPending) return <div>{back}<Skeleton className="h-40 w-full" /></div>
  if (editing && (q.isError || !q.data)) return <div>{back}<p role="alert" className="text-sm text-danger">Could not load this document.</p></div>
  if (editing && q.data && q.data.status !== 'DRAFT') return <div>{back}<p className="text-sm text-muted-foreground">Only a draft can be edited. Cancel it and make a new one to correct it.</p></div>
  return (
    <div>
      {back}
      <h2 className="mb-4 text-lg font-semibold">{editing ? `Edit ${q.data?.number}` : `New ${kind.label.toLowerCase()}`}</h2>
      <FormFor kind={kind.key} doc={editing ? q.data : undefined} />
    </div>
  )
}

/** Store > Inward. Routes under /store/hub/inward/* land here. */
export default function InwardIndex() {
  return (
    <StoreShell slice="inward">
      <Routes>
        <Route index element={<List />} />
        <Route path=":kind" element={<List />} />
        <Route path=":kind/new" element={<FormPage editing={false} />} />
        <Route path=":kind/:id" element={<DocPage />} />
        <Route path=":kind/:id/edit" element={<FormPage editing />} />
      </Routes>
    </StoreShell>
  )
}
