# Frontend-Backend Integration Guide

## 🚀 Quick Start

Your SingleStore Report Sniffer is now properly wired with frontend-backend integration!

### Development Setup

1. **Start Backend** (if not already running):
   ```bash
   cd backend
   source venv/bin/activate
   uvicorn server:app --host 0.0.0.0 --port 8000 --reload
   ```

2. **Start Frontend**:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

3. **Or use the automated setup script**:
   ```bash
   chmod +x dev-setup.sh
   ./dev-setup.sh
   ```

### 🌐 Access Points

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/api/docs
- **Integration Test**: http://localhost:3000/integration-test.html

## 🔧 Configuration

### Frontend Environment Variables

The frontend uses these environment variables (configured in `.env`):

```bash
# Optional — only when the UI is not same-origin with the API
VITE_BACKEND_URL=http://localhost:8000
```

### Backend CORS Configuration

The backend is configured to accept requests from any origin in development:

```python
allow_origins=os.environ.get('CORS_ORIGINS', '*').split(',')
```

### API Proxy Configuration

The Vite dev server proxies `/api` to the backend (`frontend/vite.config.js` `server.proxy`).

## 🔍 Testing Integration

### Manual Testing

1. **Backend Health Check**:
   ```bash
   curl http://localhost:8000/api/health
   ```

2. **Frontend API Test**:
   - Open browser console on http://localhost:3000
   - Check for API request/response logs

3. **File Upload Test**:
   - Use the integration test page: http://localhost:3000/integration-test.html
   - Upload a test file (`.zip` or `.tar.gz`)

### API Endpoints Available

- `POST /api/reports/upload` - Upload report files
- `GET /api/reports` - List all reports
- `GET /api/reports/{id}/status` - Get report processing status
- `GET /api/reports/{id}/overview` - Get report overview
- `GET /api/reports/{id}/nodes` - Get cluster nodes
- `GET /api/reports/{id}/storage` - Get storage information
- `GET /api/reports/{id}/queries` - Get query data
- `GET /api/reports/{id}/logs` - Get logs with search/filter
- `GET /api/reports/{id}/recommendations` - Get recommendations
- `GET /api/reports/{id}/config` - Get configuration
- `DELETE /api/reports/{id}` - Delete report

## Analyze in Glean (local packet handoff)

One-click RCA handoff builds a curated Markdown incident packet locally. Glean Desktop does not auto-ingest local files — the user attaches the downloaded packet in Glean Chat.

### Flow

1. On the **Issues** tab, click **Analyze in Glean**.
2. Backend returns `{filename, markdown, prompt}` from `GET /api/reports/{id}/export/glean`.
3. Browser: download `.md` + copy prompt + toast. Electron: save to Downloads, copy prompt, reveal in Finder, open Glean.app (web fallback).

### API

- `GET /api/reports/{report_id}/export/glean` — whole-report Markdown packet (no cloud-extensions gate)

### Privacy

Packet generation is fully local. Customer data leaves the machine only when the user explicitly attaches the file inside Glean. Optional Hostinger remains gated by `S2RS_ENABLE_CLOUD_EXTENSIONS`.

## 🛠️ Frontend Components

### API Client (`src/lib/api.js`)

- Axios-based HTTP client
- Request/response interceptors for debugging
- Automatic error handling
- File upload progress tracking

### Main Components

- **ReportList**: Displays list of uploaded reports
- **ReportDashboard**: Shows detailed report analysis
- **File Upload**: Handles report file uploads

## 🔧 Troubleshooting

### Common Issues

1. **Backend not responding**:
   - Check if backend is running: `curl http://localhost:8000/api/health`
   - Verify virtual environment is activated

2. **CORS errors**:
   - Backend CORS is configured for development
   - Check browser console for specific CORS errors

3. **File upload fails**:
   - Check file size (max 10GB)
   - Ensure file is `.zip` or `.tar.gz` format
   - Check backend logs for parsing errors

4. **Frontend proxy issues**:
   - Verify `vite.config.js` `server.proxy` for `/api`
   - Check that backend is running on port 8000

5. **Analyze in Glean toast but Glean did not open**:
   - Desktop: confirm Glean.app is installed (`open -a Glean`), otherwise the app opens `https://app.glean.com/chat`.
   - Browser: download the `.md` from Downloads and attach it manually in Glean Chat.
   - Packet is still useful offline as a shareable incident summary.

### Debug Mode

The frontend includes debug logging:
- API requests are logged to browser console
- Response status and data are logged
- Error details are displayed in console

## 📊 Monitoring

- Backend health: http://localhost:8000/api/health
- Performance metrics: http://localhost:8000/api/metrics/performance
- Active alerts: http://localhost:8000/api/alerts

## 🚀 Production Deployment

For production deployment:

1. **Build frontend**:
   ```bash
   cd frontend
   npm run build
   ```

2. **Configure backend**:
   - Set `S2RS_UI_DIR` environment variable to frontend build path
   - Configure proper CORS origins
   - Set up production database/storage

3. **Environment variables**:
   - `CORS_ORIGINS`: Comma-separated allowed origins
   - `S2RS_UI_DIR`: Path to frontend build directory