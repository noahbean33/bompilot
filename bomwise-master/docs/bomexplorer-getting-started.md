# BOMexplorer — Getting Started Guide

Environment setup and VS Code configuration for development on Linux Mint.

---

## Prerequisites

This guide assumes:
- Linux Mint (any recent release)
- VS Code already installed
- Docker already installed (from your Unraid work)
- Git installed (`git --version` to confirm)

Estimated time: 60–90 minutes end to end.

---

## Part 1: Environment Setup

### 1.1 Verify Docker and add Compose plugin

```bash
docker --version
docker compose version
```

If `docker compose` (no hyphen) is missing:

```bash
sudo apt-get install docker-compose-plugin
```

Add yourself to the docker group if you haven't already (avoids needing sudo for every docker command):

```bash
sudo usermod -aG docker $USER
newgrp docker
```

---

### 1.2 Install nvm and Node.js

nvm lets you manage Node versions without polluting your system.

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
```

Close and reopen your terminal, then:

```bash
nvm install 20
nvm use 20
nvm alias default 20
node --version    # should show v20.x.x
npm --version
```

---

### 1.3 Install uv (Python package manager)

uv replaces pip and venv. Faster, produces a proper lockfile, handles virtual environments cleanly.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Close and reopen your terminal, then:

```bash
uv --version
```

---

### 1.4 Install Claude Code

```bash
npm install -g @anthropic-ai/claude-code
```

Verify:

```bash
claude --version
```

You will authenticate Claude Code when you first run it inside a project. It opens a browser window for Anthropic login. Your existing claude.ai account works.

---

### 1.5 Create the project directory structure

```bash
mkdir -p ~/Documents/code_projects/bomexplorer
cd ~/Documents/code_projects/bomexplorer
mkdir backend frontend
git init
```

Create a root `.gitignore`:

```bash
cat > .gitignore << 'EOF'
# Python
__pycache__/
*.py[cod]
.venv/
*.egg-info/
dist/
.env

# Node
node_modules/
dist/
.next/

# Environment files
.env
.env.local
.env.*.local

# Docker
*.log

# OS
.DS_Store
.idea/
EOF
```

---

### 1.6 Set up the Python backend environment

```bash
cd ~/Documents/code_projects/bomexplorer/backend
uv init
uv python install 3.12
uv python pin 3.12
```

Install the core backend dependencies:

```bash
uv add fastapi uvicorn[standard] sqlalchemy alembic psycopg2-binary \
       python-jose[cryptography] passlib[bcrypt] python-multipart \
       celery redis httpx pydantic-settings python-dotenv openpyxl \
       ruff pytest pytest-asyncio
```

This creates a `pyproject.toml` and a `uv.lock` file. Both go into git.

Create the initial backend structure:

```bash
mkdir -p app/{api,core,db,models,schemas,services,workers}
touch app/__init__.py
touch app/main.py
touch app/api/__init__.py
touch app/core/__init__.py
touch app/db/__init__.py
touch app/models/__init__.py
touch app/schemas/__init__.py
touch app/services/__init__.py
touch app/workers/__init__.py
```

Create a `.env` file for local development (never commit this):

```bash
cat > .env << 'EOF'
DATABASE_URL=postgresql://bomexplorer:bomexplorer@localhost:5432/bomexplorer
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=replace-this-with-a-random-string-before-production
NEXAR_CLIENT_ID=
NEXAR_CLIENT_SECRET=
DIGIKEY_CLIENT_ID=
DIGIKEY_CLIENT_SECRET=
MOUSER_API_KEY=
PADDLE_WEBHOOK_SECRET=
RESEND_API_KEY=
ENVIRONMENT=development
EOF
```

---

### 1.7 Set up the React frontend environment
```bash
cd ~/Documents/code_projects/bomexplorer/frontend
npm create vite@latest . -- --template react-ts
```

When prompted, confirm overwriting the current directory.

Install dependencies:
```bash
npm install
npm install @tanstack/react-query zustand react-router-dom axios
npm install -D tailwindcss@3 postcss autoprefixer @types/node
npx tailwindcss init -p
```

> **Note:** Pin to `tailwindcss@3` explicitly. shadcn/ui requires v3; v4 uses a different configuration model incompatible with this setup.

Install shadcn/ui:
```bash
npx shadcn@latest init
```

When prompted:
- Style: Default
- Base colour: Slate
- CSS variables: Yes

Add core shadcn components:
```bash
npx shadcn@latest add button input label card table badge dialog
npx shadcn@latest add dropdown-menu select toast progress separator
```
---

### 1.8 Set up local Docker services

Create a `docker-compose.dev.yml` in the project root (not in backend or frontend):

```bash
cd ~/Documents/code_projects/bomexplorer
cat > docker-compose.dev.yml << 'EOF'
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: bomexplorer
      POSTGRES_PASSWORD: bomexplorer
      POSTGRES_DB: bomexplorer
    ports:
      - "5432:5432"
    volumes:
      - bomexplorer_postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

