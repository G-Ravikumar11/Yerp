import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Button, ConfirmDialog, Skeleton } from '@/components/ui'
import { get, post } from '@/lib/api'
import { useAction } from '@/lib/mutate'
import { fileSize } from '@/api/files'
import { Section } from './Section'

interface StorageReport {
  files: { count: number; bytes: number; by_kind: Record<string, { count: number; bytes: number }> }
  clean: { key: string; label: string; detail: string; count: number; bytes: number }[]
}

const KIND: Record<string, string> = { photo: 'Photos', drawing: 'Drawings', document: 'Documents' }

/**
 * What takes the space - photos, drawings and documents live in the database - and what can go: files whose
 * record was deleted and bell alerts long since read. Clearing is the owner's choice and cannot be undone.
 */
export function Storage() {
  const q = useQuery({ queryKey: ['settings', 'storage'], queryFn: () => get<StorageReport>('/api/storage'), retry: false })
  const [asking, setAsking] = useState(false)
  const clean = useAction(() => post<{ message?: string }>('/api/storage/clean', { keys: (q.data?.clean ?? []).filter((c) => c.count > 0).map((c) => c.key) }), {
    invalidate: [['settings', 'storage']],
    onSuccess: () => setAsking(false),
    onError: () => setAsking(false),
  })
  if (q.isError) return null
  const total = (q.data?.clean ?? []).reduce((n, c) => n + c.count, 0)
  return (
    <Section title="Storage" description="What your photos, drawings and documents take, and what is no use to anyone and can be cleared.">
      {q.isPending || !q.data ? (
        <Skeleton className="h-24 w-full" />
      ) : (
        <>
          <p className="text-sm text-muted-foreground" aria-label="Storage used">
            {q.data.files.count.toLocaleString('en-IN')} files, {fileSize(q.data.files.bytes)}
            {Object.entries(q.data.files.by_kind).map(([k, v]) => ` · ${KIND[k] ?? k} ${v.count} (${fileSize(v.bytes)})`)}
          </p>
          <ul className="mt-3 divide-y divide-border" aria-label="What can be cleared">
            {q.data.clean.map((c) => (
              <li key={c.key} className="flex items-start justify-between gap-4 py-3">
                <div>
                  <p className="text-sm font-medium">{c.label}</p>
                  <p className="text-[13px] text-muted-foreground">{c.detail}</p>
                </div>
                <p className="shrink-0 text-sm tabular">{c.count ? `${c.count}${c.bytes ? ` · ${fileSize(c.bytes)}` : ''}` : 'None'}</p>
              </li>
            ))}
          </ul>
          <Button className="mt-3" variant="outline" disabled={!total} onClick={() => setAsking(true)}>
            Clear them
          </Button>
          <ConfirmDialog
            open={asking}
            onOpenChange={setAsking}
            title="Clear what is no use?"
            description={`This removes ${q.data.clean.filter((c) => c.count).map((c) => `${c.count} ${c.label.toLowerCase()}`).join(' and ')}. It cannot be undone. Nothing that belongs to a live record is touched.`}
            confirmLabel="Clear them"
            tone="danger"
            loading={clean.isPending}
            onConfirm={() => clean.mutate()}
          />
        </>
      )}
    </Section>
  )
}
