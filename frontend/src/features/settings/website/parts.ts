import type { Spec } from './fields'

/** One block of a part of the Website tab: a section of the content (or a field inside it) and how it is edited. */
export interface Block { key: string; path?: string[]; title?: string; spec: Spec }
/** A page of the Website tab. Most are blocks of fields; a few have screens of their own. */
export interface Part { id: string; label: string; hint?: string; blocks?: Block[]; custom?: 'overview' | 'layout' | 'projects' | 'pictures' | 'history' | 'careers'; also?: string[] }

const text = (label: string, hint?: string): Spec => ({ kind: 'text', label, hint })
const long = (label: string, hint?: string): Spec => ({ kind: 'text', label, hint, long: true })
const heading = (key: string): Block => ({
  key: 'headings', path: [key], title: 'Drawing title',
  spec: {
    kind: 'object', fields: {
      title: text('Heading'), code: text('Code in the circle', 'One short word, e.g. SCOPE'), scale: text('Scale line', 'The small line under the heading'),
      lede: long('Line beside the heading', 'Leave empty for none.'), eyebrow: text('Name in the menu'),
    },
  },
})
const slug = (s: string, n: number) => (s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'item') + '-' + n

export const PARTS: Part[] = [
  { id: 'overview', label: 'Overview', hint: 'What still needs doing on the website, and this week’s enquiries.', custom: 'overview' },
  { id: 'layout', label: 'Page layout', hint: 'Which sections the page shows, and in what order. The menu follows.', custom: 'layout' },
  {
    id: 'hero', label: 'Opening', blocks: [
      {
        key: 'hero', spec: {
          kind: 'object', fields: {
            kicker: text('Small red line above', 'e.g. Homes · Townships · Roads · Water'), title: long('Headline'),
            accent: text('Headline, in blue', 'The end of the headline, drawn in blue. Leave empty for none.'), sub: long('Line under the headline'),
            photo: {
              kind: 'object', fields: {
                img: { kind: 'image', label: 'Site photograph (at least 1600 px wide)', place: 'hero' },
                label: text('Label along the top', 'e.g. APTIDCO · Giddaluru'), side: text('Label up the side', 'e.g. Block C-2'),
                calloutTitle: text('Callout heading', 'e.g. On site now'), callout: long('Callout', 'What the photograph shows'),
              },
            },
            noteTitle: text('Last box of the figures: heading'), note: long('Last box of the figures: text'),
          },
        },
      },
      { key: 'clients', title: 'Building for', spec: { kind: 'strings', label: 'Clients', item: 'Client', hint: 'Only names you can confirm. Left off the page while empty.' } },
    ],
  },
  {
    id: 'about', label: 'About', blocks: [
      heading('about'),
      { key: 'about', spec: { kind: 'strings', label: 'General notes', item: 'Note', long: true } },
      { key: 'company', path: ['group'], title: 'The group company (Ref. box)', spec: { kind: 'object', fields: { name: text('Name'), does: text('What it does', 'Shown as "For …, see our group company"'), url: text('Its website', 'https://…') } } },
    ],
  },
  {
    id: 'projects', label: 'Projects', custom: 'projects', also: ['projects'], blocks: [
      heading('projects'),
      {
        key: 'sites', spec: {
          kind: 'list', label: 'Projects register', item: 'Site', title: (v) => String(v.site ?? ''),
          of: { site: text('Site'), client: text('Client or programme', 'Leave empty if not to be named'), town: text('Town'), state: text('State', 'AP, TS…'), work: text('Work'), status: text('Status', 'Ongoing or Completed') },
          blank: () => ({ site: '', client: '', town: '', state: '', work: '', status: 'Ongoing' }),
        },
      },
      {
        key: 'sitePhotos', spec: {
          kind: 'list', label: 'Drawing sheets (photographs from site)', item: 'Sheet', title: (v) => String(v.site ?? ''),
          of: { img: { kind: 'image', label: 'Photograph (at least 1000 px wide)', place: 'sheet' }, site: text('Title', 'e.g. APTIDCO housing, Giddaluru'), ref: text('Sheet ref', 'e.g. S-05'), block: text('Block'), stage: text('Stage'), shown: text('What it shows') },
          blank: () => ({ img: '', site: '', ref: '', block: '', stage: '', shown: '' }),
        },
      },
      { key: 'options', path: ['showProgress'], title: 'Progress', spec: { kind: 'bool', label: 'Show each live project’s “% done” in the register (from its programme)' } },
    ],
  },
  {
    id: 'build', label: 'What we build', blocks: [
      heading('build'),
      {
        key: 'capabilities', spec: {
          kind: 'list', label: 'Kinds of work (the first is drawn twice as wide)', item: 'Kind of work', title: (v) => String(v.title ?? ''),
          of: { title: text('Name'), tag: text('Short tag'), intro: long('Introduction'), img: { kind: 'image', label: 'Photograph (at least 1000 px wide)', place: 'section' }, list: { kind: 'strings', label: 'What it covers', item: 'Line' }, line: { kind: 'bool', label: 'Show as a line under the tiles, not as a tile' } },
          blank: (n) => ({ id: slug('work', n + 1), title: '', tag: '', intro: '', img: '', list: [], line: false }),
        },
      },
    ],
  },
  {
    id: 'process', label: 'How we build', blocks: [
      heading('process'),
      { key: 'steps', spec: { kind: 'list', label: 'Stages (the last is marked in red)', item: 'Stage', title: (v) => String(v.t ?? ''), of: { t: text('Stage'), d: long('What happens') }, blank: () => ({ t: '', d: '' }) } },
    ],
  },
  {
    id: 'quality', label: 'Quality & credentials', blocks: [
      heading('quality'),
      { key: 'safety', spec: { kind: 'list', label: 'Policies', item: 'Policy', title: (v) => String(v.title ?? ''), of: { code: text('Red label', 'HSE, QA, QC'), title: text('Title'), text: long('What we do') }, blank: () => ({ code: '', title: '', text: '' }) } },
      { key: 'credentials', spec: { kind: 'list', label: 'Credentials', item: 'Credential', title: (v) => String(v.label ?? ''), of: { label: text('Name', 'e.g. Contractor registration, ISO 9001, GSTIN, RERA'), value: long('Value', 'The class, number or certificate - only what we can show a copy of. Left empty, it is not shown.') }, blank: () => ({ label: '', value: '' }) } },
      { key: 'options', path: ['safeHoursFrom'], title: 'Safe man-hours', spec: { kind: 'number', label: 'Show the safe man-hours once they pass', hint: 'Counted live from attendance and incidents. Suggested: 1,00,000.' } },
    ],
  },
  {
    id: 'quote', label: 'Start a project', blocks: [
      heading('quote'),
      { key: 'enquiry', spec: { kind: 'object', fields: { next: { kind: 'list', label: 'What happens next', item: 'Step', title: (v) => String(v.t ?? ''), of: { t: text('Step'), d: long('What happens') }, blank: () => ({ t: '', d: '' }) }, note: text('Line beside the Send button') } } },
    ],
  },
  { id: 'careers', label: 'Careers', hint: 'Openings go on the website as soon as they are posted, and come off when closed. Applications arrive in Recruitment.', custom: 'careers', blocks: [heading('careers')] },
  {
    id: 'story', label: 'Our story', hint: 'Left off the page until it has a milestone.', blocks: [
      heading('story'),
      { key: 'timeline', spec: { kind: 'list', label: 'Milestones', item: 'Milestone', title: (v) => [v.y, v.t].filter(Boolean).join(' - '), of: { y: text('Year'), t: text('Title'), d: long('One line') }, blank: () => ({ y: '', t: '', d: '', img: '' }) } },
    ],
  },
  {
    id: 'contact', label: 'Contact details', blocks: [
      {
        key: 'company', title: 'The company', spec: {
          kind: 'object', fields: {
            name: text('Company name'), trade: text('Top strip: what we do'), regions: text('Top strip: where'), email: text('Email'),
            address: long('Office address', 'Also where the map points.'),
            phone: { kind: 'object', fields: { show: text('Phone, as shown'), tel: text('Phone, as dialled', 'With the country code, e.g. +914040059348') } },
            whatsapp: text('WhatsApp number', 'With the country code, e.g. +91 98480 12345. The WhatsApp button shows on phones once it is set.'),
            founded: { kind: 'number', label: 'Year founded', hint: 'Shown as "Years building". Leave empty to leave it out.' },
            staff: { kind: 'number', label: 'Engineers & crew', hint: 'Leave empty to leave it out.' },
            social: { kind: 'object', fields: { linkedin: text('LinkedIn page', 'https://…'), facebook: text('Facebook page', 'https://…'), instagram: text('Instagram', 'https://…'), youtube: text('YouTube', 'https://…') } },
          },
        },
      },
    ],
  },
  { id: 'footer', label: 'Footer', hint: 'The "Staff login" link is always there.', blocks: [{ key: 'footer', spec: { kind: 'object', fields: { tagline: text('Line under the company name'), showGroupLink: { kind: 'bool', label: 'Link to the group company' }, sheet: text('Sheet number', 'e.g. YIP-WEB · 1 of 1') } } }] },
  {
    id: 'seo', label: 'Search & sharing', hint: 'What Google and a shared link show. Left empty, the built-in title and description are used.', blocks: [
      { key: 'seo', spec: { kind: 'object', fields: { title: text('Title', 'About 60 characters'), description: long('Description', 'About 155 characters'), image: { kind: 'image', label: 'Picture for a shared link', place: 'hero' } } } },
    ],
  },
  { id: 'pictures', label: 'Pictures', hint: 'Upload a photo, crop it, and choose where it goes.', custom: 'pictures' },
  { id: 'history', label: 'History', hint: 'Every time the website was published. Put an earlier version back.', custom: 'history' },
]

/** The sections a part edits. */
export const keysOf = (p: Part) => [...new Set([...(p.blocks ?? []).map((b) => b.key), ...(p.also ?? []), ...(p.custom === 'layout' ? ['layout'] : [])])]

export const getAt = (v: unknown, path: string[] = []): unknown => path.reduce<unknown>((o, k) => (o && typeof o === 'object' ? (o as Record<string, unknown>)[k] : undefined), v)
export function setAt(v: unknown, path: string[], next: unknown): unknown {
  if (!path.length) return next
  const [k, ...rest] = path
  const obj = (v && typeof v === 'object' ? v : {}) as Record<string, unknown>
  return { ...obj, [k]: setAt(obj[k], rest, next) }
}
