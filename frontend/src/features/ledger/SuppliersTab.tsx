import { useState } from 'react'
import { Plus } from 'lucide-react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button } from '@/components/ui'
import { MsmeBadge } from '@/components/data/MsmeBadge'
import { adoptSuppliers, ledgerKeys, useSuppliers, type Supplier } from '@/api/ledger'
import { StatementModal } from './StatementModal'
import { SupplierModal } from './SupplierModal'
import { useAction } from '@/lib/mutate'
import { cn } from '@/lib/utils'
import { MasterDelete } from '@/features/deleteorder/MasterDelete'

/** The supplier master. Names already used on orders and bills can be adopted into it in one go. */
export function SuppliersTab() {
  const q = useSuppliers()
  const [editing, setEditing] = useState<Supplier | null>(null)
  const [creating, setCreating] = useState(false)
  const [statement, setStatement] = useState<Supplier | null>(null)
  const adopt = useAction(() => adoptSuppliers(), { invalidate: [ledgerKeys.all, ['suppliers']], success: (r) => r.message ?? 'Done' })
  const missing = q.data?.unregistered ?? []
  // The bank's payment file cannot pay a supplier without an account and a proper IFSC.
  const all = q.data?.suppliers ?? []
  const noBank = all.filter((s) => s.is_active && !bankOk(s))
  const [onlyNoBank, setOnlyNoBank] = useState(false)
  const rows = onlyNoBank ? noBank : all

  const columns: TableColumn<Supplier>[] = [
    { id: 'code', header: 'Code', cell: (s) => <span className={cn('font-mono text-[13px]', !s.is_active && 'opacity-55')}>{s.code}</span> },
    { id: 'name', header: 'Supplier', sort: (s) => s.name, cell: (s) => <div className="font-semibold"><span className="inline-flex flex-wrap items-center gap-1.5">{s.name}<MsmeBadge msme={s.msme_type ? { type: s.msme_type, udyam: s.udyam_no } : null} /></span>{s.contact_person && <div className="text-xs font-normal text-muted-foreground">{s.contact_person}</div>}</div> },
    { id: 'supplies', header: 'Supplies', hideBelow: 'lg', cell: (s) => s.supplies },
    { id: 'gstin', header: 'GSTIN', hideBelow: 'md', cell: (s) => (s.gstin ? <span className="font-mono text-xs">{s.gstin}</span> : <span className="text-xs text-warning">none - input credit at risk</span>) },
    { id: 'state', header: 'State', hideBelow: 'xl', cell: (s) => s.state },
    { id: 'phone', header: 'Phone', hideBelow: 'xl', cell: (s) => s.phone },
    { id: 'bank', header: 'Bank', hideBelow: 'md', cell: (s) => (bankOk(s) ? <span className="font-mono text-xs">{s.bank_ifsc} · ...{s.bank_account.slice(-4)}</span> : <Badge tone="warning">{s.bank_account.trim() ? 'IFSC missing or wrong' : 'no bank details'}</Badge>) },
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
    { id: 'master-del', header: '', align: 'right', width: '3.5rem', cell: (r) => <MasterDelete kind="supplier" id={r.id} label={String(r.name)} noun="supplier" /> },
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
        {noBank.length > 0 && (
          <div className="rounded-lg border border-warning/50 px-3 py-2 text-[13px]">
            <strong>{noBank.length}</strong> supplier{noBank.length === 1 ? ' has' : 's have'} no bank details, so the bank payment file cannot pay {noBank.length === 1 ? 'it' : 'them'}. Ask them to add them on the partner portal, or edit them here.{' '}
            <button type="button" className="text-primary underline underline-offset-2" onClick={() => setOnlyNoBank((v) => !v)}>{onlyNoBank ? 'Show all suppliers' : 'Show only these'}</button>
          </div>
        )}
      </div>
      <DataTable label="Suppliers" rows={rows} columns={columns} rowKey={(s) => s.id} loading={q.isPending} empty={onlyNoBank ? 'Every active supplier has bank details.' : 'No suppliers on file yet.'} />
      <SupplierModal open={creating || !!editing} supplier={editing} onClose={() => { setCreating(false); setEditing(null) }} />
      <StatementModal target={statement ? { type: 'supplier', party: statement.name } : null} onClose={() => setStatement(null)} />
    </>
  )
}

/** An account number and an IFSC of the right form: what the bank's payment file needs. */
const bankOk = (s: Supplier) => /^\d{9,18}$/.test(s.bank_account.replace(/[\s-]/g, '')) && /^[A-Z]{4}0[A-Z0-9]{6}$/.test(s.bank_ifsc.trim().toUpperCase())
