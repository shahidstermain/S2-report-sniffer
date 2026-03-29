import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const api = axios.create({ baseURL: API });

export const uploadReport = (file, onProgress) => {
  const formData = new FormData();
  formData.append("file", file);
  return api.post("/reports/upload", formData, {
    headers: { "Content-Type": "multipart/form-data" },
    onUploadProgress: onProgress,
  });
};

export const listReports = () => api.get("/reports");
export const getReportStatus = (id) => api.get(`/reports/${id}/status`);
export const getReportOverview = (id) => api.get(`/reports/${id}/overview`);
export const getReportNodes = (id) => api.get(`/reports/${id}/nodes`);
export const getReportStorage = (id) => api.get(`/reports/${id}/storage`);
export const getReportQueries = (id) => api.get(`/reports/${id}/queries`);
export const getReportLogs = (id, params) => api.get(`/reports/${id}/logs`, { params });
export const getReportPipelines = (id) => api.get(`/reports/${id}/pipelines`);
export const getReportRecommendations = (id) => api.get(`/reports/${id}/recommendations`);
export const deleteReport = (id) => api.delete(`/reports/${id}`);
