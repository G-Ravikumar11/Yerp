/** The words and pictures of the company website: Yalavarti Infra Projects, a civil engineering and construction company.
 *
 * "Look B": the site drawn as an engineering drawing sheet (docs: the Look B brief, 25 Nov 2026). Everything here is edited
 * in Settings -> Website and published from there; this is the copy the site was built with, and what a company's website
 * starts from (backend/app/constants/website_content.json is kept equal to it by a test).
 *
 * Nothing here may claim a number, a client, a certificate, a person or a year the company has not confirmed. A fact still to
 * come is left empty (an empty string, an empty list or null) and the page leaves it out - never "sample", "TBC" or "on
 * request". TODO(Uday) marks each one.
 */

export interface WorkType { id: string; label: string; hint: string }
/** A kind of work. `line`: shown as a line under the tiles rather than as a tile of its own (civil structures). */
export interface Capability { id: string; title: string; tag: string; img: string; intro: string; list: string[]; line: boolean }
/** A section's heading, drawn as a drawing title: its number and one-word `code` in the circle, the heading, the `scale`
 *  line under it, and the `lede` beside it (left out when empty). `eyebrow` is the menu's name for it. */
export interface Heading { eyebrow: string; code: string; title: string; scale: string; lede: string }
/** A row of the projects register: a site we are building. The live projects ticked "show on website" join it. */
export interface RegisterRow { site: string; client: string; town: string; state: string; work: string; status: string }
/** A project's drawing sheet: a photograph from site, with its title block. */
export interface Sheet { img: string; site: string; ref: string; block: string; stage: string; shown: string }

/** The sections of the page in the order they are shown. Each can be hidden from Settings -> Website; "Our story" is left
 *  off while it has no milestones. */
export type PageSection = 'hero' | 'about' | 'projects' | 'build' | 'process' | 'quality' | 'quote' | 'careers' | 'story'
export const PAGE_SECTIONS: { id: PageSection; label: string }[] = [
  { id: 'hero', label: 'Opening (with the figures)' }, { id: 'about', label: 'About' }, { id: 'projects', label: 'Projects' },
  { id: 'build', label: 'What we build' }, { id: 'process', label: 'How we build' }, { id: 'quality', label: 'Quality, safety & credentials' },
  { id: 'quote', label: 'Start a project' }, { id: 'careers', label: 'Careers' }, { id: 'story', label: 'Our story' },
]

export const COMPANY = {
  // TODO(Uday): the exact legal name and its spelling (Pvt. Ltd.?), as on the registration certificate.
  name: 'Yalavarti Infra Projects',
  // The top strip: what we do and where.
  trade: 'Civil engineering & construction',
  regions: 'Andhra Pradesh · Telangana',
  email: 'info@yalavartiinfra.com',
  // TODO(Uday): confirm the phone and the office. Both are the Yalavarti group office in Kondapur until he says otherwise.
  phone: { show: '040 4005 9348', tel: '+914040059348' },
  // TODO(Uday): the WhatsApp number, with the country code (+91...). The WhatsApp button shows once it is set.
  whatsapp: '',
  address: 'Plot 1-109/21, Near RTA Office, Kondapur, Hyderabad 500084',
  // TODO(Uday): year founded. Shown as "Years building" once set.
  founded: null as number | null,
  // TODO(Uday): staff strength (engineers, supervisors and crew on the rolls). Shown once set.
  staff: null as number | null,
  // The group company that does building services (MEP). Its own site.
  group: { name: 'Yalavarti Projects', url: 'https://www.yalavarti.com/', does: 'building services (electrical, fire and plumbing)' },
  // The company's pages elsewhere, shown in the footer once set.
  social: { linkedin: '', facebook: '', instagram: '', youtube: '' },
}

