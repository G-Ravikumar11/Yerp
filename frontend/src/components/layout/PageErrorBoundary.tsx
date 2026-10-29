import { Component, type ErrorInfo, type ReactNode } from 'react'
import { newRef } from '@/lib/errorCodes'
import { ErrorPage } from '@/components/errors/ErrorPage'
import { reportScreenFault } from '@/api/errorLog'

interface State {
  error: Error | null
  /** The reference for this failure, shown on the page and written to the console with the error. */
  ref: string
}

/**
 * A fault on one screen must not take the whole app with it. The sidebar and
 * the rest keep working; this page says it broke and offers another go.
 */
export class PageErrorBoundary extends Component<{ children: ReactNode; resetKey: string }, State> {
  state: State = { error: null, ref: '' }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error, ref: newRef() }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`YE-APP ref=${this.state.ref} page error:`, error, info.componentStack)
    // So it shows in Settings > Error log, under the same ref as on this screen.
    reportScreenFault(this.state.ref, error.message || String(error), `${error.stack ?? ''}\n${info.componentStack ?? ''}`)
  }

  componentDidUpdate(prev: { resetKey: string }) {
    // Going to another page clears it.
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null, ref: '' })
  }

  render() {
    if (!this.state.error) return this.props.children
    return <ErrorPage kind="crash" code="YE-APP" errorRef={this.state.ref} onRetry={() => this.setState({ error: null, ref: '' })} />
  }
}