volumes:
  bomexplorer_postgres_data:
EOF
```

Start the services:

```bash
docker compose -f docker-compose.dev.yml up -d
```

Verify both are running:

```bash
docker compose -f docker-compose.dev.yml ps
```

You should see postgres and redis both showing as running. These two containers are all you need for local development. Start them at the beginning of each dev session, stop them when done.

---

### 1.9 Initialise Alembic for database migrations

```bash
cd ~/Documents/code_projects/bomexplorer/backend
uv run alembic init alembic
```

Edit `alembic.ini` — find the `sqlalchemy.url` line and comment it out:

```ini
# sqlalchemy.url = driver://user:pass@localhost/dbname
```

Edit `alembic/env.py` — replace the top section to load the URL from your `.env`:

```python
from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context
from dotenv import load_dotenv
import os

load_dotenv()

config = context.config
config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None

def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

Verify Alembic connects:

```bash
uv run alembic current
```

No error means it connected to PostgreSQL successfully.

---

## Part 2: VS Code Setup

### 2.1 Extensions to install

Open VS Code, go to Extensions (Ctrl+Shift+X), and install:

**Python development:**
- `ms-python.python` — Python language support
- `ms-python.pylance` — type checking and IntelliSense
- `charliermarsh.ruff` — linting and formatting (replaces flake8, black, isort)

**Frontend development:**
- `dbaeumer.vscode-eslint` — ESLint integration
- `esbenp.prettier-vscode` — code formatting
- `bradlc.vscode-tailwindcss` — Tailwind class autocomplete
- `formulahendry.auto-rename-tag` — renames paired HTML/JSX tags

**Database:**
- `cweijan.vscode-database-client2` — connect to PostgreSQL directly in VS Code (optional but useful for inspecting data during development)

**API testing:**
- `humao.rest-client` — test API endpoints from `.http` files without leaving VS Code

**General:**
- `eamodio.gitlens` — enhanced git history and blame
- `usernamehw.errorlens` — shows errors inline rather than just in the Problems panel
- `gruntfuggly.todo-tree` — surfaces TODO comments across the codebase

---

### 2.2 Workspace settings

Open the project root in VS Code:

```bash
code ~/Documents/code_projects/bomexplorer
```

Create `.vscode/settings.json` in the project root:

```json
{
  "editor.formatOnSave": true,
  "editor.defaultFormatter": "esbenp.prettier-vscode",
  "editor.rulers": [88],
  "editor.tabSize": 2,

  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.tabSize": 4
  },

  "python.defaultInterpreterPath": "${workspaceFolder}/backend/.venv/bin/python",

  "ruff.enable": true,
  "ruff.organizeImports": true,

  "eslint.workingDirectories": ["frontend"],

  "tailwindCSS.includeLanguages": {
    "typescript": "javascript",
    "typescriptreact": "javascript"
  },

  "files.exclude": {
    "**/__pycache__": true,
    "**/*.pyc": true,
    "**/node_modules": true,
    "**/.venv": true
  },

  "search.exclude": {
    "**/node_modules": true,
    "**/.venv": true,
    "**/dist": true
  },

  "todo-tree.general.tags": ["TODO", "FIXME", "HACK", "NOTE"],

  "terminal.integrated.env.linux": {
    "PYTHONPATH": "${workspaceFolder}/backend"
  }
}
```

