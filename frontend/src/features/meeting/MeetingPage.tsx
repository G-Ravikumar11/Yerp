import { useEffect, useRef, useState } from 'react'
import { Hand, Lock, LockOpen, LogOut, Mic, MicOff, MonitorUp, Video, VideoOff, VolumeX } from 'lucide-react'
import { Button, Field, Input } from '@/components/ui'
import { api } from '@/lib/api'
import { AuthLayout } from '@/features/auth/AuthLayout'
import { useMeeting, type Person } from './useMeeting'
import { appUrl } from '@/lib/paths'

const newRoom = () => Math.random().toString(36).slice(2, 5) + '-' + Math.random().toString(36).slice(2, 6) + '-' + Math.random().toString(36).slice(2, 5)

function Tile({ stream, name, muted, off, local, hand, sharing }: { stream?: MediaStream | null; name: string; muted?: boolean; off?: boolean; local?: boolean; hand?: boolean; sharing?: boolean }) {
  const ref = useRef<HTMLVideoElement>(null)
  useEffect(() => { if (ref.current && stream) ref.current.srcObject = stream }, [stream])
  return (
    <div className="relative aspect-video overflow-hidden rounded-xl bg-slate-900">
      <video ref={ref} autoPlay playsInline muted={local} className={`size-full ${sharing ? 'object-contain' : 'object-cover'} ${off ? 'opacity-0' : ''}`} />
      <span className="absolute bottom-2 left-2 rounded bg-black/60 px-2 py-0.5 text-xs text-white">{local ? 'You' : name}{muted && ' · muted'}{sharing && ' · sharing'}</span>
      {hand && <span className="absolute right-2 top-2 text-lg" aria-label="Hand raised">✋</span>}
    </div>
  )
}

/** A video room: everyone who opens the same room name joins the same call. Signed-in people only (the server checks). */
export default function MeetingPage() {
  const params = new URLSearchParams(window.location.search)
  const [name, setName] = useState('')
  const [room, setRoom] = useState(params.get('room') ?? '')
  const [joined, setJoined] = useState(false)
  const [signedIn, setSignedIn] = useState<boolean | null>(null)

  useEffect(() => {
    document.title = 'Meeting - Y ERP'
    void (async () => {
      for (const [url, field] of [['/api/client/me', 'contact_name'], ['/api/employee/auth/me', 'name']] as const) {
        const me = await api<Record<string, string>>(url, { quiet: true }).catch(() => null)
        if (me) { setName(me[field] || me.name || me.company_name || ''); return setSignedIn(true) }
      }
      setSignedIn(false)
    })()
  }, [])
  useEffect(() => { if (signedIn === false) window.location.assign(appUrl('login?next=') + encodeURIComponent(appUrl('meeting') + window.location.search)) }, [signedIn])

  if (signedIn === null || signedIn === false) return null
  if (!joined) {
    return (
      <AuthLayout title="Join a meeting" subtitle="Anyone with the room name can join once signed in." mark="▶">
        <form className="grid gap-4" onSubmit={(e) => { e.preventDefault(); setRoom((r) => r.trim() || newRoom()); setJoined(true) }}>
          <Field label="Your name" htmlFor="join-name"><Input id="join-name" value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label="Room" htmlFor="join-room" hint="Leave empty to start a new room."><Input id="join-room" value={room} onChange={(e) => setRoom(e.target.value)} placeholder="abc-defg-hij" /></Field>
          <Button type="submit">Join</Button>
        </form>
      </AuthLayout>
    )
  }
  return <Room room={room.trim() || newRoom()} name={name.trim() || 'Guest'} />
}

