import { Card, CardContent, CardDescription, CardHeader, CardTitle, Field, Input, NumField, Select, Textarea } from '@/components/ui'
import { departmentsForSite, useBusinessUnits, useContractors, useOrderVocabulary, type Order, type OrderHead } from '@/api/orders'

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
    bank_guarantee_number: o.bank_guarantee_number ?? '',
    bank_guarantee_bank: o.bank_guarantee_bank ?? '',
    gst_rate: o.gst_rate,
    tds_rate: o.tds_rate,
    retention_percent: o.retention_percent,
    mobilization_advance_percent: o.mobilization_advance_percent,
    advance_recovery_percent: o.advance_recovery_percent,
    labour_cess_percent: o.labour_cess_percent,
    billing_cycle: o.billing_cycle,
    payment_days: o.payment_days,
    ld_percent_per_week: o.ld_percent_per_week ?? 0,
    ld_cap_percent: o.ld_cap_percent ?? 0,
  }
}

const id = (v: string) => (v ? Number(v) : null)

/** The order's particulars: who, where, when, and on what terms it is paid. */
export function HeadForm({ head, onChange, disabled, order }: { head: OrderHead; onChange: (patch: Partial<OrderHead>) => void; disabled: boolean; order: Order }) {
  const vocab = useOrderVocabulary()
  const units = useBusinessUnits()
  const contractors = useContractors()
  const v = vocab.data

  const contractor = (contractors.data?.contractors ?? []).filter((c) => c.registration_status === 'APPROVED' || c.id === head.contractor_id)
  const picked = (contractors.data?.contractors ?? []).find((c) => c.id === head.contractor_id)
  // The TDS the law sets for whoever is picked; an order below it needs the Master's reason to be approved.
  const statutory = picked?.tds_rate ?? order.statutory_tds?.rate ?? null
  const basis = picked?.tds_basis ?? order.statutory_tds?.why ?? ''
  const tdsOptions = (v?.tds_options ?? [{ rate: 1, label: '1%' }]).map((t) => ({ value: t.rate, label: t.label }))
  const workTypes = (v?.work_types ?? []).filter((w) => !head.department || w.department === head.department)

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle>Who and where</CardTitle>
          <CardDescription>The company issuing it, the contractor it is for, and the project it is charged to.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <Field label="Issued by" htmlFor="h-unit" hint="Its logo, GSTIN and PAN print on the order.">
            <Select id="h-unit" disabled={disabled} value={head.business_unit_id ?? ''} onChange={(e) => onChange({ business_unit_id: id(e.target.value) })} placeholder="Choose" options={(units.data ?? []).map((u) => ({ value: u.id, label: u.name }))} />
          </Field>
          <Field label="Sub contractor" htmlFor="h-con" hint="Only registered contractors can be issued an order.">
            <Select
              id="h-con"
              disabled={disabled}
              value={head.contractor_id ?? ''}
              onChange={(e) => {
                const next = id(e.target.value)
                const rate = (contractors.data?.contractors ?? []).find((c) => c.id === next)?.tds_rate
                // A new contractor brings the TDS the law sets for them.
                onChange(rate != null ? { contractor_id: next, tds_rate: rate } : { contractor_id: next })
              }}
              placeholder="Choose"
              options={contractor.map((c) => ({ value: c.id, label: c.company_name + (c.vendor_code ? ` (${c.vendor_code})` : '') }))}
            />
          </Field>
          <Field label="Project" htmlFor="h-job" hint="Its budget is what this order is held against.">
            <Select id="h-job" disabled={disabled} value={head.job_id ?? ''} onChange={(e) => onChange({ job_id: id(e.target.value) })} placeholder="Choose" options={(v?.jobs ?? []).map((j) => ({ value: j.id, label: `${j.number} ${j.name}` }))} />
          </Field>
          <Field label="Trade" htmlFor="h-dept" hint={disabled ? undefined : 'Changing it on a draft issues a new number.'}>
            <Select id="h-dept" disabled={disabled} value={head.department} onChange={(e) => onChange({ department: e.target.value })} placeholder="Choose" options={departmentsForSite(v, head.job_id, head.department).map((d) => ({ value: d, label: d }))} />
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
          <CardDescription>How the contractor is paid on every RA bill against this order.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <Field label="GST" htmlFor="h-gst">
            <Select id="h-gst" disabled={disabled} value={head.gst_rate} onChange={(e) => onChange({ gst_rate: Number(e.target.value) })} options={(v?.gst_rates ?? [0, 5, 12, 18, 28]).map((r) => ({ value: r, label: `${r}%` }))} />
          </Field>
          <Field
            label="TDS"
            htmlFor="h-tds"
            hint={statutory != null ? (head.tds_rate < statutory ? `Below the ${statutory}% the law sets - ${basis}. Only the Master can approve it so.` : `${statutory}% by law: ${basis}.`) : undefined}
          >
            <Select id="h-tds" disabled={disabled} value={head.tds_rate} onChange={(e) => onChange({ tds_rate: Number(e.target.value) })} options={tdsOptions} />
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
          <Field label="Liquidated damages (% a week)" htmlFor="h-ld" hint="Of the order value, for each week past the completion date.">
            <NumField id="h-ld" disabled={disabled} value={head.ld_percent_per_week} onValue={(n) => onChange({ ld_percent_per_week: n })} />
          </Field>
          <Field label="Damages capped at (%)" htmlFor="h-ldcap" hint="Of the order value. Nought: no cap below the order value.">
            <NumField id="h-ldcap" disabled={disabled} value={head.ld_cap_percent} onValue={(n) => onChange({ ld_cap_percent: n })} />
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
              <Field label="Valid until" htmlFor="h-bgv" hint="At least to the completion date.">
                <Input id="h-bgv" type="date" disabled={disabled} value={head.bank_guarantee_validity} onChange={(e) => onChange({ bank_guarantee_validity: e.target.value })} />
              </Field>
              <Field label="Guarantee number" htmlFor="h-bgn">
                <Input id="h-bgn" disabled={disabled} value={head.bank_guarantee_number} onChange={(e) => onChange({ bank_guarantee_number: e.target.value })} placeholder="BG/2026/0042" />
              </Field>
              <Field label="Issuing bank" htmlFor="h-bgb">
                <Input id="h-bgb" disabled={disabled} value={head.bank_guarantee_bank} onChange={(e) => onChange({ bank_guarantee_bank: e.target.value })} placeholder="HDFC Bank, Banjara Hills" />
              </Field>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
