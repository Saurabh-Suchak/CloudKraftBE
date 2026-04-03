# CloudKraft Backend

Backend API for CloudKraft - A visual workflow designer for AWS infrastructure with Terraform code generation.

## Features

- JWT-based authentication
- Workflow management (CRUD operations)
- Terraform code generation from visual workflows
- Terraform code validation
- AWS credential management

## Quick Start

See [QUICKSTART.md](QUICKSTART.md) for detailed step-by-step instructions.

### Basic Setup

1. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure environment variables:
```bash
cp .env.example .env
# Edit .env and set SECRET_KEY and ENCRYPTION_KEY
# Generate secure keys: python -c "import secrets; print(secrets.token_urlsafe(32))"
```

4. Start the development server:
```bash
uvicorn app.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`

API documentation: `http://localhost:8000/docs`

**Note:** The database will be created automatically on first run. No manual migration needed for initial setup.

## Project Structure

```
app/
├── main.py              # FastAPI application
├── config.py            # Configuration
├── database.py          # Database connection
├── models/              # SQLAlchemy models
├── schemas/             # Pydantic schemas
├── api/                 # API routes
├── services/            # Business logic
└── utils/               # Utilities
```

