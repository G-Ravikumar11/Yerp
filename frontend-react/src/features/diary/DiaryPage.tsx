import { useState } from 'react'
import { FileSpreadsheet, Image, Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { FilesModal } from '@/components/data/FilesModal'
import { ProjectPicker } from '@/components/data/ProjectPicker'
import { Badge, Button, Skeleton, Stat, StatGrid } from '@/components/ui'
import { useDiaries, useLabourHistory, type DiaryRow } from '@/api/diary'
import { formatDate } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { DiaryFormModal } from './DiaryFormModal'

/** The daily site record: who turned up, what the weather did, what got built and what stopped it. */
export default function DiaryPage() {
  const [job, setJob] = useState(0)
  const [open, setOpen] = useState<number | 'new' | null>(null)
  const [photos, setPhotos] = useState<DiaryRow | null>(null)
  const q = useDiaries(job)
  const labour = useLabourHistory(job)
  const s = q.data?.summary
  const columns: TableColumn<DiaryRow>[] = [
    { id: 'date', header: 'Date', sort: (r) => r.diary_date, cell: (r) => <div><button type="button" className="font-semibold text-primary underline-offset-2 hover:underline" onClick={() => setOpen(r.id)}>{formatDate(r.diary_date)}</button>{r.lost_to_weather && <div className="text-xs text-warning">rained off</div>}</div> },
    { id: 'weather', header: 'Weather', hideBelow: 'md', cell: (r) => `${r.weather}${r.rain_hours ? ` - ${r.rain_hours}h` : ''}` },
    { id: 'md', header: 'Mandays', align: 'right', sort: (r) => r.total_mandays, cell: (r) => <strong>{r.total_mandays}</strong> },
    { id: 'lab', header: 'Labour', hideBelow: 'lg', align: 'right', cell: (r) => formatINR(r.labour_cost) },
    { id: 'plant', header: 'Plant', hideBelow: 'lg', align: 'right', cell: (r) => formatINR(r.plant_cost) },
    { id: 'work', header: 'Work done', hideBelow: 'md', cell: (r) => <div className="max-w-64"><span className="line-clamp-2">{r.work_done}</span>{r.holdups && <div className="line-clamp-1 text-xs text-warning">held up: {r.holdups}</div>}</div> },
    { id: 'status', header: 'Status', cell: (r) => <Badge tone={r.status === 'SUBMITTED' ? 'success' : 'neutral'} dot>{r.status === 'SUBMITTED' ? 'Signed off' : 'Draft'}</Badge> },
    {
      id: 'act',
      header: '',
      align: 'right',
      cell: (r) => (
        <div className="flex justify-end gap-1.5">
          <Button size="sm" variant="outline" onClick={() => setPhotos(r)}><Image /> Photos</Button>
          <Button size="sm" variant="outline" asChild><a href={`/api/diary/${r.id}/export.xlsx`} title="The daily progress report as a workbook"><FileSpreadsheet /> DPR</a></Button>
        </div>
      ),
    },
  ]
  const top = Math.max(...(labour.data?.by_trade.map((t) => t.mandays) ?? [0]), 1)
  return (
    <>
      <PageHeader eyebrow="Projects" title="Site Diary" description="Who turned up, what the weather did, what got built and what stopped it." actions={<Button disabled={!job} onClick={() => setOpen('new')}><Plus /> Record a day</Button>} />
      <div className="mb-6"><ProjectPicker value={job} onChange={setJob} id="diary-job" /></div>
      <StatGrid>
        <Stat label="Days recorded" value={s?.days_recorded ?? 0} loading={q.isPending && job > 0} />
        <Stat label="Mandays" value={s?.mandays ?? 0} loading={q.isPending && job > 0} />
        <Stat label="Labour" value={formatINR(s?.labour_cost ?? 0)} loading={q.isPending && job > 0} />
        <Stat label="Plant" value={formatINR(s?.plant_cost ?? 0)} loading={q.isPending && job > 0} />
        <Stat label="Rained off" value={s?.days_lost_to_weather ?? 0} loading={q.isPending && job > 0} />
      </StatGrid>
      <DataTable label="Diary days" rows={q.data?.diaries ?? []} columns={columns} rowKey={(r) => r.id} loading={q.isPending && job > 0} empty="No days recorded on this site yet." />
      {(labour.data?.by_trade.length ?? 0) > 0 && (
        <section aria-label="Who has been on this site" className="mt-6 rounded-xl border border-border bg-card p-4 shadow-card">
          <h2 className="text-sm font-semibold">Who has been on this site</h2>
          <p className="mb-3 text-[13px] text-muted-foreground">{labour.data?.summary.mandays} mandays over {labour.data?.summary.days_worked} working days - average gang {labour.data?.summary.average_gang} - {formatINR(labour.data?.summary.labour_cost)} in wages - {labour.data?.summary.rain_hours} hours of rain</p>
          {labour.data?.by_trade.map((t) => (
            <div key={t.trade} className="mb-2">
              <div className="flex justify-between text-[13px]"><span>{t.trade}</span><span className="text-muted-foreground">{t.mandays} md - {formatINR(t.cost)}</span></div>
              <div className="mt-1 h-2 overflow-hidden rounded bg-muted"><div className="h-full bg-primary" style={{ width: `${(t.mandays / top) * 100}%` }} /></div>
            </div>
          ))}
        </section>
      )}
      {labour.isPending && job > 0 && <Skeleton className="mt-6 h-24 w-full" />}
      <DiaryFormModal job={job} id={open} onClose={() => setOpen(null)} />
      {photos && <FilesModal type="diary" id={photos.id} title={`diary ${formatDate(photos.diary_date)}`} onClose={() => setPhotos(null)} />}
    </>
  )
}
