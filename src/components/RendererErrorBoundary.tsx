import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Keeps a renderer exception from becoming an indistinguishable empty window.
 *
 * Electron does not provide a browser error page for a React render failure.
 * A visible recovery screen lets the operator reload the renderer without
 * quitting the desktop process (and without changing trading state).
 */
export class RendererErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('Renderer render failure', error, info.componentStack);
  }

  private reload = (): void => {
    window.location.reload();
  };

  render(): ReactNode {
    if (!this.state.error) return this.props.children;

    return (
      <main className="flex min-h-screen items-center justify-center bg-rom-void px-6 text-rom-text">
        <section className="w-full max-w-lg rounded-2xl border border-rom-border bg-rom-surface p-7 shadow-rom-soft">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-rom-muted">ROM PolyBot</p>
          <h1 className="mt-3 text-xl font-semibold text-white">This screen ran into a problem</h1>
          <p className="mt-3 text-sm leading-6 text-rom-muted">
            Trading and the backend keep their own state. Reload this screen to reconnect to them.
          </p>
          <button type="button" className="rom-btn-primary mt-6" onClick={this.reload}>
            Reload screen
          </button>
          <details className="mt-5 rounded-lg border border-rom-border bg-rom-void p-3 text-xs text-rom-muted">
            <summary className="cursor-pointer select-none">Technical details</summary>
            <pre className="mt-3 whitespace-pre-wrap break-words text-rom-lossText">
              {this.state.error.message || String(this.state.error)}
            </pre>
          </details>
        </section>
      </main>
    );
  }
}
