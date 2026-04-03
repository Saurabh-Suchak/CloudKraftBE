# Quick Start Guide - CloudKraft Backend

## Step 1: Install Dependencies ✅
```bash
cd /Users/priyankajadhav/final-year-project/CloudKraftBE
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Step 2: Configure Environment Variables

Create a `.env` file from the example:
```bash
cp .env.example .env
```

Edit `.env` and set the following (at minimum):
```env
# Generate a secure secret key (you can use: python -c "import secrets; print(secrets.token_urlsafe(32))")
SECRET_KEY=your-secret-key-here-change-in-production

# Generate an encryption key for AWS credentials
ENCRYPTION_KEY=your-encryption-key-here-change-in-production

# Database (SQLite by default - no setup needed)
DATABASE_URL=sqlite:///./cloudkraft.db

# CORS - Add your frontend URL
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
```

**Important:** Generate secure keys:
```bash
python -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(32))"
python -c "import secrets; print('ENCRYPTION_KEY=' + secrets.token_urlsafe(32))"
```

## Step 3: Initialize Database

The database will be created automatically on first run, but you can also initialize it manually:

```bash
# Create initial migration
alembic revision --autogenerate -m "Initial migration"

# Apply migrations
alembic upgrade head
```

Or simply start the server - it will create the database automatically.

## Step 4: Start the Backend Server

```bash
# Make sure you're in the CloudKraftBE directory with venv activated
uvicorn app.main:app --reload --port 8000
```

You should see:
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

## Step 5: Verify Backend is Running

1. **Check health endpoint:**
   ```bash
   curl http://localhost:8000/health
   ```
   Should return: `{"status":"healthy"}`

2. **View API documentation:**
   Open in browser: http://localhost:8000/docs
   
   This is the interactive Swagger UI where you can test all endpoints.

3. **Alternative docs:**
   http://localhost:8000/redoc

## Step 6: Test Authentication

### Register a User
```bash
curl -X POST "http://localhost:8000/api/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "testpassword123",
    "full_name": "Test User"
  }'
```

### Login
```bash
curl -X POST "http://localhost:8000/api/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=test@example.com&password=testpassword123"
```

This will return a JWT token. Save it for authenticated requests.

## Step 7: Configure Frontend

Update the frontend to connect to the backend:

1. **Option 1: Environment Variable (Recommended)**
   Create `.env` in `CloudKraftFE`:
   ```env
   VITE_API_URL=http://localhost:8000
   ```

2. **Option 2: Update API Service**
   Edit `CloudKraftFE/src/services/api.ts`:
   ```typescript
   const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
   ```

## Step 8: Start Frontend

In a new terminal:
```bash
cd /Users/priyankajadhav/final-year-project/CloudKraftFE
npm install  # If not already done
npm run dev
```

Frontend will run on http://localhost:5173 (or the port Vite assigns)

## Step 9: Test Full Integration

1. **Open frontend:** http://localhost:5173
2. **Register/Login** through the UI
3. **Create a workflow:**
   - Go to Workflow Designer
   - Drag resources onto canvas
   - Configure resources
   - Click "Save" to save workflow
   - Click "Generate Code" to generate Terraform
   - View generated code in Code Viewer
   - Click "Validate" to see validation results

## Troubleshooting

### Database Issues
- If you see database errors, delete `cloudkraft.db` and restart the server
- Or run: `alembic upgrade head`

### CORS Errors
- Make sure `CORS_ORIGINS` in `.env` includes your frontend URL
- Default includes: `http://localhost:5173,http://localhost:3000`

### Port Already in Use
- Change port: `uvicorn app.main:app --reload --port 8001`
- Update frontend API URL accordingly

### Import Errors
- Make sure virtual environment is activated
- Reinstall: `pip install -r requirements.txt`

## Next Steps

- **Production Setup:** Use PostgreSQL instead of SQLite
- **Security:** Use environment variables for all secrets
- **Deployment:** Set up proper CORS, rate limiting, and HTTPS
- **Testing:** Add unit tests for services and API endpoints

## API Endpoints Summary

- `GET /` - API info
- `GET /health` - Health check
- `GET /docs` - Swagger UI documentation
- `POST /api/auth/register` - Register user
- `POST /api/auth/login` - Login (get JWT)
- `POST /api/auth/aws-register` - Register with AWS credentials
- `GET /api/auth/me` - Get current user (requires auth)
- `GET /api/workflows` - List workflows (requires auth)
- `POST /api/workflows` - Create workflow (requires auth)
- `POST /api/codegen/generate` - Generate Terraform (requires auth)
- `POST /api/validation/validate` - Validate Terraform (requires auth)

All endpoints except `/`, `/health`, `/docs`, and `/api/auth/register` require JWT authentication.

