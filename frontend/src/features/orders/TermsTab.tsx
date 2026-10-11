import { useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { Button, Select, Textarea } from '@/components/ui'
import { termsLibrary, type OrderTerm, type Vocabulary } from '@/api/orders'
import { toast } from '@/stores/toast'
import { ApiError } from '@/lib/api'

/** The conditions printed on the order, one clause under each heading. */
export function TermsTab({ terms, onTerms, disabled, vocab }: { terms: OrderTerm[]; onTerms: (t: OrderTerm[]) => void; disabled: boolean; vocab: Vocabulary | undefined }) {
  const [loading, setLoading] = useState(false)
  const categories = vocab?.clause_categories ?? []

  const set = (i: number, patch: Partial<OrderTerm>) => onTerms(terms.map((t, x) => (x === i ? { ...t, ...patch } : t)))

  const loadStandard = async () => {
    setLoading(true)
    try {
      const { library } = await termsLibrary()
      onTerms([...terms, ...library.map((l) => ({ clause_category: l.clause_category, clause_text: l.clause_text }))])
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : 'Could not load the standard conditions.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      {!disabled && (
        <div className="mb-4 flex flex-wrap gap-2">
          <Button variant="outline" size="sm" loading={loading} onClick={loadStandard}>
            Add the standard conditions
          </Button>
          <Button variant="outline" size="sm" onClick={() => onTerms([...terms, { clause_category: categories[0] ?? 'General', clause_text: '' }])}>
            <Plus /> Add a clause
          </Button>
        </div>
      )}
      {terms.length === 0 && <p className="rounded-xl border border-dashed border-border py-12 text-center text-sm text-muted-foreground">No conditions on this order. Without its own, the company&apos;s general conditions print.</p>}
      <ol className="space-y-3">
        {terms.map((t, i) => (
          <li key={i} className="rounded-xl border border-border bg-card p-4">
            <div className="mb-2 flex items-center gap-3">
              <span className="tabular grid size-6 shrink-0 place-items-center rounded-full bg-muted text-xs text-muted-foreground">{i + 1}</span>
              <div className="w-72 max-w-full">
                <Select aria-label={`Heading of clause ${i + 1}`} disabled={disabled} value={t.clause_category} onChange={(e) => set(i, { clause_category: e.target.value })} options={[...new Set([t.clause_category, ...categories])].filter(Boolean).map((c) => ({ value: c, label: c }))} />
              </div>
              {!disabled && (
                <Button variant="ghost" size="icon-sm" className="ml-auto" aria-label={`Remove clause ${i + 1}`} onClick={() => onTerms(terms.filter((_, x) => x !== i))}>
                  <Trash2 />
                </Button>
              )}
            </div>
            <Textarea aria-label={`Clause ${i + 1}`} disabled={disabled} value={t.clause_text} onChange={(e) => set(i, { clause_text: e.target.value })} rows={3} />
          </li>
        ))}
      </ol>
    </div>
  )
}
