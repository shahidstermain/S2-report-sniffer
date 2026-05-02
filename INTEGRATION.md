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