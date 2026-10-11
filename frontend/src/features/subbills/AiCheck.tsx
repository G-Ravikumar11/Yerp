import { useState } from 'react'
import { ScanSearch, Sparkles } from 'lucide-react'
import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui'
import { checkHardCopy, reviewBill, useAiStatus, type BillReview, type HardCopyCheck } from '@/api/aiSubcontracts'
import type { SubBill } from '@/api/subbills'
import { useAction } from '@/lib/mutate'
import { formatINR } from '@/lib/utils'

const TONE = { stop: 'danger', check: 'warning', note: 'neutral' } as const

/** A second pair of eyes for whoever certifies: plain-code flags and a short summary, and the hard copy read and compared. The AI suggests; the person decides. */
export function AiCheck({ bill }: { bill: SubBill }) {
  const status = useAiStatus()
  const [review, setReview] = useState<BillReview | null>(null)
  const [copy, setCopy] = useState<HardCopyCheck | null>(null)
  const run = useAction(() => reviewBill(bill.id), { success: false, onSuccess: setReview })
  const read = useAction(() => checkHardCopy(bill.id), { success: false, onSuccess: setCopy })
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Sparkles className="size-4" /> Check this bill</CardTitle>
        <CardDescription>
          Flags anything unusual, and reads the hard copy to compare it with this bill. It suggests; you decide.
          {status.data && !status.data.available && ' The AI part is not set up yet, so only the plain checks run.'}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 text-[13.5px]">
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" loading={run.isPending} onClick={() => run.mutate()}><Sparkles /> Review the bill</Button>
          {bill.hardcopy && <Button variant="outline" size="sm" loading={read.isPending} disabled={!status.data?.reads_photos} title={status.data?.reads_photos ? undefined : 'Reading a scanned bill needs the AI key'} onClick={() => read.mutate()}><ScanSearch /> Read the hard copy</Button>}
        </div>

        {review && (
          <div aria-label="Bill review" className="grid gap-2">
            {review.summary && <p>{review.summary}</p>}
            {review.ai_message && <p className="text-muted-foreground">{review.ai_message}</p>}
            {review.flags.length === 0 ? <p className="text-muted-foreground">Nothing unusual found.</p> : (
              <ul className="grid gap-1">{review.flags.map((f) => <li key={f.text} className="flex items-start gap-2"><Badge tone={TONE[f.level]}>{f.level === 'stop' ? 'stop' : f.level === 'check' ? 'check' : 'note'}</Badge><span>{f.text}</span></li>)}</ul>
            )}
          </div>
        )}

        {copy && (
          <div aria-label="Hard copy reading" className="grid gap-2 border-t border-border pt-3">
            {!copy.available ? <p className="text-muted-foreground">{copy.message}</p> : (
              <>
                <p className="font-medium">
                  {copy.agrees ? <Badge tone="success">The hard copy agrees with this bill</Badge> : <Badge tone="warning">Differences found</Badge>}{' '}
                  {copy.low_confidence && <span className="text-warning">The reading was not confident; check by eye.</span>}
                </p>
                {copy.notes && <p className="text-muted-foreground">{copy.notes}</p>}
                {(copy.mismatches ?? []).map((m) => <p key={m.item}>{m.item}: paper {formatINR(m.paper)}, bill {formatINR(m.bill)} (difference {formatINR(m.difference)})</p>)}
                {(copy.only_on_bill ?? []).map((l) => <p key={'b' + l.description}>On this bill but not on the paper: {l.description}</p>)}
                {(copy.only_on_paper ?? []).map((l) => <p key={'p' + l.description}>On the paper but not on this bill: {l.description}</p>)}
              </>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
