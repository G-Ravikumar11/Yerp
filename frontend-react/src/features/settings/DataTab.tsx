import { Download } from 'lucide-react'
import { Badge, Skeleton } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { buttonVariants } from '@/components/ui/button'
import { useAuditLog, useBackupInfo, type AuditRow } from '@/api/settings'
import { formatDate } from '@/lib/format'
import { Alerts } from './Alerts'
import { WipeWorkOrders } from './WipeWorkOrders'
import { Section } from './Section'

const size = (b: number) => (b > 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`)

function Backup() {
  const q = useBackupInfo()
  // Only the account holder can take one; for anyone else the server refuses and the block is left out.
  if (q.isError) return null
  return (
    <Section title="Backup" description="The whole business in one file, kept safe on your own computer.">
      {q.isPending || !q.data ? <Skeleton className="h-16 w-full" /> : (
        <>
          <p className="text-sm text-muted-foreground">{q.data.rows.toLocaleString('en-IN')} records in {q.data.tables} tables{q.data.files ? `, and ${q.data.files} files (${size(q.data.files_bytes)})` : ''}. {q.data.last_backup ? `Last taken ${q.data.last_backup}.` : 'No backup has been taken yet.'}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <a className={buttonVariants({ variant: 'outline' })} href="/api/backup" download><Download /> Download records</a>
            <a className={buttonVariants({ variant: 'outline' })} href="/api/backup?files=1" download><Download /> Records and files</a>
          </div>
        </>
      )}
    </Section>
  )
}

function Activity() {
  const q = useAuditLog()
  const cols: TableColumn<AuditRow>[] = [
    { id: 'when', header: 'When', cell: (a) => <span className="tabular whitespace-nowrap">{formatDate((a.created_at || '').slice(0, 10))} {(a.created_at || '').slice(11, 16)}</span> },
    { id: 'who', header: 'Who', cell: (a) => a.user_name || '-' },
    { id: 'what', header: 'Did', cell: (a) => <Badge>{a.action.replace(/_/g, ' ')}</Badge> },
    { id: 'on', header: 'On', hideBelow: 'md', cell: (a) => a.entity_name || a.entity_type || '-' },
    { id: 'det', header: 'Details', hideBelow: 'lg', cell: (a) => <span className="block max-w-72 truncate" title={a.details}>{a.details}</span> },
  ]
  return (
    <Section title="Activity log" description="The last fifty things anyone did to the books.">
      <DataTable label="Activity log" rows={q.data ?? []} columns={cols} rowKey={(a) => a.id} loading={q.isPending} empty="Nothing recorded yet." />
    </Section>
  )
}

/** Alerts, a backup to download, and the log of who did what. */
export default function DataTab() {
  return (
    <>
      <Alerts />
      <Backup />
      <Activity />
      <WipeWorkOrders />
    </>
  )
}
