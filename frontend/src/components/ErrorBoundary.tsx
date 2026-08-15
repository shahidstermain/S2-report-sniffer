import React from 'react';
import { AlertTriangle } from 'lucide-react';

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary caught an error', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen flex items-center justify-center bg-gray-50">
          <div className="ss-card p-8 w-[480px] text-center">
            <AlertTriangle size={48} className="mx-auto mb-4 text-red-500" />
            <h1 className="text-xl font-bold mb-2">Something went wrong</h1>
            <p className="text-sm text-gray-600 mb-4">
              {this.state.error?.message || 'An unexpected error occurred in the UI.'}
            </p>
            <button
              onClick={() => window.location.href = '/'}
              className="px-4 py-2 bg-purple-600 text-white rounded text-sm font-semibold hover:bg-purple-700"
            >
              Return to Home
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
