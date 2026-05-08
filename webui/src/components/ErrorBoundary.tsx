import { Component, type ErrorInfo, type ReactNode } from "react";

interface ErrorBoundaryProps {
  children: ReactNode;
  /** Optional renderer for the fallback UI. Receives the caught error so
   * consumers can surface contextual hints (e.g. "reload the page"). */
  fallback?: (error: Error, reset: () => void) => ReactNode;
  /** Hook for telemetry / logging. */
  onError?: (error: Error, info: ErrorInfo) => void;
}

interface ErrorBoundaryState {
  error: Error | null;
}

/**
 * Top-level safety net for the chat UI.
 *
 * React 18 unmounts the entire tree on an uncaught render error, which in
 * this app manifests as a blank white page after an action (e.g. ``send``).
 * Wrapping the chat surface in this boundary keeps the chrome mounted and
 * gives the user a way to recover without a full page reload — and, crucially,
 * surfaces the underlying error message instead of silently vanishing.
 */
export class ErrorBoundary extends Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Always log so devs can inspect the stack in the browser console even
    // when telemetry hooks aren't wired up.
    // eslint-disable-next-line no-console
    console.error("[ErrorBoundary]", error, info.componentStack);
    this.props.onError?.(error, info);
  }

  private reset = (): void => {
    this.setState({ error: null });
  };

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;
    if (this.props.fallback) return this.props.fallback(error, this.reset);
    return (
      <div
        role="alert"
        className="m-4 rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm"
      >
        <div className="font-semibold text-destructive">
          界面渲染出错 / UI render error
        </div>
        <div className="mt-1 text-muted-foreground">
          {error.message || String(error)}
        </div>
        <button
          type="button"
          onClick={this.reset}
          className="mt-3 inline-flex items-center rounded border border-border px-3 py-1 text-xs hover:bg-muted"
        >
          重试 / Retry
        </button>
      </div>
    );
  }
}
