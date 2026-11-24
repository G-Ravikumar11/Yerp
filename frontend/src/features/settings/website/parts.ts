import type { Spec } from './fields'

/** One block of a part of the Website tab: a section of the content (or a field inside it) and how it is edited. */
export interface Block { key: string; path?: string[]; title?: string; spec: Spec }
/** A page of the Website tab. Most are blocks of fields; a few have screens of their own. */
export interface Part { id: string; label: string; hint?: string; blocks?: Block[]; custom?: 'layout' | 'projects' | 'pictures' | 'history' | 'careers'; also?: string[] }

const text = (label: string, hint?: string): Spec => ({ kind: 'text', label, hint })
const long = (label: string, hint?: string): Spec => ({ kind: 'text', label, hint, long: true })
const heading = (key: string, extra: Record<string, Spec> = {}): Block => ({
  key: 'headings', path: [key], title: 'Heading',
  spec: { kind: 'object', fields: { eyebrow: text('Small line above'), title: text('Heading'), lede: long('Line beside the heading', 'Leave empty for none.'), ...extra } },
})
const slug = (s: string, n: number) => (s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'item') + '-' + n

export const PARTS: Part[] = [
  { id: 'layout', label: 'Page layout', hint: 'Which sections the page shows, and in what order. The menu follows.', custom: 'layout' },
  {
    id: 'hero', label: 'Opening banner', blocks: [
      { key: 'hero', spec: { kind: 'object', fields: { title: long('Headline'), sub: long('Line under the headline') } } },
      {
        key: 'slides', spec: {
          kind: 'list', label: 'Banner photographs', item: 'Photograph', title: (v) => String(v.t ?? ''),
          of: { img: { kind: 'image', label: 'Photograph', place: 'hero' }, t: text('Caption'), l: text('Line under the caption') },
          blank: () => ({ img: '', t: '', l: '' }),
        },
      },
      { key: 'lead', spec: long('Line beside the figures ("At a glance")') },
    ],
  },
  {
    id: 'about', label: 'About', blocks: [
      heading('about'),
      { key: 'about', spec: { kind: 'strings', label: 'Paragraphs', item: 'Paragraph', long: true } },
      { key: 'company', path: ['group'], title: 'The group company', spec: { kind: 'object', fields: { name: text('Name'), does: text('What it does', 'Shown as "For …, see our group company"'), url: text('Its website', 'https://…') } } },
    ],
  },
  {
    id: 'build', label: 'What we build', blocks: [
      heading('build'),
      {
        key: 'capabilities', spec: {
          kind: 'list', label: 'Kinds of work', item: 'Kind of work', title: (v) => String(v.title ?? ''),
          of: { title: text('Name'), tag: text('Short tag'), intro: long('Introduction'), img: { kind: 'image', label: 'Photograph', place: 'section' }, list: { kind: 'strings', label: 'What it covers', item: 'Line' } },
          blank: (n) => ({ id: slug('work', n + 1), title: '', tag: '', intro: '', img: '', list: [] }),
        },
      },
    ],
  },
  {
    id: 'process', label: 'How we build', blocks: [
      heading('process'),
      { key: 'steps', spec: { kind: 'list', label: 'Stages', item: 'Stage', title: (v) => String(v.t ?? ''), of: { t: text('Stage'), d: long('What happens') }, blank: () => ({ t: '', d: '' }) } },
    ],
  },
  {
    id: 'projects', label: 'Projects', custom: 'projects', also: ['projects'], blocks: [
      heading('projects', { ledeEmpty: long('Line beside the heading while no project is shown with photos') }),
      { key: 'sites', spec: { kind: 'list', label: 'Where we are building', item: 'Group of sites', title: (v) => String(v.group ?? ''), of: { group: text('Group'), where: text('Where'), names: { kind: 'strings', label: 'Sites', item: 'Site' } }, blank: () => ({ group: '', where: '', names: [] }) } },
      { key: 'sitePhotos', spec: { kind: 'list', label: 'Photographs from our sites', item: 'Photograph', title: (v) => String(v.site ?? ''), of: { img: { kind: 'image', label: 'Photograph', place: 'section' }, site: text('Site'), text: long('What it shows') }, blank: () => ({ img: '', site: '', text: '' }) } },
    ],
  },
  {
    id: 'story', label: 'Our story', blocks: [
      heading('story'),
      { key: 'timeline', spec: { kind: 'list', label: 'Milestones', item: 'Milestone', title: (v) => [v.y, v.t].filter(Boolean).join(' - '), of: { y: text('Year'), t: text('Title'), d: long('One line'), img: { kind: 'image', label: 'Photograph', place: 'story' } }, blank: () => ({ y: '', t: '', d: '', img: '' }) } },
    ],
  },
  {
    id: 'credentials', label: 'Credentials', blocks: [
      heading('credentials'),
      { key: 'credentials', spec: { kind: 'list', label: 'Credentials', item: 'Credential', title: (v) => String(v.label ?? ''), of: { label: text('Name', 'e.g. Contractor registration, ISO 9001, GSTIN, RERA'), value: long('Value', 'The class, number or certificate - only what we can show a copy of. Left empty, it is not shown on the website.') }, blank: () => ({ label: '', value: '' }) } },
    ],
  },
  {
    id: 'safety', label: 'Quality & safety', blocks: [
      heading('safety'),
      { key: 'safety', spec: { kind: 'list', label: 'Policies', item: 'Policy', title: (v) => String(v.title ?? ''), of: { title: text('Title'), text: long('What we do') }, blank: () => ({ title: '', text: '' }) } },
    ],
  },
  { id: 'quote', label: 'Start a project', blocks: [heading('quote')] },
  { id: 'careers', label: 'Careers', hint: 'Openings go on the website as soon as they are posted, and come off when closed. Applications arrive in Recruitment.', custom: 'careers', blocks: [heading('careers')] },
  {
    id: 'contact', label: 'Contact details', blocks: [
      heading('contact'),
      {
        key: 'company', title: 'The company', spec: {
          kind: 'object', fields: {
            name: text('Company name'), email: text('Email'), address: long('Office address', 'Also where the map points.'),
            phone: { kind: 'object', fields: { show: text('Phone, as shown'), tel: text('Phone, as dialled', 'With the country code, e.g. +914040059348') } },
            founded: { kind: 'number', label: 'Year founded', hint: 'Shown as "Years building". Leave empty to leave it out.' },
            staff: { kind: 'number', label: 'Engineers & crew', hint: 'Leave empty to leave it out.' },
          },
        },
      },
    ],
  },
  { id: 'footer', label: 'Footer', hint: 'The "Staff login" link is always there.', blocks: [{ key: 'footer', spec: { kind: 'object', fields: { tagline: text('Line after the company name'), showGroupLink: { kind: 'bool', label: 'Link to the group company' } } } }] },
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
