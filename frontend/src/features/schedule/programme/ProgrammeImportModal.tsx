import { useRef, useState } from 'react'
import { FileUp } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { Button, Modal, Select } from '@/components/ui'
import { importProgramme, programmeKeys, readProgrammeSheet, type ImportPreview } from '@/api/programme'
import { schKeys } from '@/api/schedule'
import { useAction } from '@/lib/mutate'
import { formatDate } from '@/lib/format'

/**
 * Import one of the office's schedule sheets - the GH layout, the APTIDCO / finishing-works layout, or a sheet exported
 * from here - as rows under what is on the programme already. The tree and the dependencies are shown first; nothing is
 * saved until Import is pressed, and anything read wrong is fixed in the grid afterwards (indent, outdent, predecessors).
 */
export function ProgrammeImportModal({ job, open, onClose }: { job: number; open: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const file = useRef<HTMLInputElement>(null)
  const [picked, setPicked] = useState<File | null>(null)
  const [preview, setPreview] = useState<ImportPreview | null>(null)

  const read = useAction(({ f, sheet }: { f: File; sheet: string }) => readProgrammeSheet(job, f, sheet), { onSuccess: (r) => setPreview(r) })
  const save = useAction(() => importProgramme(job, preview!), {
    success: (r) => (r as { message?: string }).message ?? 'Imported.',
    onSuccess: async () => {
      await Promise.all([qc.invalidateQueries({ queryKey: programmeKeys.one(job) }), qc.invalidateQueries({ queryKey: schKeys.all })])
      close()
    },
  })
  const close = () => { setPicked(null); setPreview(null); onClose() }

  const depth = (() => {
    const parent = new Map((preview?.nodes ?? []).map((n) => [n.key, n.parent]))
    const out = new Map<number, number>()
    for (const n of preview?.nodes ?? []) {
      let d = 0
      for (let p = n.parent; p !== null && p !== undefined && d < 30; p = parent.get(p) ?? null) d++
      out.set(n.key, d)
    }
    return out
  })()
  const nodes = preview?.nodes ?? []
  const links = nodes.reduce((s, n) => s + n.links.length, 0)

  return (
    <Modal open={open} onOpenChange={(o) => !o && close()} title="Import a programme" size="xl"
      description="The GH sheet, the APTIDCO / finishing-works sheet, or one exported from here. The rows are shown first; nothing is saved until you press Import."
      footer={preview ? <><Button variant="ghost" onClick={close}>Cancel</Button><Button loading={save.isPending} onClick={() => save.mutate()}>Import {nodes.length} rows</Button></> : undefined}>
      {!preview ? (
        <div className="grid gap-3">
          <input ref={file} type="file" hidden accept=".xlsx" onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) { setPicked(f); read.mutate({ f, sheet: '' }) } }} />
          <Button variant="outline" loading={read.isPending} onClick={() => file.current?.click()}><FileUp /> Choose the sheet</Button>
          {read.error && <p role="alert" className="text-[13px] text-danger">{read.error.message}</p>}
          <p className="text-xs text-muted-foreground">Needs a header row with Start, End and the item / activity. Headings are found from the sheet's own formulas, or from its bold rows and SL.NO; a Start written as a formula on another row becomes a dependency.</p>
        </div>
      ) : (
        <div className="grid gap-3">
          <p className="text-sm">
            <b>{nodes.length}</b> rows read from <b>{preview.sheet}</b>: {nodes.filter((n) => n.heading).length} headings, {nodes.filter((n) => !n.heading).length} activities, {links} dependenc{links === 1 ? 'y' : 'ies'}.
            {preview.own ? ' This sheet was exported from here, so it comes back as it was.' : ' Days are the dates the sheet shows, End - Start + 1, and every day is counted until you set the working week.'}
          </p>
          {preview.sheets.length > 1 && picked && (
            <label className="flex items-center gap-2 text-[13px]">
              <span className="text-muted-foreground">Sheet</span>
              <Select aria-label="Sheet to read" value={preview.sheet} onChange={(e) => read.mutate({ f: picked, sheet: e.target.value })} options={preview.sheets.map((s) => ({ value: s, label: s }))} className="h-8 w-72 text-xs" />
            </label>
          )}
          {preview.warnings.length > 0 && (
            <div className="rounded-lg border border-warning/40 bg-warning-soft p-2.5 text-[13px]">
              <div className="mb-1 font-semibold">Check these</div>
              <ul className="grid gap-0.5">{preview.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
            </div>
          )}
          <div className="max-h-[26rem] overflow-y-auto rounded-lg border border-border">
            <table aria-label="Rows read from the sheet" className="w-full text-[13px]">
              <thead className="sticky top-0 bg-surface text-left text-[11px] uppercase tracking-wide text-muted-foreground">
                <tr><th className="px-2 py-2">Item / activity</th><th className="px-2 py-2">Start</th><th className="px-2 py-2 text-right">Days</th><th className="px-2 py-2">U.O.M</th><th className="px-2 py-2 text-right">Quantity</th><th className="px-2 py-2">Waits on</th></tr>
              </thead>
              <tbody>
                {nodes.map((n) => (
                  <tr key={n.key} className={`border-t border-border ${n.heading ? 'bg-surface/60 font-semibold' : ''}`}>
                    <td className="px-2 py-1.5" style={{ paddingLeft: 8 + (depth.get(n.key) ?? 0) * 16 }}>{n.name}</td>
                    <td className="px-2 py-1.5">{n.start ? formatDate(n.start) : ''}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{n.days ?? ''}</td>
                    <td className="px-2 py-1.5">{n.uom}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{n.quantity || ''}</td>
                    <td className="px-2 py-1.5 text-xs text-muted-foreground">{n.links.map((l) => `${nodes.find((x) => x.key === l.pred)?.name ?? l.pred} ${l.kind}${l.lag ? (l.lag > 0 ? '+' : '') + l.lag : ''}`).join(', ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Modal>
  )
}