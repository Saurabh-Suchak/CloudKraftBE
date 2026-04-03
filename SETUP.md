# CloudKraft Backend Setup Guide

## Quick Start

1. **Install dependencies:**
```bash
cd CloudKraftBE
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

2. **Configure environment:**
```bash
cp .env.example .env
# Edit .env and set your SECRET_KEY and ENCRYPTION_KEY
```

3. **Initialize database:**
```bash
# The database will be created automatically on first run
# Or run migrations manually:
alembic revision --autogenerate -m "Initial migration"
alembic upgrade head
```

4. **Run the server:**
```bash
uvicorn app.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`
API documentation: `http://localhost:8000/docs`

## Environment Variables

- `DATABASE_URL`: Database connection string (default: sqlite:///./cloudkraft.db)
- `SECRET_KEY`: Secret key for JWT token signing (change in production!)
- `ALGORITHM`: JWT algorithm (default: HS256)
- `ACCESS_TOKEN_EXPIRE_MINUTES`: Token expiration time (default: 30)
- `CORS_ORIGINS`: Comma-separated list of allowed origins
- `ENCRYPTION_KEY`: Key for encrypting AWS credentials (change in production!)

## API Endpoints

### Authentication
- `POST /api/auth/register` - Register new user
- `POST /api/auth/login` - Login (returns JWT)
- `POST /api/auth/aws-register` - Register with AWS credentials
- `GET /api/auth/me` - Get current user (requires auth)

### Workflows
- `GET /api/workflows` - List user's workflows
- `POST /api/workflows` - Create workflow
- `GET /api/workflows/{id}` - Get workflow
- `PUT /api/workflows/{id}` - Update workflow
- `DELETE /api/workflows/{id}` - Delete workflow

### Code Generation
- `POST /api/codegen/generate` - Generate Terraform from workflow

### Validation
- `POST /api/validation/validate` - Validate Terraform code

## Frontend Integration

The frontend should be configured to point to the backend API. Set the environment variable:
```
VITE_API_URL=http://localhost:8000
```

Or update `src/services/api.ts` to change the default API URL.

