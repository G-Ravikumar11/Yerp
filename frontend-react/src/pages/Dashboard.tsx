import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowUpRight, BookOpenCheck, CheckCheck, ExternalLink, FileSignature, HardHat, Palette, Receipt } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge, Button, CardInteractive, Skeleton } from '@/components/ui'
import { useSession } from '@/lib/session'

const shortcuts = [
  { to: '/approvals', title: 'Approvals', body: 'Work orders, RA bills and vendors waiting on a signature.', icon: CheckCheck },
  { to: '/subcontractors/work-orders', title: 'Subcontract Work Orders', body: 'Issue, amend and track orders to each gang.', icon: FileSignature },
  { to: '/subcontractors/measurement-book', title: 'Measurement Book', body: 'What the gang has built, measured line by line.', icon: BookOpenCheck },
  { to: '/subcontractors/ra-bills', title: 'RA Bills', body: 'Previous, this bill and up to date, certified in turn.', icon: Receipt },
  { to: '/subcontractors/vendors', title: 'Vendor Register', body: 'Every gang with its code and registration form.', icon: HardHat },
]

const stagger = { hidden: {}, show: { transition: { staggerChildren: 0.06 } } }
const rise = { hidden: { opacity: 0, y: 14 }, show: { opacity: 1, y: 0, transition: { duration: 0.4, ease: [0.16, 1, 0.3, 1] as const } } }

export default function Dashboard() {
  const { user, isLoading } = useSession()
  const name = user?.name?.split(' ')[0]

  return (
    <>
      <PageHeader
        eyebrow="Command Center"
        title={isLoading ? 'Welcome back' : name ? `Good to see you, ${name}` : 'Welcome to Y ERP'}
        description="The book, the orders and the bills - in one place. The live figures for project profitability and cash flow arrive with the dashboard step; until then the modules below open the screens as they are ported."
        actions={
          <>
            <Button variant="outline" asChild>
              <Link to="/design">
                <Palette /> Design system
              </Link>
            </Button>
            <Button asChild>
              <a href="/app.html">
                Open current app <ExternalLink />
              </a>
            </Button>
          </>
        }
      />

      <motion.div variants={stagger} initial="hidden" animate="show" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {shortcuts.map(({ to, title, body, icon: Icon }) => (
          <motion.div key={to} variants={rise}>
            <Link to={to} className="group block rounded-xl">
              <CardInteractive className="h-full p-5">
                <div className="flex items-start justify-between">
                  <span className="grid size-11 place-items-center rounded-xl bg-primary-soft text-primary ring-1 ring-primary/20">
                    <Icon className="size-5" />
                  </span>
                  <ArrowUpRight className="size-4 text-subtle transition-all duration-200 group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-primary" />
                </div>
                <h3 className="mt-5 text-[17px] font-semibold">{title}</h3>
                <p className="mt-1.5 text-[13.5px] leading-relaxed text-muted-foreground">{body}</p>
                <div className="mt-4">
                  <Badge tone="neutral">Not yet ported</Badge>
                </div>
              </CardInteractive>
            </Link>
          </motion.div>
        ))}

        <motion.div variants={rise}>
          <div className="flex h-full flex-col justify-between rounded-xl border border-dashed border-border p-5">
            <div>
              <p className="text-sm font-medium">Connected to the live backend</p>
              <p className="mt-1.5 text-[13.5px] leading-relaxed text-muted-foreground">
                Requests go to the same FastAPI service under <code className="font-mono text-xs text-foreground">/api</code>, using your existing session.
              </p>
            </div>
            <div className="mt-4 flex items-center gap-2 text-[13px]">
              {isLoading ? (
                <Skeleton className="h-5 w-40" />
              ) : user ? (
                <Badge tone="success" dot>
                  Signed in as {user.company || user.email}
                </Badge>
              ) : (
                <Badge tone="warning" dot>
                  Not signed in - sign in on the current app first
                </Badge>
              )}
            </div>
          </div>
        </motion.div>
      </motion.div>
    </>
  )
}
