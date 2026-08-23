import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import ReportList from "@/pages/ReportList";
import ReportDashboard from "@/pages/ReportDashboard";
import { Toaster } from "@/components/ui/sonner";
import ErrorBoundary from "@/components/ErrorBoundary";
import UpdateBanner from "@/components/UpdateBanner";
import TerminologyNormalizer from "@/components/TerminologyNormalizer";
import { GuidedModeProvider } from "@/guided-mode/GuidedModeProvider";
import GuidedTourOverlay from "@/guided-mode/GuidedTourOverlay";

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
        <TerminologyNormalizer />
        <BrowserRouter basename={getRouterBasename()}>
          <GuidedModeProvider>
            <Routes>
              <Route path="/" element={<ReportList />} />
              <Route path="/report/:reportId/*" element={<ReportDashboard />} />
            </Routes>
            <GuidedTourOverlay />
          </GuidedModeProvider>
        </BrowserRouter>
        <Toaster position="top-right" />
        <UpdateBanner />
      </div>
    </ErrorBoundary>
  );
}

export default App;
