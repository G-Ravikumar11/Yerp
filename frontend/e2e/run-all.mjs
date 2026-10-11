/**
 * Every browser suite in turn, against the app the backend is serving.
 *
 *   npm run build && npm run e2e
 *
 * Needs the backend running on a throwaway database (see lib.mjs), because the
 * suites create, approve and cancel real records.
 */
import { spawnSync } from 'node:child_process'
import { readdirSync } from 'node:fs'
import { join } from 'node:path'

const dir = import.meta.dirname
const suites = readdirSync(dir).filter((f) => f.endsWith('.e2e.mjs')).sort()
const failed = []
for (const suite of suites) {
  console.log(`\n=== ${suite}`)
  const r = spawnSync(process.execPath, [join(dir, suite)], { stdio: 'inherit' })
  if (r.status !== 0) failed.push(suite)
}
console.log(failed.length ? `\nFAILED: ${failed.join(', ')}` : `\nAll ${suites.length} suites passed.`)
process.exit(failed.length ? 1 : 0)
