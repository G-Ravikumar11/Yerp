import type { Portal } from '@/api/people'

export type Level = 'none' | 'read' | 'write'

/** Where a set of rights stands on one portal: none without its view right, write once it holds any of the portal's write rights. */
export const levelOf = (pt: Portal, held: Set<string>): Level =>
  pt.read.length === 0 || !held.has(pt.read[0]!) ? 'none' : pt.write.some((k) => held.has(k)) ? 'write' : 'read'

/** The rights after one portal is set to a level. Only that portal's own rights change; every other right is kept as it was. */
export function withLevel(rights: string[], pt: Portal, level: Level): string[] {
  const own = new Set([...pt.read, ...pt.write])
  return [...rights.filter((k) => !own.has(k)), ...(level === 'none' ? [] : pt.read), ...(level === 'write' ? pt.write : [])]
}
