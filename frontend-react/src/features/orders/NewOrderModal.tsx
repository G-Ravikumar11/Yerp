import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Field, Input, Modal, Select } from '@/components/ui'
import { createOrder, orderKeys, useBusinessUnits, useContractors, useOrderVocabulary } from '@/api/orders'
import { useAction } from '@/lib/mutate'

/**
 * Opens a draft. Only the few things that decide the order's number and
 * routing are asked here; the schedule, dates and terms are filled in on the
 * order itself, where a half-finished draft can wait.
 */
export function NewOrderModal({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const nav = useNavigate()
  const vocab = useOrderVocabulary()
  const units = useBusinessUnits()
  const contractors = useContractors()
  const [f, setF] = useState({ contractor_id: '', job_id: '', department: '', subject: '' })
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF((s) => ({ ...s, [k]: e.target.value }))

  const create = useAction(
    () =>
      createOrder({
        contractor_id: f.contractor_id ? Number(f.contractor_id) : null,
        job_id: f.job_id ? Number(f.job_id) : null,
        department: f.department,
        subject: f.subject,
        // The company itself, when it is the only one there is.
        business_unit_id: units.data?.length === 1 ? units.data[0].id : null,
      }),
    {
      invalidate: [orderKeys.all],
      onSuccess: (res) => {
        onOpenChange(false)
        setF({ contractor_id: '', job_id: '', department: '', subject: '' })
        nav(`/subcontractors/work-orders/${res.order.id}`)
      },
    },
  )

  const registered = (contractors.data?.contractors ?? []).filter((c) => c.registration_status === 'APPROVED')

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title="New work order"
      description="It opens as a draft with its number issued. You can finish it later."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button loading={create.isPending} onClick={() => create.mutate()}>
            Open the draft
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        <Field label="Sub contractor" htmlFor="no-con" hint="Only gangs whose registration form has been signed off can be issued an order.">
          <Select id="no-con" value={f.contractor_id} onChange={set('contractor_id')} placeholder="Choose later" options={registered.map((c) => ({ value: c.id, label: c.company_name + (c.vendor_code ? ` (${c.vendor_code})` : '') }))} />
        </Field>
        <Field label="Project" htmlFor="no-job">
          <Select id="no-job" value={f.job_id} onChange={set('job_id')} placeholder="Choose later" options={(vocab.data?.jobs ?? []).map((j) => ({ value: j.id, label: `${j.number} ${j.name}` }))} />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Trade" htmlFor="no-dept" hint="Sets the series the number comes from.">
            <Select id="no-dept" value={f.department} onChange={set('department')} placeholder="Choose later" options={(vocab.data?.departments ?? []).map((d) => ({ value: d, label: d }))} />
          </Field>
          <Field label="What is the work?" htmlFor="no-subject">
            <Input id="no-subject" value={f.subject} onChange={set('subject')} placeholder="Shuttering, tower C" />
          </Field>
        </div>
      </div>
    </Modal>
  )
}