---

### 2.3 Ruff configuration

Create `backend/pyproject.toml` additions for Ruff (add this to the existing pyproject.toml that uv created):

```toml
[tool.ruff]
line-length = 88
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B"]
ignore = ["E501"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

---

### 2.4 Prettier configuration

Create `frontend/.prettierrc` :

```json
{
  "semi": false,
  "singleQuote": true,
  "tabWidth": 2,
  "trailingComma": "es5",
  "printWidth": 88
}
```

---

### 2.5 Terminal layout for daily development

VS Code's split terminal panel is your working environment. Recommended layout:

Open the terminal panel (Ctrl+`) and create four terminals:

| Terminal | Purpose | Starting command |
|---|---|---|
| **backend** | FastAPI dev server | `cd backend && uv run uvicorn app.main:app --reload` |
| **worker** | Celery worker | `cd backend && uv run celery -A app.workers worker --loglevel=info` |
| **frontend** | Vite dev server | `cd frontend && npm run dev` |
| **claude** | Claude Code | `claude` |

You won't need all four running simultaneously at the start of the project. In the early stages, backend and claude are enough.

---

### 2.6 Configure the REST Client extension

Create a `requests/` directory in the project root for `.http` files. These let you test API endpoints directly in VS Code without switching to Postman or a browser.

Create `requests/auth.http` as your first test file:

```http
@baseUrl = http://localhost:8000

### Register a new user
POST {{baseUrl}}/auth/register
Content-Type: application/json

{
  "email": "test@example.com",
  "password": "testpassword123"
}

### Login
POST {{baseUrl}}/auth/login
Content-Type: application/json

{
  "email": "test@example.com",
  "password": "testpassword123"
}
```

Click "Send Request" above any block to fire it. Responses appear in a split pane. As you build each API module, add a corresponding `.http` file here.

---

### 2.7 Activate the Python virtual environment in VS Code

After running `uv add` in the backend directory, uv creates a `.venv` folder. Tell VS Code to use it:

Press Ctrl+Shift+P → "Python: Select Interpreter" → choose the one pointing to `backend/.venv/bin/python`.

Pylance will now provide accurate type checking and autocomplete for all your installed packages.

---

## Part 3: Verify the Setup

Run through this checklist before starting development:

```bash
# Docker services running
docker compose -f docker-compose.dev.yml ps

# Python environment works
cd ~/Documents/code_projects/bomexplorer/backend
uv run python -c "import fastapi; print(fastapi.__version__)"

# Alembic connects to PostgreSQL
uv run alembic current

# Node and npm work
cd ~/Documents/code_projects/bomexplorer/frontend
node --version
npm --version

# Frontend dependencies installed
ls node_modules | head -5

# Claude Code authenticated
claude --version
```

If all of these pass without errors, the environment is ready.

---

## Part 4: Daily Workflow

**Start of session:**

```bash
# Start Docker services
cd ~/Documents/code_projects/bomexplorer
docker compose -f docker-compose.dev.yml up -d

# Open VS Code
code .
```

In VS Code, open your four terminals and start whichever servers you need for the session.

**End of session:**

```bash
docker compose -f docker-compose.dev.yml stop
```

The volume data persists between sessions. Your database is not lost when you stop the containers.

**Running Claude Code:**

Always run `claude` from the directory relevant to what you're building:

```bash
# For backend work
cd ~/Documents/code_projects/bomexplorer/backend
claude

# For frontend work
cd ~/Documents/code_projects/bomexplorer/frontend
claude
```

Claude Code reads the files in the current directory and its subdirectories. Starting from the right directory ensures it has full context for the task.

---

## Reference: Useful Commands

```bash
# Apply a new database migration
uv run alembic upgrade head

# Create a new migration after changing models
uv run alembic revision --autogenerate -m "add users table"

# Run backend tests
uv run pytest

# Add a new Python package
uv add package-name

# Add a new shadcn component
npx shadcn@latest add component-name

# Build the frontend for production
npm run build

# Check Python code quality
uv run ruff check .
uv run ruff format .
```