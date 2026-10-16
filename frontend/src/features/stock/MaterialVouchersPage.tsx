import { useState } from 'react'
import { FileSpreadsheet, FileText, Plus, Trash2, X } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { ProjectPicker } from '@/components/data/ProjectPicker'
import { Button, ConfirmDialog, Field, Input, Stat, StatGrid, Tabs } from '@/components/ui'
import { addVoucher, removeVoucher, useVouchers, voucherKeys, voucherPdf, voucherRegister, type Voucher, type VoucherLine } from '@/api/materialVouchers'
import { apiUrl } from '@/lib/api'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate, today } from '@/lib/format'

type Tab = 'new' | 'register'
const blankLine = (): VoucherLine => ({ description: '', uom: '', issued_qty: 0, returned_qty: 0, remarks: '' })

/** Store > Material Issue Voucher: fill in the voucher as on paper, and keep every one in Sl. No. order. */
export default function MaterialVouchersPage() {
  const [tab, setTab] = useState<Tab>('new')
  return (
    <>
      <PageHeader eyebrow="Store" title="Material Issue Voucher" description="The store's voucher for material issued to a project, as on the printed form. Every voucher is kept in Sl. No. order, to print or download." />
      <div className="mb-6">
        <Tabs size="lg" label="Material Issue Voucher" value={tab} onChange={setTab} items={[{ value: 'new', label: 'New voucher' }, { value: 'register', label: 'Voucher register' }]} />
      </div>
      {tab === 'new' ? <VoucherForm onSaved={() => setTab('register')} /> : <Register />}
    </>
  )
}

