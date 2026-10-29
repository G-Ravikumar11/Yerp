import { Bot } from 'lucide-react'

/** Marks a feature as AI-assisted: a plain bot icon and a small "AI" label, in the neutral greys. */
export function AiMark() {
  return (
    <span className="inline-flex items-center gap-1.5">
      <Bot className="size-4 text-muted-foreground" aria-hidden />
      <span className="rounded-sm bg-surface px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">AI</span>
    </span>
  )
}
