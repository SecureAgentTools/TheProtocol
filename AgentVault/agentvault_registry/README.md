# The Protocol Registry

A world-class registry system for autonomous agent networks, featuring AAA-grade UI design, advanced visualizations, and enterprise-grade functionality.

## Quick Start

### Local Development

1. **Prerequisites**:
   - Docker Desktop
   - Port 8000 available

2. **Start the registry**:
   ```bash
   # Windows
   start-local.bat
   
   # Linux/Mac
   ./start-local.sh
   ```

3. **Access the registry**:
   - UI: http://localhost:8000
   - API Docs: http://localhost:8000/docs

### First Time Setup

1. The intro video will play on first visit
2. Register a new account or login
3. Explore the Mission Control dashboard

## Features

- **Mission Control**: Command center dashboard with real-time stats
- **Galactic Map**: 3D holographic agent discovery interface
- **Senate Floor**: Locks and governance
- **Federation Embassy**: WebGL 3D globe network visualization
- **Agent Architect**: Visual programming interface for building agents
- **TEG Integration**: Token Economic Graph support
- **Sound Design**: Optional immersive audio system

## Project Structure

```
agentvault_registry/
├── src/agentvault_registry/    # Main application code
│   ├── main.py                 # FastAPI application
│   ├── routers/                # API endpoints
│   ├── static/                 # Frontend assets
│   └── templates/              # HTML templates
├── alembic/                    # Database migrations
├── tests/                      # Test suite
├── docs/                       # Documentation
├── docker-compose.local.yml    # Local development
├── Dockerfile.local            # Local Docker image
└── requirements.txt            # Python dependencies
```

## Development

### Running Tests
```bash
docker-compose -f docker-compose.local.yml run registry pytest
```

### Database Migrations
```bash
# Create new migration
docker-compose -f docker-compose.local.yml run registry alembic revision --autogenerate -m "Description"

# Apply migrations
docker-compose -f docker-compose.local.yml run registry alembic upgrade head
```

### Accessing Logs
```bash
docker-compose -f docker-compose.local.yml logs -f registry
```

## Environment Variables

See `.env.example` for all available configuration options.

Key variables:
- `DATABASE_URL`: PostgreSQL connection string
- `SECRET_KEY`: Application secret key
- `JWT_SECRET_KEY`: JWT signing key
- `MAIL_*`: Email configuration

## Troubleshooting

### Port Already in Use
```bash
# Find process using port 8000
netstat -ano | findstr :8000

# Kill the process
taskkill /PID <PID> /F
```

### Database Connection Issues
```bash
# Reset database
docker-compose -f docker-compose.local.yml down -v
docker-compose -f docker-compose.local.yml up
```

### Frontend Not Loading
- Check browser console for errors
- Ensure static files are properly mounted
- Clear browser cache (Ctrl+Shift+R)

## Production Deployment

For production deployment, use the main `docker-compose.yml` in the parent directory with proper environment variables and security configurations.

## License

Copyright 2025 AgentVault. All rights reserved.
