import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import ReportList from "@/pages/ReportList";
import ReportDashboard from "@/pages/ReportDashboard";
import { Toaster } from "@/components/ui/sonner";
import ErrorBoundary from "@/components/ErrorBoundary";

function getRouterBasename() {
  if (typeof window === "undefined") return "/";
  const p = window.location?.pathname || "/";
  if (p === "/ui" || p.startsWith("/ui/")) return "/ui";
  return "/";
}

function App() {
  return (
    <ErrorBoundary>
      <div className="App">
        <BrowserRouter basename={getRouterBasename()}>
          <Routes>
            <Route path="/" element={<ReportList />} />
            <Route path="/report/:reportId/*" element={<ReportDashboard />} />
          </Routes>
        </BrowserRouter>
        <Toaster position="top-right" />
      </div>
    </ErrorBoundary>
  );
}

export default App;
