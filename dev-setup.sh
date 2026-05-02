#!/bin/bash
# Development Setup Script for SingleStore Report Sniffer

echo "🚀 Setting up development environment..."

# Check if backend is running
if curl -s http://localhost:8000/api/health > /dev/null; then
    echo "✅ Backend is running"
else
    echo "❌ Backend is not running. Starting backend..."
    cd backend
    source venv/bin/activate
    uvicorn server:app --host 0.0.0.0 --port 8000 --reload &
    BACKEND_PID=$!
    cd ..
    echo "🔄 Backend started with PID: $BACKEND_PID"
fi

# Install frontend dependencies if needed
if [ ! -d "frontend/node_modules" ]; then
    echo "📦 Installing frontend dependencies..."
    cd frontend
    npm install
    cd ..
fi

# Start frontend development server
echo "🎨 Starting frontend development server..."
cd frontend
npm run dev

echo "✅ Development environment setup complete!"
echo "🌐 Frontend: http://localhost:3000 (Vite)"
echo "🔧 Backend: http://localhost:8000"
echo "📚 API Docs: http://localhost:8000/api/docs"