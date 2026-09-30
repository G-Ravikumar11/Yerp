import { useState } from 'react'
import { Plus } from 'lucide-react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Button } from '@/components/ui'
import { adoptSuppliers, ledgerKeys, useSuppliers, type Supplier } from '@/api/ledger'
import { StatementModal } from './StatementModal'
import { SupplierModal } from './SupplierModal'
import { useAction } from '@/lib/mutate'
import { cn } from '@/lib/utils'

/** The supplier master. Names already used on orders and bills can be adopted into it in one go. */
export function SuppliersTab() {
  const q = useSuppliers()
  const [editing, setEditing] = useState<Supplier | null>(null)
  const [creating, setCreating] = useState(false)
  const [statement, setStatement] = useState<Supplier | null>(null)
  const adopt = useAction(() => adoptSuppliers(), { invalidate: [ledgerKeys.all, ['suppliers']], success: (r) => r.message ?? 'Done' })
  const missing = q.data?.unregistered ?? []

  const columns: TableColumn<Supplier>[] = [
    { id: 'code', header: 'Code', cell: (s) => <span className={cn('font-mono text-[13px]', !s.is_active && 'opacity-55')}>{s.code}</span> },
    { id: 'name', header: 'Supplier', sort: (s) => s.name, cell: (s) => <div className="font-semibold">{s.name}{s.contact_person && <div className="text-xs font-normal text-muted-foreground">{s.contact_person}</div>}</div> },
    { id: 'supplies', header: 'Supplies', hideBelow: 'lg', cell: (s) => s.supplies },
    { id: 'gstin', header: 'GSTIN', hideBelow: 'md', cell: (s) => (s.gstin ? <span className="font-mono text-xs">{s.gstin}</span> : <span className="text-xs text-warning">none - input credit at risk</span>) },
    { id: 'state', header: 'State', hideBelow: 'xl', cell: (s) => s.state },
    { id: 'phone', header: 'Phone', hideBelow: 'xl', cell: (s) => s.phone },
    { id: 'days', header: 'Pays in', hideBelow: 'lg', align: 'right', cell: (s) => `${s.payment_days || 0} days` },
    {
      id: 'act',
      header: '',
      align: 'right',
      cell: (s) => (
        <div className="flex justify-end gap-1.5">
          <Button size="sm" variant="outline" onClick={() => setStatement(s)}>Statement</Button>
          <Button size="sm" variant="outline" onClick={() => setEditing(s)}>Edit</Button>
        </div>
      ),
    },
  ]

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Button size="sm" onClick={() => setCreating(true)}><Plus /> Supplier</Button>
        {missing.length > 0 && (
          <div className="rounded-lg border border-warning/50 px-3 py-2 text-[13px]">
            <strong>{missing.length}</strong> supplier name{missing.length === 1 ? '' : 's'} on orders and bills are not in the master yet ({missing.slice(0, 4).join(', ')}
            {missing.length > 4 ? '...' : ''}).{' '}
            <button type="button" className="text-primary underline underline-offset-2" onClick={() => adopt.mutate()}>Add them all</button>
          </div>
        )}
      </div>
      <DataTable label="Suppliers" rows={q.data?.suppliers ?? []} columns={columns} rowKey={(s) => s.id} loading={q.isPending} empty="No suppliers on file yet." />
      <SupplierModal open={creating || !!editing} supplier={editing} onClose={() => { setCreating(false); setEditing(null) }} />
      <StatementModal target={statement ? { type: 'supplier', party: statement.name } : null} onClose={() => setStatement(null)} />
    </>
  )
}