function Room({ room, name }: { room: string; name: string }) {
  const m = useMeeting(room, name, true)
  const [text, setText] = useState('')
  const [open, setOpen] = useState(true)
  const link = `${location.origin}${appUrl('meeting')}?room=${encodeURIComponent(room)}`

  if (m.ended) return <AuthLayout title="Meeting ended" mark="■"><p className="mb-4 text-center text-sm text-muted-foreground">{m.ended}</p><div className="text-center"><Button asChild><a href={appUrl('meeting')}>Join another</a></Button></div></AuthLayout>
  const sharer = m.people.find((p: Person) => p.sharing)
  return (
    <div className="flex h-screen flex-col bg-slate-950 text-white">
      <header className="flex flex-wrap items-center justify-between gap-2 px-4 py-2 text-sm">
        <span>Room <b className="font-mono">{room}</b> · {m.people.length + 1} in the call</span>
        <button className="rounded bg-white/10 px-2 py-1 text-xs hover:bg-white/20" onClick={() => void navigator.clipboard?.writeText(link)}>Copy invite link</button>
      </header>
      {m.waiting && <p role="status" className="bg-warning/20 px-4 py-2 text-center text-sm">Waiting for the host to let you in...</p>}
      {m.notice && <button className="bg-info/20 px-4 py-2 text-center text-sm" onClick={m.clearNotice}>{m.notice}</button>}
      {m.requests.map((r) => <div key={r.id} className="flex items-center justify-between gap-3 bg-white/10 px-4 py-2 text-sm"><span><b>{r.name}</b> wants to join</span><span className="flex gap-2"><Button size="sm" onClick={() => m.decide(r.id, true)}>Admit</Button><Button size="sm" variant="outline" className="text-foreground" onClick={() => m.decide(r.id, false)}>Deny</Button></span></div>)}
      <div className="flex min-h-0 flex-1">
        <div className={`grid flex-1 content-start gap-3 overflow-y-auto p-3 ${m.people.length > 0 ? 'sm:grid-cols-2' : ''} ${m.people.length > 3 ? 'lg:grid-cols-3' : ''}`}>
          {sharer && <div className="sm:col-span-full"><Tile stream={sharer.stream} name={sharer.name} sharing /></div>}
          <Tile local stream={m.localStream} name={name} off={!m.cam} muted={!m.mic} hand={false} />
          {m.people.filter((p) => !p.sharing).map((p) => <div key={p.id} className="group relative"><Tile stream={p.stream} name={p.name} muted={p.muted} off={p.videoOff} hand={p.hand} />{m.host && <button className="absolute right-2 top-2 hidden rounded bg-black/70 px-2 py-0.5 text-xs group-hover:block" onClick={() => m.remove(p.id)}>Remove</button>}</div>)}
        </div>
        {open && (
          <aside aria-label="Chat" className="hidden w-72 flex-col border-l border-white/10 sm:flex">
            <div className="flex-1 space-y-2 overflow-y-auto p-3 text-sm">
              {m.chat.map((c, i) => c.system ? <p key={i} className="text-center text-xs text-white/50">{c.text}</p> : <p key={i}><b className={c.mine ? 'text-blue-300' : 'text-emerald-300'}>{c.name}</b> {c.text}</p>)}
            </div>
            <form className="flex gap-2 border-t border-white/10 p-2" onSubmit={(e) => { e.preventDefault(); m.sendChat(text); setText('') }}>
              <input aria-label="Message" value={text} onChange={(e) => setText(e.target.value)} placeholder="Message everyone" className="min-w-0 flex-1 rounded bg-white/10 px-2 py-1 text-sm outline-none" />
              <Button size="sm" type="submit">Send</Button>
            </form>
          </aside>
        )}
      </div>
      <footer className="flex flex-wrap items-center justify-center gap-2 border-t border-white/10 p-3">
        <Button variant={m.mic ? 'outline' : 'primary'} aria-label={m.mic ? 'Mute' : 'Unmute'} onClick={m.toggleMic}>{m.mic ? <Mic /> : <MicOff />}</Button>
        <Button variant={m.cam ? 'outline' : 'primary'} aria-label={m.cam ? 'Camera off' : 'Camera on'} onClick={m.toggleCam}>{m.cam ? <Video /> : <VideoOff />}</Button>
        <Button variant="outline" aria-label={m.sharing ? 'Stop sharing' : 'Share screen'} onClick={() => void m.share()}><MonitorUp /></Button>
        <Button variant="outline" aria-label="Raise hand" onClick={m.raiseHand}><Hand /></Button>
        <Button variant="outline" onClick={() => setOpen((o) => !o)}>Chat</Button>
        {m.host && <>
          <Button variant="outline" aria-label="Mute everyone" onClick={m.muteAll}><VolumeX /></Button>
          <Button variant="outline" aria-label={m.locked ? 'Unlock meeting' : 'Lock meeting'} onClick={m.toggleLock}>{m.locked ? <Lock /> : <LockOpen />}</Button>
        </>}
        <Button variant="danger" aria-label="Leave" onClick={m.leave}><LogOut /> Leave</Button>
      </footer>
    </div>
  )
}
