import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = {
  children: ReactNode;
};

type State = {
  hasError: boolean;
  message: string;
};

export class AppErrorBoundary extends Component<Props, State> {
  state: State = {
    hasError: false,
    message: "",
  };

  static getDerivedStateFromError(error: Error): State {
    return {
      hasError: true,
      message: error.message || "Unexpected frontend error",
    };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Keep details in browser console for debugging if available.
    // This prevents a blank screen and shows a readable fallback in UI.
    console.error("App render error:", error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="page">
          <div className="error">
            Failed to render this page.
            <br />
            <strong>{this.state.message}</strong>
          </div>
          <a className="btn-secondary" href="/">Back to Library</a>
        </div>
      );
    }

    return this.props.children;
  }
}

