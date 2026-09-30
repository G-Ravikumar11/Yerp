import { Card, CardContent, CardDescription, CardHeader, CardTitle, Field, Input, NumField, Select, Textarea } from '@/components/ui'
import { useBusinessUnits, useContractors, useOrderVocabulary, type Order, type OrderHead } from '@/api/orders'

export const BILLING_CYCLES = ['Monthly', 'Fortnightly', 'On milestone', 'On completion']

export function headFrom(o: Order): OrderHead {
  return {
    business_unit_id: o.business_unit_id,
    contractor_id: o.contractor_id,
    job_id: o.job_id,
    department: o.department,
    work_type: o.work_type,
    subject: o.subject,
    scope_of_work: o.scope_of_work,
    commencement_date: o.commencement_date,
    completion_date: o.completion_date,
    duration_months: o.duration_months,
    defect_liability_months: o.defect_liability_months,
    bank_guarantee_applicable: o.bank_guarantee_applicable,
    bank_guarantee_amount: o.bank_guarantee_amount,
    bank_guarantee_validity: o.bank_guarantee_validity,
    gst_rate: o.gst_rate,
    tds_rate: o.tds_rate,
    retention_percent: o.retention_percent,
    mobilization_advance_percent: o.mobilization_advance_percent,
    advance_recovery_percent: o.advance_recovery_percent,
    labour_cess_percent: o.labour_cess_percent,
    billing_cycle: o.billing_cycle,
    payment_days: o.payment_days,
  }
}

const id = (v: string) => (v ? Number(v) : null)

