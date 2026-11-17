/** Credentials and the quality and safety policies, for the company website.
 *
 * TODO(Uday): each "on request" below is a placeholder. Replace it with the real figure (registration class and number,
 * certificate numbers, RERA numbers, plant list) once there is a copy to show - nothing here should claim what the company
 * cannot produce. Until then the site says only that the document is available on request.
 */
export const CREDENTIALS: { label: string; value: string }[] = [
  // TODO(Uday): class and registering authority, e.g. "Class I civil contractor, Government of Telangana".
  { label: 'Contractor registration', value: 'Class and registering authority on request' },
  // TODO(Uday): standard and certificate number, if certified.
  { label: 'ISO certification', value: 'Certificates on request' },
  // TODO(Uday): GSTIN.
  { label: 'GST & PAN', value: 'Copies on request' },
  // TODO(Uday): the RERA registration number of each township or apartment project we sell or build.
  { label: 'RERA registration', value: 'Project registration numbers on request' },
  { label: 'Safety record', value: 'Safe man-hours counted live from our site records (see Quality & Safety)' },
  // TODO(Uday): plant owned - excavators, mixers, batching plant, shuttering, vehicles.
  { label: 'Plant & machinery', value: 'Owned equipment list on request' },
]

// TODO(Uday): have the quality and safety heads check this says what really happens on our sites before it goes live,
// and send the HSE plan and quality policy PDFs to link here (as { label, href: 'docs/....pdf' } under public/site).
export const QUALITY: { title: string; text: string; link?: { label: string; href: string } }[] = [
  { title: 'Health, safety & environment', text: 'Our sites work to a written safety plan, and every incident and near miss is recorded and investigated.' },
  { title: 'Quality', text: 'Work is inspected against the drawings and the specification before it is covered up or poured, and anything that does not pass is recorded and put right.' },
  { title: 'Materials', text: 'Cement, steel, aggregates and concrete are checked when they arrive and tested as the work goes on, and the records are kept with the project.' },
]
