import { useCallback, useEffect, useRef, useState } from 'react'

const ICE = { iceServers: [{ urls: 'stun:stun.l.google.com:19302' }, { urls: 'stun:stun1.l.google.com:19302' }, { urls: 'stun:stun2.l.google.com:19302' }] }

export interface Person { id: string; name: string; stream?: MediaStream; muted?: boolean; videoOff?: boolean; hand?: boolean; sharing?: boolean }
export interface Chat { name: string; text: string; mine?: boolean; system?: boolean }
export interface Request { id: string; name: string }

type Msg = Record<string, any> // eslint-disable-line @typescript-eslint/no-explicit-any

/** One video meeting: the signalling socket, a peer connection to everyone else in the room, and the local camera and microphone. */
export function useMeeting(room: string, name: string, active: boolean) {
  const me = useRef('user-' + Math.random().toString(36).slice(2, 10))
  const ws = useRef<WebSocket | null>(null)
  const peers = useRef<Record<string, RTCPeerConnection>>({})
  const local = useRef<MediaStream | null>(null)
  const screen = useRef<MediaStream | null>(null)
  const closing = useRef(false)

  const [localStream, setLocalStream] = useState<MediaStream | null>(null)
  const [people, setPeople] = useState<Record<string, Person>>({})
  const [chat, setChat] = useState<Chat[]>([])
  const [mic, setMic] = useState(true)
  const [cam, setCam] = useState(true)
  const [sharing, setSharing] = useState(false)
  const [host, setHost] = useState(false)
  const [waiting, setWaiting] = useState(false)
  const [locked, setLocked] = useState(false)
  const [requests, setRequests] = useState<Request[]>([])
  const [ended, setEnded] = useState('')
  const [notice, setNotice] = useState('')

  const send = useCallback((m: Msg) => { if (ws.current?.readyState === WebSocket.OPEN) ws.current.send(JSON.stringify(m)) }, [])
  const patch = useCallback((id: string, p: Partial<Person>) => setPeople((s) => ({ ...s, [id]: { ...(s[id] ?? { id, name: id }), ...p } })), [])
  const say = useCallback((text: string) => setChat((c) => [...c, { name: '', text, system: true }]), [])

  const drop = useCallback((id: string) => {
    peers.current[id]?.close()
    delete peers.current[id]
    setPeople((s) => { const n = { ...s }; delete n[id]; return n })
  }, [])

  const connect = useCallback((id: string, initiator: boolean) => {
    peers.current[id]?.close()
    const pc = new RTCPeerConnection(ICE)
    peers.current[id] = pc
    const stream = local.current
    stream?.getTracks().forEach((t) => pc.addTrack(t, stream))
    if (screen.current) pc.addTrack(screen.current.getVideoTracks()[0], screen.current)
    pc.onicecandidate = (e) => e.candidate && send({ type: 'ice-candidate', candidate: e.candidate, target: id })
    pc.ontrack = (e) => { if (e.track.kind === 'video' || e.streams[0]) patch(id, { stream: e.streams[0] }) }
    pc.onnegotiationneeded = async () => {
      try { await pc.setLocalDescription(await pc.createOffer()); send({ type: 'offer', offer: pc.localDescription, target: id }) } catch { /* the other side will offer */ }
    }
    pc.onconnectionstatechange = () => { if (pc.connectionState === 'failed') drop(id) }
    void initiator
    return pc
  }, [drop, patch, send])

  const leave = useCallback(() => {
    closing.current = true
    ws.current?.close()
    Object.values(peers.current).forEach((p) => p.close())
    peers.current = {}
    local.current?.getTracks().forEach((t) => t.stop())
    screen.current?.getTracks().forEach((t) => t.stop())
    local.current = null
    screen.current = null
    setLocalStream(null)
    setPeople({})
    setEnded((e) => e || 'You left the meeting.')
  }, [])

  const handle = useCallback(async (m: Msg) => {
    switch (m.type) {
      case 'welcome':
        setWaiting(false); setHost(!!m.is_host)
        for (const uid of m.participants ?? []) { patch(uid, { name: uid }); connect(uid, true) }
        break
      case 'user-joined': patch(m.user_id, { name: m.name }); say(`${m.name} joined the meeting`); break
      case 'user-left': drop(m.user_id); say(`${m.name} left the meeting`); break
      case 'offer': {
        patch(m.from, { name: m.name || m.from })
        const pc = peers.current[m.from] ?? connect(m.from, false)
        try {
          await pc.setRemoteDescription(m.offer)
          await pc.setLocalDescription(await pc.createAnswer())
          send({ type: 'answer', answer: pc.localDescription, target: m.from })
        } catch { /* a clash of offers: the next one settles it */ }
        break
      }
      case 'answer': try { await peers.current[m.from]?.setRemoteDescription(m.answer) } catch { /* stale answer */ } break
      case 'ice-candidate': try { await peers.current[m.from]?.addIceCandidate(m.candidate) } catch { /* candidate for a closed connection */ } break
      case 'chat': setChat((c) => [...c, { name: m.name, text: m.message }]); break
      case 'toggle-media': patch(m.user_id, m.kind === 'audio' ? { muted: m.muted } : { videoOff: m.muted }); break
      case 'screen-share-started': patch(m.user_id, { sharing: true }); say(`${m.name} is sharing their screen`); break
      case 'screen-share-stopped': patch(m.user_id, { sharing: false }); break
      case 'raise-hand': patch(m.user_id, { hand: true }); setNotice(`${m.name} raised their hand`); break
      case 'waiting': setWaiting(true); break
      case 'denied': setEnded('The host did not let you in.'); leave(); break
      case 'removed': setEnded('You were removed by the host.'); leave(); break
      case 'join-request': setRequests((r) => [...r, { id: m.user_id, name: m.name }]); break
      case 'force-mute': local.current?.getAudioTracks().forEach((t) => { t.enabled = false }); setMic(false); setNotice('The host muted your microphone'); break
      case 'room-locked': setLocked(!!m.locked); break
    }
  }, [connect, drop, leave, patch, say, send])

  useEffect(() => {
    if (!active) return
    closing.current = false
    let alive = true
    const open = () => {
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
      const sock = new WebSocket(`${proto}//${location.host}/ws/meeting/${encodeURIComponent(room)}?user_id=${me.current}&name=${encodeURIComponent(name)}`)
      ws.current = sock
      sock.onmessage = (e) => void handle(JSON.parse(e.data))
      sock.onclose = () => { if (alive && !closing.current) setTimeout(() => alive && open(), 3000) }
    }
    ;(async () => {
      try { local.current = await navigator.mediaDevices.getUserMedia({ video: true, audio: true }) }
      catch {
        try { local.current = await navigator.mediaDevices.getUserMedia({ video: false, audio: true }); setCam(false) }
        catch { setNotice('No camera or microphone could be used. You can still watch and chat.') }
      }
      if (!alive) return
      setLocalStream(local.current)
      open()
    })()
    return () => { alive = false; leave() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, room, name])

  const toggleMic = () => { const on = !mic; local.current?.getAudioTracks().forEach((t) => { t.enabled = on }); setMic(on); send({ type: 'toggle-media', kind: 'audio', muted: !on }) }
  const toggleCam = () => { const on = !cam; local.current?.getVideoTracks().forEach((t) => { t.enabled = on }); setCam(on); send({ type: 'toggle-media', kind: 'video', muted: !on }) }

  const share = async () => {
    if (screen.current) {
      screen.current.getTracks().forEach((t) => t.stop())
      screen.current = null
      Object.values(peers.current).forEach((pc) => pc.getSenders().filter((s) => s.track && s.track.label.toLowerCase().includes('screen')).forEach((s) => pc.removeTrack(s)))
      setSharing(false); send({ type: 'screen-share-stopped' })
      return
    }
    try {
      const s = await navigator.mediaDevices.getDisplayMedia({ video: true })
      screen.current = s
      Object.values(peers.current).forEach((pc) => pc.addTrack(s.getVideoTracks()[0], s))
      s.getVideoTracks()[0].onended = () => void share()
      setSharing(true); send({ type: 'screen-share-started' })
    } catch { /* cancelled */ }
  }

  const sendChat = (text: string) => { if (!text.trim()) return; send({ type: 'chat', message: text }); setChat((c) => [...c, { name: 'You', text, mine: true }]) }
  const decide = (id: string, ok: boolean) => { send({ type: ok ? 'admit-user' : 'deny-user', target: id }); setRequests((r) => r.filter((x) => x.id !== id)) }

  return {
    id: me.current, localStream, people: Object.values(people), chat, mic, cam, sharing, host, waiting, locked, requests, ended, notice,
    toggleMic, toggleCam, share, sendChat, leave, decide, clearNotice: () => setNotice(''),
    raiseHand: () => send({ type: 'raise-hand' }), muteAll: () => send({ type: 'mute-all' }), remove: (id: string) => send({ type: 'remove-user', target: id }),
    toggleLock: () => send({ type: 'toggle-lock', locked: !locked }),
  }
}
