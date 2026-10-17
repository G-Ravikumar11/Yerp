import { StoreShell } from '../StoreShell'

/** Store > Control. Owned by P4: replace the body, keep the shell. Routes under /store/hub/control/* land here, so
 * add your own sub-routes with <Routes> inside this component rather than in src/routes.tsx. */
export default function ControlIndex() {
  // TODO(P4)
  return (
    <StoreShell slice="control">
      <p className="text-sm text-muted-foreground">Nothing here yet.</p>
    </StoreShell>
  )
}
