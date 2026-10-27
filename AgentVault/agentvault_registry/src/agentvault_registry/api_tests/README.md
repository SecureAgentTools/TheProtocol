# API Test Suite - Modular Architecture

## Quick Start Guide

### Overview
The API test suite has been modularized to solve context overflow issues and enable rapid, focused testing of specific categories.

**Key Benefits:**
- ✅ No more "out of context" errors
- ✅ Test single categories in <5 seconds
- ✅ Parallel execution support
- ✅ Smart auth token retry
- ✅ Comprehensive error analysis

### Installation
No additional installation needed - uses existing dependencies.

### Basic Usage

#### 1. Test a Single Category
```bash
# Test TEG endpoints (highest priority)
python -m agentvault_registry.api_tests.runner -c teg

# Test Auth endpoints
python -m agentvault_registry.api_tests.runner -c auth

# With tokens
python -m agentvault_registry.api_tests.runner -c teg --dev-token YOUR_TOKEN --agent-token YOUR_AGENT_TOKEN
```

#### 2. Test Priority Endpoints Only
```bash
# Quick validation - tests only the most important endpoints
python -m agentvault_registry.api_tests.runner -c teg --priority
```

#### 3. Test Multiple Categories
```bash
# Test auth and teg
python -m agentvault_registry.api_tests.runner -c auth -c teg

# Test in parallel
python -m agentvault_registry.api_tests.runner -c auth -c teg --parallel
```

#### 4. Test All Categories
```bash
# Sequential (respects dependencies)
python -m agentvault_registry.api_tests.runner --all

# Parallel execution
python -m agentvault_registry.api_tests.runner --all --parallel
```

#### 5. Save Results
```bash
# Save to specific file
python -m agentvault_registry.api_tests.runner -c teg --output teg_results.json

# Auto-named with timestamp
python -m agentvault_registry.api_tests.runner --all --output
```

### Validation Script
Run the validation script to ensure everything is working:
```bash
cd D:\Agentvault2\AgentVault\agentvault_registry\src
python agentvault_registry/api_tests/validate_modular.py
```

### Available Categories
Currently implemented:
- **teg** - the ledger service (HIGH PRIORITY - validation errors)
- **auth** - Authentication (FOUNDATIONAL - required by others)

Coming soon:
- agents, locks, governance, federation, admin, etc.

### Advanced Features

#### TEG Diagnostics
The TEG module includes special diagnostics:
```python
from agentvault_registry.api_tests.categories.teg import TestTEG

tester = TestTEG()
await tester.setup()
diagnostics = await tester.diagnose_validation_errors(dev_token, agent_token)
print(diagnostics['recommendations'])
```

#### Auth Token Harvesting
The Auth module can obtain tokens for use by other tests:
```python
from agentvault_registry.api_tests.categories.auth import TestAuth

auth_tester = TestAuth()
await auth_tester.test_all()
tokens = auth_tester.get_obtained_tokens()
# Use tokens['developer'] and tokens['agent'] for other tests
```

### Creating New Category Modules

1. Copy the template:
```bash
cp api_tests/categories/_template.py api_tests/categories/agents/test_agents.py
```

2. Customize:
- Set `CATEGORY_NAME = "agents"`
- Define `PRIORITY_ENDPOINTS`
- Implement category-specific test methods

3. Test:
```bash
python -m agentvault_registry.api_tests.runner -c agents
```

### Troubleshooting

#### "Module not found" Error
Ensure you're in the correct directory:
```bash
cd D:\Agentvault2\AgentVault\agentvault_registry\src
```

#### Auth Failures
1. First run auth tests to get tokens:
```bash
python -m agentvault_registry.api_tests.runner -c auth
```

2. Use obtained tokens for other categories:
```bash
python -m agentvault_registry.api_tests.runner -c teg --dev-token TOKEN --agent-token TOKEN
```

#### Rate Limiting
Use `--priority` flag to test fewer endpoints:
```bash
python -m agentvault_registry.api_tests.runner -c teg --priority
```

### CLI Options
```
--category, -c       Test specific category (can be used multiple times)
--all, -a           Test all categories
--parallel, -p      Run tests in parallel
--priority          Run only priority endpoints
--dev-token         Developer token for authentication
--agent-token       Agent token for authentication
--base-url          Base URL for API (default: http://localhost:8710)
--output, -o        Output file for results
```

### Architecture
```
api_tests/
├── __init__.py              # Package init
├── base.py                  # Core test functionality
├── auth_manager.py          # Auth handling
├── endpoints_registry.py    # Endpoint definitions
├── request_bodies.py        # Request templates
├── test_results_analyzer.py # Results analysis
├── runner.py               # Test orchestration
├── legacy_compat.py        # Backward compatibility
├── validate_modular.py     # Validation script
└── categories/
    ├── _template.py        # Category template
    ├── teg/               # TEG tests
    │   └── test_teg.py
    └── auth/              # Auth tests
        └── test_auth.py
```

### Next Steps
1. Run validation script
2. Test TEG category (highest priority)
3. Test Auth category (foundational)
4. Add more categories as needed

---

**Status**: Core infrastructure complete and ready for use!
**Contact**: See session logs in D:\Agentvault2\SESSION_LOG_TEST_MODULARIZATION_2025-01-28.md
