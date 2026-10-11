import { Letterheads } from './Letterheads'
import { Signatories } from './Signatories'
import { Terms } from './Terms'

/** What the company's paper looks like: letterheads, who signs, and the printed conditions. */
export default function DocumentsTab() {
  return (
    <>
      <Letterheads />
      <Signatories />
      <Terms />
    </>
  )
}