/** The voucher, laid out like the printed one: the four fields and Sl. No. / Date, then the items table. */
function VoucherForm({ onSaved }: { onSaved: () => void }) {
  const [job, setJob] = useState(0)
  const [f, setF] = useState({ voucher_on: today(), indented_by: '', issued_by: '', issued_for: '' })
  const [lines, setLines] = useState<VoucherLine[]>([blankLine(), blankLine(), blankLine()])
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }))
  const setLine = (i: number, k: keyof VoucherLine, v: string) =>
    setLines((ls) => ls.map((l, n) => (n === i ? { ...l, [k]: k === 'issued_qty' || k === 'returned_qty' ? Number(v) || 0 : v } : l)))
  const filled = lines.filter((l) => l.description.trim())
  const ready = job > 0 && filled.length > 0 && filled.every((l) => l.issued_qty > 0 && l.returned_qty >= 0 && l.returned_qty <= l.issued_qty)
  const save = useAction(() => addVoucher({ job_id: job, ...f, lines: filled }), {
    invalidate: [voucherKeys.all],
    onSuccess: () => {
      setF({ voucher_on: today(), indented_by: '', issued_by: '', issued_for: '' })
      setLines([blankLine(), blankLine(), blankLine()])
      onSaved()
    },
  })
  const cell = 'h-9 w-full rounded-md border border-border bg-background px-2 text-[13px] outline-none focus:border-primary'

  return (
    <div className="rounded-2xl border border-border bg-card p-5 sm:p-6">
      <h2 className="mb-5 text-center text-lg font-bold tracking-[0.12em]">MATERIAL ISSUE VOUCHER</h2>
      <div className="grid gap-4 lg:grid-cols-[1fr_16rem]">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Project Name" htmlFor="miv-job" className="sm:col-span-2"><ProjectPicker value={job} onChange={setJob} id="miv-job" /></Field>
          <Field label="Material Indented By" htmlFor="miv-ind"><Input id="miv-ind" value={f.indented_by} onChange={set('indented_by')} /></Field>
          <Field label="Issued By" htmlFor="miv-by"><Input id="miv-by" value={f.issued_by} onChange={set('issued_by')} /></Field>
          <Field label="Issued For" htmlFor="miv-for" className="sm:col-span-2"><Input id="miv-for" value={f.issued_for} onChange={set('issued_for')} /></Field>
        </div>
        <div className="grid content-start gap-4">
          <Field label="Sl. No." htmlFor="miv-no"><Input id="miv-no" value="Given when saved, next in sequence" readOnly disabled /></Field>
          <Field label="Date" htmlFor="miv-date"><Input id="miv-date" type="date" value={f.voucher_on} onChange={set('voucher_on')} /></Field>
        </div>
      </div>

      <div className="mt-6 overflow-x-auto rounded-xl border border-border">
        <table className="w-full min-w-[46rem] text-[13px]">
          <thead className="bg-muted/60 text-left text-xs font-semibold">
            <tr>
              <th className="w-14 px-2 py-2 text-center">S.No.</th>
              <th className="px-2 py-2">Item Description</th>
              <th className="w-24 px-2 py-2">Uom</th>
              <th className="w-28 px-2 py-2 text-right">Issued Qty.</th>
              <th className="w-28 px-2 py-2 text-right">Returned Qty.</th>
              <th className="px-2 py-2">Remarks</th>
              <th className="w-10" />
            </tr>
          </thead>
          <tbody>
            {lines.map((l, i) => (
              <tr key={i} className="border-t border-border">
                <td className="px-2 py-1.5 text-center tabular text-muted-foreground">{i + 1}</td>
                <td className="px-2 py-1.5"><input aria-label={`Item ${i + 1} description`} className={cell} value={l.description} onChange={(e) => setLine(i, 'description', e.target.value)} /></td>
                <td className="px-2 py-1.5"><input aria-label={`Item ${i + 1} unit`} className={cell} value={l.uom} placeholder="Bag, MT, Cum" onChange={(e) => setLine(i, 'uom', e.target.value)} /></td>
                <td className="px-2 py-1.5"><input aria-label={`Item ${i + 1} issued quantity`} type="number" min={0} step="any" className={`${cell} text-right`} value={l.issued_qty || ''} onChange={(e) => setLine(i, 'issued_qty', e.target.value)} /></td>
                <td className="px-2 py-1.5"><input aria-label={`Item ${i + 1} returned quantity`} type="number" min={0} step="any" className={`${cell} text-right ${l.returned_qty > l.issued_qty ? 'border-danger' : ''}`} value={l.returned_qty || ''} onChange={(e) => setLine(i, 'returned_qty', e.target.value)} /></td>
                <td className="px-2 py-1.5"><input aria-label={`Item ${i + 1} remarks`} className={cell} value={l.remarks} onChange={(e) => setLine(i, 'remarks', e.target.value)} /></td>
                <td className="px-1 text-center">
                  {lines.length > 1 && (
                    <button type="button" aria-label={`Remove item ${i + 1}`} className="text-muted-foreground hover:text-danger" onClick={() => setLines((ls) => ls.filter((_, n) => n !== i))}>
                      <X className="size-4" />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Button size="sm" variant="outline" className="mt-3" onClick={() => setLines((ls) => [...ls, blankLine()])}><Plus /> Add an item</Button>

      <div className="mt-6 grid grid-cols-2 gap-3 border-t border-border pt-4 text-xs text-muted-foreground sm:grid-cols-4">
        {['Indented By', 'Received By', 'Stores', 'Authorised Signature'].map((s) => <span key={s}>{s}<span className="block pt-1 text-[11px]">signed on the printed voucher</span></span>)}
      </div>

      <div className="mt-5 flex items-center justify-end gap-2">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        {!job && <p className="mr-auto text-[13px] text-muted-foreground">Choose the project first.</p>}
        <Button loading={save.isPending} disabled={!ready} onClick={() => save.mutate()}>Save the voucher</Button>
      </div>
    </div>
  )
}

/** Every voucher in Sl. No. order: open each as its PDF, or download the whole register as Excel. */
function Register() {
  const { can } = useSession()
  const [job, setJob] = useState(0)
  const [removing, setRemoving] = useState<Voucher | null>(null)
  const q = useVouchers(job)
  const d = q.data
  const remove = useAction((v: Voucher) => removeVoucher(v.id), { invalidate: [voucherKeys.all], onSuccess: () => setRemoving(null) })

  const columns: TableColumn<Voucher>[] = [
    { id: 'no', header: 'Sl. No.', width: '5rem', sort: (v) => v.number, cell: (v) => <span className="font-mono font-semibold">{v.number}</span> },
    { id: 'on', header: 'Date', sort: (v) => v.voucher_on, cell: (v) => formatDate(v.voucher_on) },
    { id: 'project', header: 'Project Name', cell: (v) => v.project },
    { id: 'ind', header: 'Indented By', hideBelow: 'md', cell: (v) => v.indented_by || '-' },
    { id: 'by', header: 'Issued By', hideBelow: 'lg', cell: (v) => v.issued_by || '-' },
    { id: 'for', header: 'Issued For', hideBelow: 'lg', cell: (v) => v.issued_for || '-' },
    {
      id: 'items',
      header: 'Items',
      cell: (v) => (
        <div className="max-w-72 text-[13px]">
          {v.lines.slice(0, 3).map((l, i) => (
            <div key={i} className="truncate">{l.description} - {l.issued_qty} {l.uom}{l.returned_qty ? `, ${l.returned_qty} back` : ''}</div>
          ))}
          {v.lines.length > 3 && <div className="text-xs text-muted-foreground">and {v.lines.length - 3} more</div>}
        </div>
      ),
    },
    {
      id: 'act',
      header: '',
      align: 'right',
      cell: (v) => (
        <div className="flex justify-end gap-1.5">
          <Button size="sm" variant="outline" asChild><a href={apiUrl(voucherPdf(v.id))} target="_blank" rel="noopener"><FileText /> PDF</a></Button>
          {can('site.signoff') && <Button size="icon" variant="ghost" aria-label={`Remove voucher ${v.number}`} onClick={() => setRemoving(v)}><Trash2 /></Button>}
        </div>
      ),
    },
  ]

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <div className="min-w-64 flex-1 sm:max-w-md"><ProjectPicker value={job} onChange={setJob} id="miv-reg-job" allowAll /></div>
        <Button variant="outline" className="ml-auto" asChild><a href={apiUrl(voucherRegister(job))}><FileSpreadsheet /> Download register (Excel)</a></Button>
      </div>
      <StatGrid className="lg:grid-cols-2 xl:grid-cols-2">
        <Stat label="Vouchers" value={d?.summary.vouchers ?? 0} loading={q.isPending} />
        <Stat label="Items issued" value={d?.summary.lines ?? 0} loading={q.isPending} />
      </StatGrid>
      <DataTable label="Voucher register" rows={d?.vouchers ?? []} columns={columns} rowKey={(v) => v.id} loading={q.isPending} empty="No vouchers yet. Fill one in on New voucher." />
      <ConfirmDialog
        open={!!removing}
        onOpenChange={(o) => !o && setRemoving(null)}
        title={removing ? `Remove voucher Sl. No. ${removing.number}?` : ''}
        description="It is taken off the register. Its Sl. No. is not given out again."
        confirmLabel="Remove"
        tone="danger"
        loading={remove.isPending}
        onConfirm={() => {
          if (removing) remove.mutate(removing)
        }}
      />
    </div>
  )
}
