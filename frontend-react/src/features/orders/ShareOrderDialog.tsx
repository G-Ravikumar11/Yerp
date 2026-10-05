import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Button, Modal, Skeleton } from '@/components/ui'
import { get, put } from '@/lib/api'
import { useAction } from '@/lib/mutate'

interface Person {
  id: number
  name: string
  department: string
  shared: boolean
  on_route: boolean
}

/**
 * Staff see only the orders they made or have to sign. The owner, or whoever made the order, can let
 * others in - a site engineer who measures it, a clerk who bills it.
 */
export function ShareOrderDialog({ open, onOpenChange, orderId, number }: { open: boolean; onOpenChange: (o: boolean) => void; orderId: number; number: string }) {
  const q = useQuery({ queryKey: ['order-access', orderId], queryFn: () => get<{ people: Person[] }>(`/api/wo/orders/${orderId}/access`), enabled: open && orderId > 0, gcTime: 0, staleTime: 0 })
  const [ids, setIds] = useState<number[]>([])
  useEffect(() => {
    if (q.data) setIds(q.data.people.filter((p) => p.shared).map((p) => p.id))
  }, [q.data])
  const save = useAction(() => put<{ message?: string }>(`/api/wo/orders/${orderId}/access`, { employee_ids: ids }), { invalidate: [['order-access', orderId]], onSuccess: () => onOpenChange(false) })
  const toggle = (id: number) => setIds((cur) => (cur.includes(id) ? cur.filter((i) => i !== id) : [...cur, id]))
  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={`Who can see ${number}?`}
      description="The Master, the one who made it and those who sign it always can. Tick anyone else who needs it - to measure it, bill it or read it."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button loading={save.isPending} onClick={() => save.mutate()}>Save</Button>
        </>
      }
    >
      {q.isPending ? (
        <Skeleton className="h-24 w-full" />
      ) : q.isError ? (
        <p className="text-sm text-danger">Only the Master, or whoever made the order, can change this.</p>
      ) : q.data!.people.length === 0 ? (
        <p className="text-sm text-muted-foreground">There is no other staff to share it with.</p>
      ) : (
        <ul className="max-h-80 divide-y divide-border overflow-y-auto text-sm">
          {q.data!.people.map((p) => (
            <li key={p.id}>
              <label className="flex items-center gap-3 py-2">
                <input type="checkbox" checked={ids.includes(p.id) || p.on_route} disabled={p.on_route} onChange={() => toggle(p.id)} />
                <span className="flex-1">
                  {p.name}
                  {p.department && <span className="ml-2 text-xs text-muted-foreground">{p.department}</span>}
                </span>
                {p.on_route && <span className="text-xs text-muted-foreground">signs it</span>}
              </label>
            </li>
          ))}
        </ul>
      )}
    </Modal>
  )
}
