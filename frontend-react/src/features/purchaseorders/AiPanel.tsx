import { useState } from 'react'
import { Mail, Sparkles } from 'lucide-react'
import { Badge, Button } from '@/components/ui'
import { draftPoEmail, reviewPo, type PoEmail, type PoReview } from '@/api/aiPurchasing'
import { useAction } from '@/lib/mutate'

const TONE = { stop: 'danger', check: 'warning', note: 'neutral' } as const

/** Flags on an order and a draft of the email to the supplier. Nothing is sent from here: a person reads it, then sends it. */
export function AiPanel({ orderId }: { orderId: number }) {
  const [review, setReview] = useState<PoReview | null>(null)
  const [email, setEmail] = useState<PoEmail | null>(null)
  const run = useAction(() => reviewPo(orderId), { success: false, onSuccess: setReview })
  const draft = useAction(() => draftPoEmail(orderId), { success: false, onSuccess: setEmail })
  return (
    <section aria-label="AI help" className="mb-4 rounded-lg border border-border p-3 text-[13.5px]">
      <div className="flex flex-wrap items-center gap-2">
        <span className="mr-auto flex items-center gap-1.5 font-medium"><Sparkles className="size-4" /> Check this order</span>
        <Button size="sm" variant="outline" loading={run.isPending} onClick={() => run.mutate()}>Review it</Button>
        <Button size="sm" variant="outline" loading={draft.isPending} onClick={() => draft.mutate()}><Mail /> Draft the supplier email</Button>
      </div>
      {review && (
        <div aria-label="Order review" className="mt-3 grid gap-2">
          {review.summary && <p>{review.summary}</p>}
          {review.ai_message && <p className="text-muted-foreground">{review.ai_message}</p>}
          {review.flags.length === 0 ? <p className="text-muted-foreground">Nothing unusual found.</p> : (
            <ul className="grid gap-1">{review.flags.map((f) => <li key={f.text} className="flex items-start gap-2"><Badge tone={TONE[f.level]}>{f.level}</Badge><span>{f.text}</span></li>)}</ul>
          )}
        </div>
      )}
      {email && (
        <div aria-label="Email draft" className="mt-3 grid gap-1 border-t border-border pt-3">
          <p className="text-muted-foreground">To {email.to || 'the supplier (no email on the order)'} {email.written_by_ai ? '· worded by AI' : '· standard wording'}</p>
          <p className="font-medium">{email.subject}</p>
          <pre className="whitespace-pre-wrap font-sans">{email.body}</pre>
          <div><Button size="sm" variant="ghost" onClick={() => navigator.clipboard?.writeText(`${email.subject}\n\n${email.body}`)}>Copy</Button></div>
        </div>
      )}
    </section>
  )
}
