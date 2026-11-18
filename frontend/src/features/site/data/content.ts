/** The words and pictures of the company website: Yalavarti Infra Projects, a civil engineering and construction company.
 *
 * Nothing here may claim a number, a project, a certificate, a person or a year the company has not confirmed. Every fact
 * still to come is marked TODO(Uday) - search for it - and stays out of the page (null, or an empty list) until it is
 * filled in. The photographs are neutral construction pictures until Uday sends our own site photos: they carry no
 * captions that name a project.
 */

export interface WorkType { id: string; label: string; hint: string }
export interface Capability { id: string; title: string; tag: string; img: string; intro: string; list: string[] }

export const COMPANY = {
  // TODO(Uday): the exact legal name and its spelling (Pvt. Ltd.?), as on the registration certificate.
  name: 'Yalavarti Infra Projects',
  email: 'info@yalavartiinfra.com',
  // TODO(Uday): confirm the phone and the office. Both are the Yalavarti group office in Kondapur until he says otherwise.
  phone: { show: '040 4005 9348', tel: '+914040059348' },
  address: 'Plot 1-109/21, Near RTA Office, Kondapur, Hyderabad 500084',
  // TODO(Uday): year founded. Shown as "Years building" once set.
  founded: null as number | null,
  // TODO(Uday): staff strength (engineers, supervisors and crew on the rolls). Shown once set.
  staff: null as number | null,
  // The group company that does building services (MEP). Its own site.
  group: { name: 'Yalavarti Projects', url: 'https://www.yalavarti.com/', does: 'building services (MEP)' },
}

