import { Partners } from './Partners'
import { Team } from './Team'

/** Who can sign in: the owner's colleagues, and the partners' logins. */
export default function AccessTab() {
  return (
    <>
      <Team />
      <Partners />
    </>
  )
}