export const SITE = {
  hero: {
    kicker: 'Homes · Townships · Roads · Water',
    title: 'Built to the drawing,',
    accent: 'from the plot to the keys.',
    sub: 'Civil engineering and construction: houses and villas, apartments, gated townships, and the roads, drains and water lines that serve them.',
    // The photograph, framed with dimension lines: `label` across the top, `side` up the left, and its callout.
    photo: {
      img: 'site/img/sites/giddaluru-c2.jpg', label: 'APTIDCO · Giddaluru', side: 'Block C-2',
      calloutTitle: 'On site now', callout: 'C-2 block: staircase and kicker aluminium formwork being fixed.',
    },
    // The last box of the figures' title block.
    noteTitle: 'One contractor',
    note: 'Approvals, design, structure, finishing and handover, with our own engineers on site.',
  },

  // "Building for": the clients we build for. Left off while empty.
  // TODO(Uday): the client names to show (APTIDCO, government departments, developers) - only those confirmed.
  clients: [] as string[],

  // General notes: who we are, one note each.
  about: [
    'Yalavarti Infra Projects builds houses, apartments and townships, and the civil infrastructure around them: roads, drainage, water supply and sewerage.',
    'We take a project from the land and its approvals through design and construction to handover.',
    'Work is inspected against the drawings and the specification before it is covered up or poured.',
    // TODO(Uday): our own story - when the company began, who leads it, what it has built.
  ],

  // What we build: detail tiles, numbered 3.1, 3.2... The first is drawn twice as wide. Each can open the enquiry with its
  // kind of work already chosen (`type`, from plan.types).
  // TODO(Uday): confirm each list says what we really take on, and send our own photographs for the tiles.
  capabilities: [
    {
      id: 'township', title: 'Gated townships & layouts', tag: 'Plots to communities', img: 'site/img/cat3.jpg', line: false,
      intro: 'Plotted layouts and gated communities, with everything a township needs before the first family moves in.',
      list: ['Site clearing, grading and levelling', 'Internal roads, footpaths and kerbs', 'Storm water drains and culverts', 'Compound walls, gates and security rooms', 'Clubhouses, parks and open spaces'],
    },
    {
      id: 'apartment', title: 'Apartments', tag: 'Residential blocks', img: 'site/img/sites/nuzividu-a05.jpg', line: false,
      intro: 'Apartment blocks and residential towers, from the foundation to the finished flat.',
      list: ['RCC framed structures', 'Stilt and basement parking', 'Staircases, lift wells and common areas'],
    },
    {
      id: 'house', title: 'Houses & villas', tag: 'Your plot, your home', img: 'site/img/cat2.jpg', line: false,
      intro: 'Independent houses, villas and row houses, built on your plot to your drawings or to ours.',
      list: ['Drawings and building permission', 'Foundation, RCC frame and masonry', 'Finishes, sumps and compound walls'],
    },
    {
      id: 'road', title: 'Roads & drainage', tag: 'Roads, drains, culverts', img: 'site/img/gallery/g63.jpg', line: false,
      intro: 'Roads and the drains beside them, for layouts, campuses and public works.',
      list: ['CC and bituminous roads', 'Storm water and roadside drains', 'Culverts and cross drainage'],
    },
    {
      id: 'water', title: 'Water supply & sewerage', tag: 'Water in, water out', img: 'site/img/gallery/g112.jpg', line: false,
      intro: 'The civil works that bring water to a site and carry it away.',
      list: ['Mains and distribution lines', 'Sumps and overhead tanks', 'Sewer lines, manholes, STP civil works'],
    },
    {
      id: 'commercial', title: 'Commercial & industrial', tag: 'Places of work', img: 'site/img/banner3.jpg', line: false,
      intro: 'Offices, shops, schools, warehouses and industrial sheds.',
      list: ['Office, retail and school buildings', 'Warehouses and industrial sheds', 'Hard standings and yards'],
    },
    {
      id: 'civil', title: 'Civil structures', tag: 'Walls, tanks, foundations', img: '', line: true,
      intro: 'including retaining walls, water tanks and reservoirs, compound walls, plant foundations and culverts.',
      list: [],
    },
  ] as Capability[],

  // How a job runs, drawn as a chainage line of stages.
  // TODO(Uday): confirm this is how we run a job, and say if a stage is one the client usually does himself.
  steps: [
    { t: 'Land & approvals', d: 'We check the plot, its title papers and the rules that apply, and take the plans through building permission.' },
    { t: 'Design', d: 'Architectural and structural drawings, the specification and a costed bill of quantities you can check line by line.' },
    { t: 'Foundation', d: 'Soil checked, the site set out, excavation and footings cast to the drawings.' },
    { t: 'Structure', d: 'Columns, beams and slabs, floor by floor, to the structural drawings.' },
    { t: 'Finishing', d: 'Masonry, plastering, flooring, doors, windows and paint, to the specification you agreed.' },
    { t: 'Handover', d: 'A walk-through with you, any snags put right, and the keys.' },
  ],

  // The projects register: every site in hand, as Hemanth listed them (18 Nov 2026), all running (19 Nov 2026). Names,
  // towns and states only, with the client and work where we have them; anything not confirmed is left empty. The live
  // projects ticked "show on website" are added to it, without repeating a site already here.
  sites: [
    { site: 'Nuzividu', client: 'APTIDCO housing', town: 'Nuzividu', state: 'AP', work: 'Housing blocks', status: 'Ongoing' },
    { site: 'Tiruvuru', client: 'APTIDCO housing', town: 'Tiruvuru', state: 'AP', work: 'Housing blocks', status: 'Ongoing' },
    { site: 'Ongole', client: 'APTIDCO housing', town: 'Ongole', state: 'AP', work: 'Housing blocks', status: 'Ongoing' },
    { site: 'Addanki', client: 'APTIDCO housing', town: 'Addanki', state: 'AP', work: 'Housing blocks', status: 'Ongoing' },
    { site: 'Giddaluru', client: 'APTIDCO housing', town: 'Giddaluru', state: 'AP', work: 'Housing blocks', status: 'Ongoing' },
    { site: 'Visakhapatnam', client: '', town: 'Visakhapatnam', state: 'AP', work: 'High-rise structure', status: 'Ongoing' },
    { site: 'Vision Anmaya', client: '', town: 'Hyderabad', state: 'TS', work: '', status: 'Ongoing' },
    { site: 'Vision Arusha', client: '', town: 'Hyderabad', state: 'TS', work: '', status: 'Ongoing' },
    { site: 'Steel Alpha', client: '', town: 'Hyderabad', state: 'TS', work: '', status: 'Ongoing' },
  ] as RegisterRow[],

  // Drawing sheets: photographs from our own sites, in the site team's words. The first is drawn large.
  sitePhotos: [
    { img: 'site/img/sites/giddaluru-c2.jpg', site: 'APTIDCO housing, Giddaluru', ref: 'S-05', block: 'C-2', stage: 'Structure', shown: 'Staircase & kicker aluminium formwork' },
    { img: 'site/img/sites/nuzividu-a05.jpg', site: 'APTIDCO housing, Nuzividu', ref: 'S-01', block: 'A-05', stage: 'Structure', shown: 'Rebar fixing & Mivan formwork' },
  ] as Sheet[],

  // TODO(Uday): our own milestones, in this shape: { y: '2012', t: 'First township', d: 'One line.', img: '' }.
  // "Our story" is left off the page while this is empty.
  timeline: [] as { y: string; t: string; d: string; img: string }[],

  // Each section's drawing title.
  headings: {
    about: { eyebrow: 'About', code: 'About', title: 'Civil works, start to finish', scale: 'General notes · read with the projects register', lede: '' },
    projects: { eyebrow: 'Projects', code: 'Projects', title: 'Projects register', scale: 'Sites in hand · Andhra Pradesh & Telangana', lede: 'Every site we are building now, with photographs from site.' },
    build: { eyebrow: 'What we build', code: 'Scope', title: 'What we build', scale: 'Kinds of work · details 3.1 to 3.7', lede: 'From a single house on your plot to a gated township with its roads, drains and water lines.' },
    process: { eyebrow: 'How we build', code: 'Method', title: 'From the land to the keys', scale: 'Six stages, in the order they happen', lede: '' },
    quality: { eyebrow: 'Quality', code: 'QA / HSE', title: 'Checked work, safe sites', scale: 'Inspection, safety and the papers a tender asks for', lede: '' },
    quote: { eyebrow: 'Contact', code: 'Enquiry', title: 'Start a project', scale: 'One form · it reaches our team directly', lede: '' },
    careers: { eyebrow: 'Careers', code: 'People', title: 'Build homes and townships with us', scale: 'Openings · posted from Recruitment', lede: 'Engineers, supervisors and crew for our sites. Apply online. It takes a few minutes.' },
    story: { eyebrow: 'Our story', code: 'Story', title: 'Our story', scale: 'Milestones, in the order they came', lede: '' },
  } as Record<Exclude<PageSection, 'hero'>, Heading>,

  // The order of the page, and which sections are shown.
  layout: PAGE_SECTIONS.map((p) => ({ id: p.id, shown: true })) as { id: PageSection; shown: boolean }[],

  // The quality and safety policies, one box each. `code`: the small red label (HSE, QA, QC).
  // TODO(Uday): have the quality and safety heads check this says what really happens on our sites, and send the HSE
  // plan and quality policy PDFs to link here (as { label, href: 'site/docs/....pdf' }).
  safety: [
    { code: 'HSE', title: 'Health, safety & environment', text: 'Our sites work to a written safety plan, and every incident and near miss is recorded and investigated.' },
    { code: 'QA', title: 'Quality', text: 'Work is inspected against the drawings and the specification before it is covered up or poured. Anything that does not pass is recorded and put right.' },
    { code: 'QC', title: 'Materials', text: 'Cement, steel, aggregates and concrete are checked when they arrive and tested as the work goes on. The records are kept with the project.' },
  ] as { code: string; title: string; text: string; link?: { label: string; href: string } }[],

  // Credentials, as a register. An item is shown only once it has a real value (credentialShown): nothing may claim what the
  // company cannot produce a copy of, and nothing says "on request".
  // TODO(Uday): the registration class and authority, ISO certificate numbers, GSTIN and the RERA number of each project.
  credentials: [
    { label: 'Contractor registration', value: '' },
    { label: 'ISO certification', value: '' },
    { label: 'GSTIN', value: '' },
    { label: 'RERA registration', value: '' },
    { label: 'Plant & machinery', value: '' },
  ] as { label: string; value: string }[],

  // What the owner decides about the live figures. The safe man-hours are shown only once past `safeHoursFrom`; a project's
  // "% done" (from its programme) only when `showProgress` is ticked.
  options: { safeHoursFrom: 100000, showProgress: false },

  // Start a project: what happens after the enquiry, beside the form.
  enquiry: {
    next: [
      { t: 'You send the enquiry', d: 'It reaches our tender team directly, with the type of work and site you chose.' },
      { t: 'We call you', d: 'To understand the plot, the drawings you have and the timeline.' },
      { t: 'Site visit & estimate', d: 'A costed bill of quantities you can check line by line.' },
    ],
    note: 'Your enquiry goes straight to our team.',
  },

  // The enquiry form's choices.
  plan: {
    types: [
      { id: 'house', label: 'House or villa', hint: 'On your own plot' },
      { id: 'apartment', label: 'Apartment', hint: 'Residential block or tower' },
      { id: 'township', label: 'Township or layout', hint: 'Gated community, plotted layout' },
      { id: 'road', label: 'Road or drainage', hint: 'Roads, drains, water and sewer lines' },
      { id: 'commercial', label: 'Commercial', hint: 'Offices, schools, warehouses, sheds' },
      { id: 'other', label: 'Something else', hint: 'Tell us in a line' },
    ] as WorkType[],
    units: ['sq ft', 'sq yd', 'acres'],
    starts: ['Within 3 months', '3 to 6 months', '6 to 12 months', 'Not decided yet'],
  },

  // The foot of the page: the drawing's title block. The "Staff login" link is always there and is not set here.
  footer: { tagline: 'Civil engineering & construction', showGroupLink: true, sheet: 'YIP-WEB · 1 of 1' },

  // What a search engine and a shared link show. Empty: the built-in title and description.
  seo: { title: '', description: '', image: '' },
}

/** Whether a credential has a real value to show: not empty, and not a placeholder such as "on request" or "to follow". */
export const credentialShown = (c: { label: string; value: string }) =>
  !!c.label.trim() && !!c.value.trim() && !/\b(on request|to follow|tbc|tbd|awaited|pending|sample|owner to fill)\b/i.test(c.value)

/** The kind of work an enquiry asks about, for a capability: "Water supply & sewerage" asks as a road or drainage job. */
export const typeFor = (capability: string, types: WorkType[] = SITE.plan.types) => (types.some((t) => t.id === capability) ? capability : capability === 'water' ? 'road' : 'other')