export const SITE = {
  hero: {
    title: 'Building homes, townships and the infrastructure around them',
    sub: 'Civil engineering and construction: houses and villas, apartments, gated townships, and the roads, drains and water lines that serve them.',
  },

  // TODO(Uday): our own site photographs. Until then neutral construction pictures, captioned by kind of work only.
  slides: [
    { img: 'site/img/cat3.jpg', t: 'Apartments & townships', l: 'Gated communities and residential blocks' },
    { img: 'site/img/cat2.jpg', t: 'Structure', l: 'Foundations, frames and slabs' },
    { img: 'site/img/gallery/g63.jpg', t: 'Roads & layouts', l: 'Internal roads, drains and open spaces' },
    { img: 'site/img/banner3.jpg', t: 'Commercial & institutional', l: 'Offices, campuses and public buildings' },
  ],

  lead: 'One builder from the plot to the keys: approvals, design, structure, finishing and handover.',

  about: [
    'Yalavarti Infra Projects builds houses, apartments and townships, and the civil infrastructure around them: roads, drainage, water supply and sewerage.',
    'We take a project from the land and its approvals through design and construction to handover.',
    // TODO(Uday): a short paragraph of our own story - when the company began, who leads it (directors), what it has built.
  ],

  // What we build. Each one can open the enquiry with its kind of work already chosen (`type`, from WORK_TYPES).
  // TODO(Uday): confirm each list says what we really take on.
  capabilities: [
    {
      id: 'house', title: 'Houses & villas', tag: 'Your plot, your home', img: 'site/img/cat2.jpg',
      intro: 'Independent houses, villas and row houses, built on your plot to your drawings or to ours.',
      list: ['Architectural and structural drawings', 'Building permission and approvals', 'Foundation, RCC frame and masonry', 'Plastering, flooring, painting and finishes', 'Sumps, overhead tanks and compound walls'],
    },
    {
      id: 'apartment', title: 'Apartments', tag: 'Residential blocks', img: 'site/img/cat3.jpg',
      intro: 'Apartment blocks and residential towers, from the foundation to the finished flat.',
      list: ['RCC framed structures', 'Stilt and basement parking', 'Staircases, lift wells and common areas', 'Finishes to the agreed specification', 'External works and landscaping'],
    },
    {
      id: 'township', title: 'Gated townships & layouts', tag: 'Plots to communities', img: 'site/img/gallery/g63.jpg',
      intro: 'Plotted layouts and gated communities, with everything a township needs before the first family moves in.',
      list: ['Site clearing, grading and levelling', 'Internal roads, footpaths and kerbs', 'Storm water drains and culverts', 'Compound walls, gates and security rooms', 'Clubhouses, parks and open spaces'],
    },
    {
      id: 'road', title: 'Roads & drainage', tag: 'Roads, drains, culverts', img: 'site/img/gallery/g63.jpg',
      intro: 'Roads and the drains beside them, for layouts, campuses and public works.',
      list: ['CC and bituminous roads', 'Granular sub-base and WBM', 'Storm water and roadside drains', 'Culverts and cross drainage', 'Kerbs, footpaths and medians'],
    },
    {
      id: 'water', title: 'Water supply & sewerage', tag: 'Water in, water out', img: 'site/img/gallery/g112.jpg',
      intro: 'The civil works that bring water to a site and carry it away.',
      list: ['Water supply mains and distribution lines', 'Sumps and overhead tanks', 'Sewer lines and manholes', 'Civil works for sewage treatment plants', 'Rainwater harvesting and recharge pits'],
    },
    {
      id: 'commercial', title: 'Commercial & industrial buildings', tag: 'Places of work', img: 'site/img/banner3.jpg',
      intro: 'Offices, shops, schools, warehouses and industrial sheds.',
      list: ['Office and retail buildings', 'Schools and institutional buildings', 'Warehouses and industrial sheds', 'Foundations for pre-engineered buildings', 'Hard standings and yards'],
    },
    {
      id: 'civil', title: 'Civil structures', tag: 'Walls, tanks, foundations', img: 'site/img/cat2.jpg',
      intro: 'The structures a site needs around its buildings.',
      list: ['Retaining walls', 'Water tanks and reservoirs', 'Compound walls', 'Foundations for plant and equipment', 'Culverts'],
    },
  ] as Capability[],

  // How a job runs, in the order it happens. Describes the stages, not promises about them.
  // TODO(Uday): confirm this is how we run a job, and say if a stage is one the client usually does himself.
  steps: [
    { t: 'Land & approvals', d: 'We check the plot, its title papers and the rules that apply, and take the plans through building permission.' },
    { t: 'Design', d: 'Architectural and structural drawings, the specification and a costed bill of quantities you can check line by line.' },
    { t: 'Foundation', d: 'Soil checked, the site set out, excavation and footings cast to the drawings.' },
    { t: 'Structure', d: 'Columns, beams and slabs, floor by floor, to the structural drawings.' },
    { t: 'Finishing', d: 'Masonry, plastering, flooring, doors, windows and paint, to the specification you agreed.' },
    { t: 'Handover', d: 'A walk-through with you, any snags put right, and the keys.' },
  ],

  // Where we are building, as Hemanth listed them (18 Nov 2026). Names and places only: no status, size or year until confirmed.
  sites: [
    { group: 'APTIDCO sites', where: 'Andhra Pradesh', names: ['Nuzividu', 'Tiruvuru', 'Ongole', 'Addanki'] },
    { group: 'High rise', where: 'Andhra Pradesh', names: ['Visakhapatnam'] },
    { group: 'Hyderabad', where: 'Telangana', names: ['Vision Anmaya', 'Vision Arusha', 'Steel Alpha'] },
  ],

  // TODO(Uday): our own milestones, in this shape: { y: '2012', t: 'First township', d: 'One line.', img: 'site/img/...' }.
  // The section is left off the page while this is empty.
  timeline: [] as { y: string; t: string; d: string; img: string }[],

  // The enquiry form.
  plan: {
    types: [
      { id: 'house', label: 'House or villa', hint: 'On your own plot' },
      { id: 'apartment', label: 'Apartment', hint: 'Residential block or tower' },
      { id: 'township', label: 'Township or layout', hint: 'Gated community, plotted layout' },
      { id: 'road', label: 'Road or drainage', hint: 'Roads, drains, water and sewer lines' },
      { id: 'commercial', label: 'Commercial or industrial', hint: 'Offices, schools, warehouses, sheds' },
      { id: 'other', label: 'Something else', hint: 'Tell us in a line' },
    ] as WorkType[],
    units: ['sq ft', 'sq yd', 'acres'],
    starts: ['Within 3 months', '3 to 6 months', '6 to 12 months', 'Not decided yet'],
  },
}

/** The kind of work an enquiry asks about, for a capability: "Water supply & sewerage" asks as a road or drainage job. */
export const typeFor = (capability: string) => (SITE.plan.types.some((t) => t.id === capability) ? capability : capability === 'water' ? 'road' : 'other')
