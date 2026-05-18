import axios from "axios";

const BACKEND_URL =
  (typeof import.meta !== "undefined" && import.meta.env && import.meta.env.VITE_BACKEND_URL) ||
  "";

const isIntegratedUi =
  typeof window !== "undefined" &&
  (window.location.pathname === "/ui" || window.location.pathname.startsWith("/ui/"));

const API = isIntegratedUi ? "/api" : (BACKEND_URL ? `${BACKEND_URL}/api` : "/api");

const api = axios.create({ 
  baseURL: API,
  timeout: 30000, // 30 second timeout for large file uploads
  headers: {
    'Content-Type': 'application/json',
  }
});

const DEBUG =
  (typeof import.meta !== "undefined" && import.meta.env && import.meta.env.DEV) || false;

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
        error.parsedData = error.response.data;
      }

      return Promise.reject(error);
    }
  );
}

export const uploadReport = (file, onProgress) => {
  const formData = new FormData();
  formData.append("file", file);
  return api.post("/reports/upload", formData, {
    headers: { "Content-Type": "multipart/form-data" },
    onUploadProgress: onProgress,
  });
};

export const importReport = (path) => api.post("/reports/import", { path });

export const listReports = () => api.get("/reports");
export const getReportStatus = (id) => api.get(`/reports/${id}/status`);
export const getReportOverview = (id) => api.get(`/reports/${id}/overview`);
export const getReportNodes = (id) => api.get(`/reports/${id}/nodes`);
export const getReportStorage = (id) => api.get(`/reports/${id}/storage`);
export const getReportQueries = (id) => api.get(`/reports/${id}/queries`);
export const getReportLogs = (id, params) => api.get(`/reports/${id}/logs`, { params });
export const getReportPipelines = (id) => api.get(`/reports/${id}/pipelines`);
export const getReportRecommendations = (id) => api.get(`/reports/${id}/recommendations`);
export const getReportConfig = (id) => api.get(`/reports/${id}/config`);
export const deleteReport = (id) => api.delete(`/reports/${id}`);

// Glean MCP Integration API
export const getGleanConfig = () => api.get("/glean/config");
export const saveGleanConfig = (config) => api.post("/glean/config", config);
export const testGleanConnection = () => api.post("/glean/health");
export const fetchGleanInsights = (reportId, reportData) => api.post("/glean/insights", { report_id: reportId, report_data: reportData });
export const enrichFindings = (reportId, findings, reportMetadata) => api.post("/glean/enrich", { report_id: reportId, findings, report_metadata: reportMetadata });
