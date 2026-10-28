import axios, { AxiosInstance, AxiosProgressEvent, AxiosPromise } from "axios";
import type {
  LogSearchResponse,
  ReportOverview,
  ReportStatusResponse,
  UploadResponse,
} from "@/types/api";

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
  onProgress?: (progressEvent: AxiosProgressEvent) => void,
  options: { anonymize?: boolean } = {}
): AxiosPromise<UploadResponse> => {
  const formData = new FormData();
  formData.append("file", file);
  return api.post("/reports/upload", formData, {
    params: { anonymize: options.anonymize ?? true },
    timeout: 0, // no timeout for uploads — file size is bounded server-side at 10 GB
    ...(onProgress ? { onUploadProgress: onProgress } : {}),
  });
};

export const importReport = (path: string, options: { anonymize?: boolean } = {}) =>
  api.post("/reports/import", { path, anonymize: options.anonymize ?? true });

export const listReports = () => api.get("/reports");
export const getExplainers = () => api.get("/explainers");
export const getReportStatus = (id: string): AxiosPromise<ReportStatusResponse> =>
  api.get(`/reports/${encodeURIComponent(id)}/status`);
export const getReportOverview = (id: string): AxiosPromise<ReportOverview> =>
  api.get(`/reports/${encodeURIComponent(id)}/overview`);
export const rehydrateDiagnostics = (id: string, path: string) =>
  api.post(`/reports/${id}/rehydrate-diagnostics`, { path }, { timeout: 120000 });
export const getReportNodes = (id: string) => api.get(`/reports/${id}/nodes`);
export const getReportStorage = (id: string) =>
  api.get(`/reports/${id}/storage`, { timeout: 120000 });
export const getReportDiskIntelligence = (id: string) =>
  api.get(`/reports/${id}/disk-intelligence`, { timeout: 120000 });
export const getReportQueries = (id: string) => api.get(`/reports/${id}/queries`);
export const getReportLogs = (id: string, params?: Record<string, unknown>) =>
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
    start?: string;
    end?: string;
    context_lines?: number;
  }
): AxiosPromise<LogSearchResponse> => api.get(`/reports/${encodeURIComponent(id)}/logs/search`, { params });
export const getReportPipelines = (id: string) => api.get(`/reports/${id}/pipelines`);
export const getReportRecommendations = (id: string) => api.get(`/reports/${id}/recommendations`);
export const getReportTriage = (id: string) => api.get(`/reports/${id}/triage`);
export const getReportConfig = (id: string) => api.get(`/reports/${id}/config`);
export const deleteReport = (id: string) => api.delete(`/reports/${id}`);
export const compareReports = (fromId: string, toId: string) =>
  api.get("/reports/diff", { params: { from_id: fromId, to_id: toId } });
export const exportReportMarkdown = (id: string) =>
  api.get(`/reports/${id}/export/markdown`, { responseType: "blob" });
export const exportReportHtml = (id: string) =>
  api.get(`/reports/${id}/export/html`, { responseType: "blob" });
export const getTelemetrySettings = () => api.get("/settings/telemetry");
export const updateTelemetrySettings = (enabled: boolean) =>
  api.put("/settings/telemetry", { enabled });

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

/** Whole-report Markdown packet for Glean Chat handoff. */
export const getGleanPacket = (reportId: string) =>
  api.get(`/reports/${reportId}/export/glean`);

/** Whole-report AI-ready JSON incident packet for LLM root-cause analysis. */
export const getAiExportJson = (reportId: string) =>
  api.get(`/reports/${reportId}/export/json`, { responseType: "blob" });