/** The order's particulars: who, where, when, and on what terms it is paid. */
export function HeadForm({ head, onChange, disabled, order }: { head: OrderHead; onChange: (patch: Partial<OrderHead>) => void; disabled: boolean; order: Order }) {
  const vocab = useOrderVocabulary()
  const units = useBusinessUnits()
  const contractors = useContractors()
  const v = vocab.data

  const gang = (contractors.data?.contractors ?? []).filter((c) => c.registration_status === 'APPROVED' || c.id === head.contractor_id)
  const workTypes = (v?.work_types ?? []).filter((w) => !head.department || w.department === head.department)

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle>Who and where</CardTitle>
          <CardDescription>The company issuing it, the gang it is for, and the project it is charged to.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <Field label="Issued by" htmlFor="h-unit" hint="Its logo, GSTIN and PAN print on the order.">
            <Select id="h-unit" disabled={disabled} value={head.business_unit_id ?? ''} onChange={(e) => onChange({ business_unit_id: id(e.target.value) })} placeholder="Choose" options={(units.data ?? []).map((u) => ({ value: u.id, label: u.name }))} />
          </Field>
          <Field label="Sub contractor" htmlFor="h-con" hint="Only registered gangs can be issued an order.">
            <Select id="h-con" disabled={disabled} value={head.contractor_id ?? ''} onChange={(e) => onChange({ contractor_id: id(e.target.value) })} placeholder="Choose" options={gang.map((c) => ({ value: c.id, label: c.company_name + (c.vendor_code ? ` (${c.vendor_code})` : '') }))} />
          </Field>
          <Field label="Project" htmlFor="h-job" hint="Its budget is what this order is held against.">
            <Select id="h-job" disabled={disabled} value={head.job_id ?? ''} onChange={(e) => onChange({ job_id: id(e.target.value) })} placeholder="Choose" options={(v?.jobs ?? []).map((j) => ({ value: j.id, label: `${j.number} ${j.name}` }))} />
          </Field>
          <Field label="Trade" htmlFor="h-dept" hint={disabled ? undefined : 'Changing it on a draft issues a new number.'}>
            <Select id="h-dept" disabled={disabled} value={head.department} onChange={(e) => onChange({ department: e.target.value })} placeholder="Choose" options={(v?.departments ?? []).map((d) => ({ value: d, label: d }))} />
          </Field>
          <Field label="Kind of work" htmlFor="h-type">
            <Select id="h-type" disabled={disabled} value={head.work_type} onChange={(e) => onChange({ work_type: e.target.value })} placeholder="Choose" options={workTypes.map((w) => ({ value: w.name, label: w.name }))} />
          </Field>
          <Field label="Subject" htmlFor="h-subject" hint="What the order is called on paper.">
            <Input id="h-subject" disabled={disabled} value={head.subject} onChange={(e) => onChange({ subject: e.target.value })} placeholder="Shuttering, tower C" />
          </Field>
          <Field label="Scope of work" htmlFor="h-scope" className="sm:col-span-2">
            <Textarea id="h-scope" disabled={disabled} value={head.scope_of_work} onChange={(e) => onChange({ scope_of_work: e.target.value })} rows={4} />
          </Field>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Programme</CardTitle>
          <CardDescription>Both dates are needed before it can be sent for approval.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <Field label="Starts" htmlFor="h-start">
            <Input id="h-start" type="date" disabled={disabled} value={head.commencement_date} onChange={(e) => onChange({ commencement_date: e.target.value })} />
          </Field>
          <Field label="Completes" htmlFor="h-end">
            <Input id="h-end" type="date" disabled={disabled} value={head.completion_date} onChange={(e) => onChange({ completion_date: e.target.value })} />
          </Field>
          <Field label="Duration (months)" htmlFor="h-dur">
            <NumField id="h-dur" disabled={disabled} value={head.duration_months} onValue={(n) => onChange({ duration_months: n })} />
          </Field>
          <Field label="Defect liability (months)" htmlFor="h-dlp">
            <NumField id="h-dlp" disabled={disabled} value={head.defect_liability_months} onValue={(n) => onChange({ defect_liability_months: Math.round(n) })} />
          </Field>
          <Field label="Billed" htmlFor="h-cycle">
            <Select id="h-cycle" disabled={disabled} value={head.billing_cycle} onChange={(e) => onChange({ billing_cycle: e.target.value })} placeholder="Not set" options={BILLING_CYCLES.map((c) => ({ value: c, label: c }))} />
          </Field>
          <Field label="Paid within (days)" htmlFor="h-days">
            <NumField id="h-days" disabled={disabled} value={head.payment_days} onValue={(n) => onChange({ payment_days: Math.round(n) })} />
          </Field>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Tax, retention and advance</CardTitle>
          <CardDescription>How the gang is paid on every RA bill against this order.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <Field label="GST" htmlFor="h-gst">
            <Select id="h-gst" disabled={disabled} value={head.gst_rate} onChange={(e) => onChange({ gst_rate: Number(e.target.value) })} options={(v?.gst_rates ?? [0, 5, 12, 18, 28]).map((r) => ({ value: r, label: `${r}%` }))} />
          </Field>
          <Field label="TDS" htmlFor="h-tds">
            <Select id="h-tds" disabled={disabled} value={head.tds_rate} onChange={(e) => onChange({ tds_rate: Number(e.target.value) })} options={(v?.tds_options ?? [{ rate: 1, label: '1%' }]).map((t) => ({ value: t.rate, label: t.label }))} />
          </Field>
          <Field label="Retention (%)" htmlFor="h-ret" hint="Held back from every bill.">
            <NumField id="h-ret" disabled={disabled} value={head.retention_percent} onValue={(n) => onChange({ retention_percent: n })} />
          </Field>
          <Field label="Labour cess (%)" htmlFor="h-cess">
            <NumField id="h-cess" disabled={disabled} value={head.labour_cess_percent} onValue={(n) => onChange({ labour_cess_percent: n })} />
          </Field>
          <Field label="Mobilisation advance (%)" htmlFor="h-adv" hint={order.mobilization_advance_amount ? `${order.mobilization_advance_amount.toLocaleString('en-IN')} on this order` : undefined}>
            <NumField id="h-adv" disabled={disabled} value={head.mobilization_advance_percent} onValue={(n) => onChange({ mobilization_advance_percent: n })} />
          </Field>
          <Field label="Recovered per bill (%)" htmlFor="h-rec" hint="Of the advance paid.">
            <NumField id="h-rec" disabled={disabled} value={head.advance_recovery_percent} onValue={(n) => onChange({ advance_recovery_percent: n })} />
          </Field>
          <label className="flex items-center gap-2.5 text-[13px] font-medium sm:col-span-2">
            <input type="checkbox" disabled={disabled} checked={head.bank_guarantee_applicable} onChange={(e) => onChange({ bank_guarantee_applicable: e.target.checked })} className="size-4 accent-[var(--primary)]" />
            A bank guarantee is required
          </label>
          {head.bank_guarantee_applicable && (
            <>
              <Field label="Guarantee amount" htmlFor="h-bg">
                <NumField id="h-bg" disabled={disabled} value={head.bank_guarantee_amount} onValue={(n) => onChange({ bank_guarantee_amount: n })} />
              </Field>
              <Field label="Valid until" htmlFor="h-bgv">
                <Input id="h-bgv" type="date" disabled={disabled} value={head.bank_guarantee_validity} onChange={(e) => onChange({ bank_guarantee_validity: e.target.value })} />
              </Field>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
