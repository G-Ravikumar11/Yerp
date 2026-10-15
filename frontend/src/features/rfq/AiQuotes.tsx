import { useState } from 'react'
import { Sparkles } from 'lucide-react'
import { Badge, Button } from '@/components/ui'
import { recommendQuote, type QuoteRecommendation } from '@/api/aiPurchasing'
import { useAction } from '@/lib/mutate'

const TONE = { stop: 'danger', check: 'warning', note: 'neutral' } as const

/** A written recommendation on the quotes in hand. The buyer awards. */
export function Recommendation({ id }: { id: number }) {
  const [rec, setRec] = useState<QuoteRecommendation | null>(null)
  const run = useAction(() => recommendQuote(id), { success: false, onSuccess: setRec })
  return (
    <div className="border-b border-border px-5 py-3 text-[13.5px]">
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="outline" loading={run.isPending} onClick={() => run.mutate()}><Sparkles /> Recommend</Button>
        {!rec && <span className="text-muted-foreground">Flags problems with the quotes and suggests who to award. You decide.</span>}
      </div>
      {rec && (
        <div aria-label="Recommendation" className="mt-3 grid gap-2">
          {rec.recommendation && <p>{rec.recommendation}</p>}
          {rec.ai_message && <p className="text-muted-foreground">{rec.ai_message}</p>}
          {rec.flags.length === 0 ? <p className="text-muted-foreground">No problems found with the quotes.</p> : (
            <ul className="grid gap-1">{rec.flags.map((f) => <li key={f.text} className="flex items-start gap-2"><Badge tone={TONE[f.level]}>{f.level}</Badge><span>{f.text}</span></li>)}</ul>
          )}
        </div>
      )}
    </div>
  )
}
