# TEG Layer MVP Makefile
# Common operations for development and testing

.PHONY: help install init-db migrate run test test-coverage clean docs lint format db-setup db-reset

# Default target
help:
	@echo "TEG Layer MVP - Available commands:"
	@echo "  make install       - Install dependencies with Poetry"
	@echo "  make db-setup     - Create database and run migrations"
	@echo "  make migrate      - Run database migrations"
	@echo "  make init-db      - Initialize database and fund treasury"
	@echo "  make run          - Run the service in development mode"
	@echo "  make test         - Run all tests"
	@echo "  make test-coverage - Run tests with coverage report"
	@echo "  make clean        - Clean up generated files"
	@echo "  make docs         - Open API documentation in browser"
	@echo "  make lint         - Run code linting"
	@echo "  make format       - Format code with black"

# Install dependencies
install:
	poetry install

# Set up database (create and migrate)
db-setup:
	@echo "Setting up PostgreSQL database..."
	@echo "Run these commands in psql:"
	@echo "  CREATE DATABASE teg_db;"
	@echo "  CREATE USER teg_user WITH PASSWORD 'teg_pass';"
	@echo "  GRANT ALL PRIVILEGES ON DATABASE teg_db TO teg_user;"
	@echo ""
	@echo "Then run: make migrate"

# Run database migrations
migrate:
	poetry run alembic upgrade head
	@echo "Database migrations completed"

# Initialize database and fund treasury
init-db: migrate
	poetry run python scripts/initialize_db.py
	@echo "Database initialized"
	poetry run python scripts/issue_initial_tokens.py did:theprotocol:teg_system_treasury 10000.0
	@echo "Treasury funded with 10,000 AVT"

# Run the service
run:
	poetry run uvicorn src.teg_core_service.main:app --reload --host 0.0.0.0 --port 8000

# Run the service with mTLS support
run-mtls:
	@echo "Starting TEG Core Service with mTLS support..."
	@echo "Ensure SPIFFE_ENDPOINT_SOCKET is set and SPIRE agent is running"
	poetry run python -m src.teg_core_service.main_mtls

# Register TEG Core Service with SPIRE
register-spire:
	@echo "Registering TEG Core Service with SPIRE..."
	docker exec agentvault-spire-server \
		/opt/spire/bin/spire-server entry create \
		-parentID spiffe://agentvault.com/spire-agent \
		-spiffeID spiffe://agentvault.com/service/teg-core \
		-selector unix:uid:1000 \
		-ttl 3600
	@echo "TEG Core Service registered with SPIFFE ID: spiffe://agentvault.com/service/teg-core"

# Run tests
test:
	poetry run pytest tests/ -v

# Run tests with coverage
test-coverage:
	poetry run pytest tests/ --cov=src --cov-report=html --cov-report=term

# Clean up
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache
	rm -rf htmlcov
	rm -rf .coverage
	rm -f teg_database.db

# Reset database (drops and recreates)
db-reset:
	@echo "⚠️  This will DROP the database! Press Ctrl+C to cancel..."
	@sleep 3
	poetry run alembic downgrade base
	poetry run alembic upgrade head
	@echo "Database reset complete"

# Open API docs
docs:
	@echo "Opening API documentation..."
	@python -m webbrowser http://localhost:8000/docs

# Lint code
lint:
	poetry run flake8 src/ tests/ --max-line-length=100 --ignore=E203,W503

# Format code
format:
	poetry run black src/ tests/ scripts/ --line-length=100

# Quick setup for new developers
setup: install migrate init-db
	@echo "Setup complete! Run 'make run' to start the service."

# Show migration history
db-history:
	poetry run alembic history

# Show current database version
db-current:
	poetry run alembic current

# Create new migration
db-revision:
	@read -p "Enter migration message: " msg; \
	poetry run alembic revision --autogenerate -m "$msg"

# Run specific test file
test-file:
	@read -p "Enter test file name (e.g., test_api_token): " file; \
	poetry run pytest tests/$$file.py -v

# Create test data
test-data:
	poetry run python scripts/issue_initial_tokens.py agent_test1 1000.0
	poetry run python scripts/issue_initial_tokens.py agent_test2 500.0
	poetry run python scripts/issue_initial_tokens.py agent_test3 100.0
	@echo "Test agents created with initial balances"

# Check service health
health:
	@curl -s http://localhost:8000/health | python -m json.tool

# View recent transactions
recent-txs:
	@echo "Recent transactions:"
	@poetry run python -c "from src.teg_core_service.database.db_session import engine; import pandas as pd; df = pd.read_sql('SELECT transaction_id, sender_agent_id, receiver_agent_id, amount, status, timestamp FROM teg_transactions ORDER BY timestamp DESC LIMIT 10', engine); print(df.to_string())"

# View agent balances
balances:
	@echo "Agent balances:"
	@poetry run python -c "from src.teg_core_service.database.db_session import engine; import pandas as pd; df = pd.read_sql('SELECT agent_id, token_balance, reputation_score FROM agent_teg_profiles', engine); print(df.to_string())"
