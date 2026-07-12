import axios, { AxiosInstance, AxiosProgressEvent } from "axios";

const BACKEND_URL =
  (typeof import.meta !== "undefined" && import.meta.env && import.meta.env.VITE_BACKEND_URL) ||
  "";

const isIntegratedUi =
  typeof window !== "undefined" &&
  (window.location.pathname === "/ui" || window.location.pathname.startsWith("/ui/"));

const API = isIntegratedUi ? "/api" : BACKEND_URL ? `${BACKEND_URL}/api` : "/api";

const api: AxiosInstance = axios.create({
  baseURL: API,
  timeout: 30000,
  headers: {
    "Content-Type": "application/json",
  },
});

const DEBUG = (typeof import.meta !== "undefined" && import.meta.env && import.meta.env.DEV) || false;

if (DEBUG) {
  api.interceptors.request.use(
    (config) => {
      console.log(`🚀 ${config.method?.toUpperCase()} ${config.url}`, config.params || "");
      return config;
    },
    (error) => {
      console.error("❌ Request error:", error);
      return Promise.reject(error);
    }
  );

  api.interceptors.response.use(
    (response) => {
      console.log(`✅ ${response.status} ${response.config.url}`);
      return response;
    },
    (error) => {
      console.error("❌ Response error:", {
        url: error.config?.url,
        status: error.response?.status,
        statusText: error.response?.statusText,
        data: error.response?.data,
        message: error.message,
      });

      if (error.response?.data) {
        (error as any).parsedData = error.response.data;
      }

      return Promise.reject(error);
    }
  );
}

export const uploadReport = (
  file: File,
  onProgress?: (progressEvent: AxiosProgressEvent) => void
) => {
  const formData = new FormData();
  formData.append("file", file);
  return api.post("/reports/upload", formData, {
    headers: { "Content-Type": undefined }, // let axios/browser set boundary for multipart
    timeout: 0, // no timeout for uploads — file size is bounded server-side at 10 GB
    onUploadProgress: onProgress,
  });
};

export const importReport = (path: string) => api.post("/reports/import", { path });

export const listReports = () => api.get("/reports");
export const getReportStatus = (id: string) => api.get(`/reports/${id}/status`);
export const getReportOverview = (id: string) => api.get(`/reports/${id}/overview`);
export const rehydrateDiagnostics = (id: string, path: string) =>
  api.post(`/reports/${id}/rehydrate-diagnostics`, { path }, { timeout: 120000 });
export const getReportNodes = (id: string) => api.get(`/reports/${id}/nodes`);
export const getReportStorage = (id: string) => api.get(`/reports/${id}/storage`);
export const getReportQueries = (id: string) => api.get(`/reports/${id}/queries`);
export const getReportLogs = (id: string, params?: Record<string, any>) =>
  api.get(`/reports/${id}/logs`, { params });
export const searchReportLogs = (
  id: string,
  params: {
    keyword: string;
    regex?: boolean;
    severity?: string;
    node?: string;
    case_sensitive?: boolean;
    max_results?: number;
  }
) => api.get(`/reports/${id}/logs/search`, { params });
export const getReportPipelines = (id: string) => api.get(`/reports/${id}/pipelines`);
export const getReportRecommendations = (id: string) => api.get(`/reports/${id}/recommendations`);
export const getReportTriage = (id: string) => api.get(`/reports/${id}/triage`);
export const getReportConfig = (id: string) => api.get(`/reports/${id}/config`);
export const deleteReport = (id: string) => api.delete(`/reports/${id}`);

export const listQueryTraces = (id: string) => api.get(`/reports/${id}/query-traces`);
export const getQueryTrace = (id: string, traceId: string) =>
  api.get(`/reports/${id}/query-traces/${traceId}`);
export const resolveQueryTrace = (
  id: string,
  selector: {
    trace_id?: string;
    connection_id?: string;
    activity_name?: string;
    query_text?: string;
    normalized_sql?: string;
  }
) => api.post(`/reports/${id}/query-traces/resolve`, selector);

// Glean MCP Integration API
export const getGleanConfig = () => api.get("/glean/config");
export const saveGleanConfig = (config: Record<string, any>) => api.post("/glean/config", config);
export const testGleanConnection = () => api.post("/glean/health");
export const fetchGleanInsights = (reportId: string, reportData: Record<string, any>) =>
  api.post("/glean/insights", { report_id: reportId, report_data: reportData });
export const enrichFindings = (
  reportId: string,
  findings: any[],
  reportMetadata: Record<string, any>
) => api.post("/glean/enrich", { report_id: reportId, findings, report_metadata: reportMetadata });
