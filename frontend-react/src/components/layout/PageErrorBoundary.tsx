import { Component, type ErrorInfo, type ReactNode } from 'react'
import { AlertTriangle } from 'lucide-react'
import { Button } from '@/components/ui'

interface State {
  error: Error | null
}

/**
 * A fault on one screen must not take the whole app with it. The sidebar and
 * the rest keep working; this page says it broke and offers another go.
 */
export class PageErrorBoundary extends Component<{ children: ReactNode; resetKey: string }, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Page error:', error, info.componentStack)
  }

  componentDidUpdate(prev: { resetKey: string }) {
    // Going to another page clears it.
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null })
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div role="alert" className="mx-auto max-w-md py-20 text-center">
        <span className="mx-auto grid size-14 place-items-center rounded-2xl bg-danger-soft text-danger">
          <AlertTriangle className="size-6" />
        </span>
        <h1 className="mt-5 text-2xl font-semibold">This page hit a problem</h1>
        <p className="mt-2 text-[15px] text-muted-foreground">Nothing you entered elsewhere was lost. Try again, or go to another screen.</p>
        <Button className="mt-6" onClick={() => this.setState({ error: null })}>
          Try again
        </Button>
      </div>
    )
  }
}
