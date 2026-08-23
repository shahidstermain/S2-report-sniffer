import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { createDemoWorkspace } from "@/lib/api";
import { GUIDED_MODE_VERSION, loadGuidedPreference, saveGuidedPreference } from "./guidedModeStorage";
import { tourForPath } from "./tourRegistry";

const DEFAULT_GUIDED_MODE = {
  activeTour: null,
  explainPage: false,
  launchingDemo: false,
  reportId: null,
  startTour: () => {},
  stopTour: () => {},
  setTourIndex: () => {},
  toggleExplainPage: () => {},
  launchDemoWorkspace: async () => null,
};

const GuidedModeContext = createContext(DEFAULT_GUIDED_MODE);

export function GuidedModeProvider({ children }) {
  const location = useLocation();
  const navigate = useNavigate();
  const params = useParams();
  const [activeTour, setActiveTour] = useState(null);
  const [explainPage, setExplainPage] = useState(() => Boolean(loadGuidedPreference("explainPage", false)));
  const [launchingDemo, setLaunchingDemo] = useState(false);

  const startTour = useCallback((startIndex = 0) => {
    const steps = tourForPath(location.pathname);
    setActiveTour({ steps, index: startIndex });
    saveGuidedPreference("lastTour", { pathname: location.pathname, startedAt: Date.now() });
  }, [location.pathname]);

  const stopTour = useCallback((completed = false) => {
    if (completed) saveGuidedPreference("completedVersion", GUIDED_MODE_VERSION);
    setActiveTour(null);
  }, []);

  const setTourIndex = useCallback((index) => {
    setActiveTour((tour) => tour ? { ...tour, index } : tour);
    saveGuidedPreference("lastStep", index);
  }, []);

  const toggleExplainPage = useCallback(() => {
    setExplainPage((value) => {
      const next = !value;
      saveGuidedPreference("explainPage", next);
      return next;
    });
  }, []);

  const launchDemoWorkspace = useCallback(async () => {
    setLaunchingDemo(true);
    try {
      const response = await createDemoWorkspace();
      const reports = response.data?.reports || [];
      const incident = reports.find((report) => report.scenario === "incident") || reports[0];
      toast.success("Demo workspace ready");
      if (incident?.id) {
        navigate(`/report/${incident.id}/overview`);
      }
      return response.data;
    } catch (error) {
      toast.error("Could not create demo workspace");
      throw error;
    } finally {
      setLaunchingDemo(false);
    }
  }, [navigate]);

  const value = useMemo(() => ({
    activeTour,
    explainPage,
    launchingDemo,
    reportId: params.reportId,
    startTour,
    stopTour,
    setTourIndex,
    toggleExplainPage,
    launchDemoWorkspace,
  }), [activeTour, explainPage, launchingDemo, params.reportId, startTour, stopTour, setTourIndex, toggleExplainPage, launchDemoWorkspace]);

  return (
    <GuidedModeContext.Provider value={value}>
      {children}
    </GuidedModeContext.Provider>
  );
}

export function useGuidedMode() {
  return useContext(GuidedModeContext) || DEFAULT_GUIDED_MODE;
}
