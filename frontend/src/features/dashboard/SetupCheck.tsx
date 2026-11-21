import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { CircleCheck, ListChecks, TriangleAlert } from 'lucide-react'
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui'
import { get } from '@/lib/api'
import { useSession } from '@/lib/session'

interface SetupItem {
  key: string
  title: string
  detail: string
  count: number
  link: string
  fix: string
  ok: boolean
}

export const useSetupCheck = (enabled: boolean) =>
  useQuery({ queryKey: ['setup-check'], enabled, staleTime: 60_000, queryFn: () => get<{ items: SetupItem[]; to_do: number; total: number }>('/api/setup-check') })

/**
 * What the business's controls rely on that is not yet set - approval routes, budgets, the company's own details - each
 * with the screen that puts it right. Left blank, a control falls back to the Master; this keeps that in sight. Shown to
 * the Master on the Command Center while anything is left, and gone once everything is set.
 */
export function SetupCheck() {
  const { isOwner } = useSession()
  const q = useSetupCheck(isOwner)
  const [showAll, setShowAll] = useState(false)
  if (!isOwner || !q.data || q.data.to_do === 0) return null
  const items = showAll ? q.data.items : q.data.items.filter((i) => !i.ok)
  return (
    <Card className="mb-5 border-warning/40" aria-labelledby="setup-check-title">
      <CardHeader className="pb-2">
        <CardTitle id="setup-check-title" className="flex items-center gap-2 text-base">
          <ListChecks className="size-5 text-warning" aria-hidden /> Setup check - {q.data.to_do} of {q.data.total} still to do
        </CardTitle>
        <CardDescription>Until these are set, the checks that rely on them fall back to you.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {items.map((i) => (
          <div key={i.key} className="flex flex-wrap items-center gap-3 rounded-lg border border-border px-3 py-2.5">
            {i.ok ? <CircleCheck className="size-4 shrink-0 text-success" aria-label="Done" /> : <TriangleAlert className="size-4 shrink-0 text-warning" aria-label="To do" />}
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">{i.title}</p>
              <p className="text-[13px] text-muted-foreground">{i.detail}</p>
            </div>
            {!i.ok && (
              <Button size="sm" asChild>
                <Link to={i.link}>{i.fix}</Link>
              </Button>
            )}
          </div>
        ))}
        <button type="button" onClick={() => setShowAll((v) => !v)} className="text-[13px] font-medium text-primary hover:underline">
          {showAll ? 'Show only what is left' : 'Show what is already done too'}
        </button>
      </CardContent>
    </Card>
  )
}
