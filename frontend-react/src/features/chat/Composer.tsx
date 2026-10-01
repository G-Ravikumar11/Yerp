import { useRef, useState } from 'react'
import { Paperclip, Send, X } from 'lucide-react'
import { Button, Textarea } from '@/components/ui'
import { attach, chatKeys, sendMessage, usePeople, type ChatFile } from '@/api/chat'
import { useAction } from '@/lib/mutate'
import { toast } from '@/stores/toast'

/** Write a message: Enter sends, Shift+Enter is a new line, "@" offers the people to ring, the paperclip puts photos beside the words. */
export function Composer({ thread }: { thread: number }) {
  const [text, setText] = useState('')
  const [files, setFiles] = useState<ChatFile[]>([])
  const [busy, setBusy] = useState(false)
  const pick = useRef<HTMLInputElement>(null)
  const area = useRef<HTMLTextAreaElement>(null)
  const people = usePeople()
  const send = useAction(() => sendMessage(thread, text.trim(), files.map((f) => f.id)), { invalidate: [chatKeys.all], success: false, onSuccess: () => { setText(''); setFiles([]) } })
  const upto = text.slice(0, area.current?.selectionStart ?? text.length)
  const m = upto.match(/@([\w ]{0,20})$/)
  const hits = m ? (people.data?.people ?? []).filter((p) => p.key !== people.data?.me && p.name.toLowerCase().startsWith(m[1].toLowerCase())).slice(0, 6) : []
  const choose = (name: string) => {
    const at = area.current?.selectionStart ?? text.length
    const before = text.slice(0, at).replace(/@([\w ]{0,20})$/, `@${name} `)
    setText(before + text.slice(at))
    requestAnimationFrame(() => { area.current?.focus(); area.current?.setSelectionRange(before.length, before.length) })
  }
  const add = async (list: FileList | null) => {
    const chosen = list ? [...list] : []
    if (!chosen.length) return
    setBusy(true)
    for (const f of chosen) {
      try { const got = await attach(thread, f); setFiles((x) => [...x, got]) } catch (e) { toast.error(e instanceof Error ? e.message : 'Not attached') }
    }
    setBusy(false)
  }
  const ready = (text.trim() || files.length) && !busy
  return (
    <div className="relative border-t border-border p-3">
      {hits.length > 0 && (
        <ul role="listbox" aria-label="People" className="absolute bottom-full left-3 z-10 mb-1 w-64 overflow-hidden rounded-lg border border-border bg-card shadow-lg">
          {hits.map((p) => <li key={p.key}><button type="button" role="option" aria-selected="false" className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-accent" onMouseDown={(e) => { e.preventDefault(); choose(p.name) }}>{p.name}<span className="text-xs text-muted-foreground">{p.role}</span></button></li>)}
        </ul>
      )}
      {files.length > 0 && <div className="mb-2 flex flex-wrap gap-1.5">{files.map((f, i) => <span key={f.id} className="inline-flex items-center gap-1 rounded-full bg-muted px-2.5 py-1 text-xs">{f.name}<button type="button" aria-label={`Remove ${f.name}`} onClick={() => setFiles(files.filter((_, j) => j !== i))}><X className="size-3" /></button></span>)}</div>}
      <div className="flex items-end gap-2">
        <input ref={pick} type="file" multiple className="sr-only" aria-label="Attach files" onChange={(e) => { void add(e.target.files); e.target.value = '' }} />
        <Button type="button" variant="ghost" size="icon" aria-label="Attach a photo or file" loading={busy} onClick={() => pick.current?.click()}><Paperclip /></Button>
        <Textarea ref={area} aria-label="Message" rows={1} className="min-h-10 flex-1 resize-none" value={text} placeholder="Write a message. @ to ring somebody." onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !hits.length) { e.preventDefault(); if (ready) send.mutate() } }} />
        <Button aria-label="Send" loading={send.isPending} disabled={!ready} onClick={() => send.mutate()}><Send /></Button>
      </div>
    </div>
  )
}
