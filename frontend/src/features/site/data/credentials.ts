/** Credentials and the quality and safety policies, for the company website.
 *
 * TO FILL IN: each "On request" below is a placeholder. Replace it with the real figure (registration class and number,
 * certificate numbers, turnover band, machinery list) once confirmed - nothing here should claim what the company cannot
 * show a copy of. Until then the site says only that the document is available on request.
 */
export const CREDENTIALS: { label: string; value: string }[] = [
  { label: 'Contractor registration', value: 'Class and registering authority on request' },
  { label: 'ISO certification', value: 'Certificates on request' },
  { label: 'GST & PAN', value: 'Copies on request' },
  { label: 'Safety record', value: 'Safe man-hours counted live from site attendance (see Quality & Safety)' },
  { label: 'Plant & machinery', value: 'Owned equipment list on request' },
  { label: 'Bank solvency', value: 'Solvency certificate on request' },
]

// TO CONFIRM: placeholder wording, written from what the ERP records (inspections, non-conformances, incidents). Have the
// QA/QC and safety heads check it says what really happens on site before it goes live.
export const QUALITY: { title: string; text: string; link?: { label: string; href: string } }[] = [
  { title: 'Health, safety & environment', text: 'Our sites work to a written HSE plan, and every incident and near miss is recorded and investigated.', link: { label: 'Our HSE plan (PDF)', href: 'docs/yalavarti-hse-plan.pdf' } },
  // TO FILL IN: link the quality policy PDF here once it is published, as the HSE plan above.
  { title: 'Quality', text: 'Work is inspected against the drawings and the specification before it is covered up or handed over, and anything that does not pass is recorded and closed out before billing.' },
  { title: 'Testing & commissioning', text: 'Systems are tested and commissioned before handover, and the test records are handed over with the as-built drawings.' },
]
