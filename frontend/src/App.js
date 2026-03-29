import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import ReportList from "@/pages/ReportList";
import ReportDashboard from "@/pages/ReportDashboard";
import { Toaster } from "@/components/ui/sonner";

function App() {
  return (
    <div className="App">
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<ReportList />} />
          <Route path="/report/:reportId/*" element={<ReportDashboard />} />
        </Routes>
      </BrowserRouter>
      <Toaster position="top-right" />
    </div>
  );
}

export default App;
