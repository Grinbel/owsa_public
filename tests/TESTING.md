# Testing Guide - Test Without Full Waldur Stack

---

## The Problem Identified

Testing with the full Waldur stack is **complicated**:

```
ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
â  Full E2E Testing (COMPLICATED! ð±)                          â
ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ¤
â  Waldur UI â Waldur Backend â PostgreSQL â RabbitMQ â       â
â  waldur-site-agent â Your Plugin â OpenStack Keystone       â
â                                                              â
â  Problems:                                                   â
â  - Takes 5-10 minutes to start everything                   â
â  - Hard to debug                                             â
â  - Cannot test edge cases easily                            â
â  - Expensive (requires full Kubernetes cluster)             â
â  - Slow feedback loop                                        â
ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
```

## The Solution: Testing Pyramid ðï¸

**Use 3 levels of tests** - each level serves a different purpose:

```
                    /\
                   /  \
                  / E2E \ â Few tests, full stack
                 /  Tests \
                /ââââââââââ\
               /Integration \ â Some tests, real OpenStack
              /   Tests      \
             /ââââââââââââââââ\
            /   Unit Tests     \ â Many tests, all mocked
           /____________________\

         Fast âââââââââââââââââââ Slow
         Many âââââââââââââââââââ Few
         Cheap ââââââââââââââââââ Expensive
```

---

## Level 1: Unit Tests (70% of your tests)

### What Are They?

**Mock everything** - test individual functions in isolation.

### Why Use Them?

- â¡ **Super fast** (milliseconds)
- ð§ **Easy to write**
- ð¯ **Test edge cases** easily
- ð» **Run on your laptop** without any infrastructure
- ð **Quick feedback** loop

### What to Mock?

- Mock OpenStack Keystone (no real API calls)
- Mock Waldur resources
- Mock network calls

### Example: Test `ping()` Method

```python
# tests/test_openstack_client_unit.py

def test_ping_success(client, mock_keystone):
    """Test ping returns True when token obtained."""
    # Arrange: Set up the mock
    mock_keystone.get_token.return_value = "fake-token"

    # Act: Call the method
    result = client.ping()

    # Assert: Verify the result
    assert result is True
```

**What's happening:**
1. We create a **fake token** (no real OpenStack needed!)
2. We call `ping()`
3. We verify it returns `True`

**Run it:**
```bash
# Install pytest first
source .venv/bin/activate
pip install pytest pytest-mock

# Run unit tests (SUPER FAST!)
pytest tests/test_openstack_client_unit.py -v
```

**Output:**
```
tests/test_openstack_client_unit.py::TestHealthChecks::test_ping_success PASSED
tests/test_openstack_client_unit.py::TestHealthChecks::test_ping_failure PASSED
... 20 tests in 0.5 seconds â
```

---

## Level 2: Integration Tests (20% of your tests)

### What Are They?

**Use real OpenStack** but **mock Waldur events**.

### Why Use Them?

- ð **Test real OpenStack** integration
- ð« **No Waldur needed** - just mock the events
- ð­ **Simulate Waldur events** manually
- â¡ **Faster than E2E** (no full stack)

### What to Mock?

- Mock Waldur resources (create fake `waldur_resource` objects)
- Mock Waldur events
- Use REAL OpenStack Keystone

### Example: Test Resource Creation

```python
# tests/test_backend_integration.py

def test_create_and_delete_project(backend):
    """Test creating project WITHOUT Waldur."""

    # 1. Create a FAKE waldur_resource (what Waldur would send)
    fake_resource = Mock()
    fake_resource.uuid = str(uuid4())
    fake_resource.name = "Test Project"
    fake_resource.backend_id = None  # New resource

    # 2. Create the resource (calls REAL OpenStack!)
    backend_id = backend._create_resource_in_backend(fake_resource)

    # 3. Verify it was created in REAL OpenStack
    assert backend.client.get_project(backend_id) is not None

    # 4. Cleanup
    fake_resource.backend_id = backend_id
    backend.delete_resource(fake_resource)
```

**What's happening:**
1. We create a **fake Waldur resource** (no Waldur needed!)
2. We call `_create_resource_in_backend()` which creates a **REAL OpenStack project**
3. We verify it exists in **real OpenStack**
4. We clean up

**Run it:**
```bash
# Load OpenStack credentials
source test.env

# Run integration tests (uses real OpenStack)
pytest tests/test_backend_integration.py -v -s
```

**Output:**
```
tests/test_backend_integration.py::test_create_and_delete_project PASSED
ð¦ Created real OpenStack project!
â Verified in Keystone
ðï¸  Cleaned up
... 8 tests in 15 seconds â
```

---

## Level 3: End-to-End Tests (10% of your tests)

### What Are They?

**Full stack** - Waldur + RabbitMQ + Agent + OpenStack.

### Why Use Them?

- ð¯ **Test complete workflow**
- â **Final validation** before production
- ð **Catch integration issues**

### When to Use?

- Before deploying to production
- Weekly regression testing
- NOT for everyday development!

### Example: Full Workflow

```bash
# 1. Start full stack
kubectl port-forward svc/waldur-release-rabbitmq 61613:61613

# 2. Run agent in event mode
waldur-site-agent run --mode event_process --config test-config-final.yaml

# 3. Manually test in Waldur UI:
#    - Create resource order
#    - Add user to team
#    - Verify in OpenStack Keystone
```

**Time:** 10-30 minutes per test ð´

---

## Testing Strategy: When to Use Each Level

| Scenario | Test Level | Why |
|----------|-----------|-----|
| Writing new method | Unit Test | Fast feedback, test edge cases |
| Testing OpenStack integration | Integration Test | Verify real API calls work |
| Testing event handling | Integration Test | Mock events, use real OpenStack |
| Bug fix | Unit Test | Reproduce bug quickly |
| Before deployment | E2E Test | Final validation |
| Testing edge cases (missing UUID, etc.) | Unit Test | Easy to simulate errors |
| Testing user lifecycle | Integration Test | Mock Waldur events |

---

## Practical Example: Testing a New Feature

**Scenario:** You added a new method `get_project_metadata()`

### Step 1: Write Unit Test (2 minutes)

```python
def test_get_project_metadata_success(client, mock_keystone):
    """Test get_project_metadata returns correct data."""
    # Mock project
    fake_project = Mock()
    fake_project.id = "123"
    fake_project.name = "test"
    fake_project.enabled = True
    mock_keystone.get_project.return_value = fake_project

    # Call method
    metadata = client.get_project_metadata("test")

    # Verify
    assert metadata["project_id"] == "123"
    assert metadata["enabled"] is True
```

**Run:** `pytest tests/test_openstack_client_unit.py::test_get_project_metadata_success -v`

### Step 2: Write Integration Test (5 minutes)

```python
def test_get_metadata_from_real_project(backend):
    """Test getting metadata from real OpenStack project."""
    # Create real project
    fake_resource = create_fake_waldur_resource()
    backend_id = backend._create_resource_in_backend(fake_resource)

    # Get metadata (from REAL OpenStack!)
    metadata = backend.get_resource_metadata(backend_id)

    # Verify
    assert metadata["project_name"] == backend_id
    assert "project_id" in metadata

    # Cleanup
    backend.delete_resource(fake_resource)
```

**Run:** `source test.env && pytest tests/test_backend_integration.py::test_get_metadata_from_real_project -v`

### Step 3: Manual E2E Test (10 minutes)

Only if integration tests pass!

---

## Running Tests

### Quick Reference

```bash
# 1. Install dependencies
source .venv/bin/activate
pip install pytest pytest-mock

# 2. Run unit tests (FAST - no infrastructure needed)
pytest tests/test_openstack_client_unit.py -v

# 3. Run integration tests (needs OpenStack)
source test.env  # Load credentials
pytest tests/test_backend_integration.py -v -s

# 4. Run all tests
pytest tests/ -v

# 5. Run specific test
pytest tests/test_openstack_client_unit.py::TestHealthChecks::test_ping_success -v

# 6. Run tests with output
pytest tests/ -v -s  # -s shows print statements
```

### CI/CD Pipeline

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - run: pip install pytest pytest-mock
      - run: pytest tests/test_openstack_client_unit.py -v

  integration-tests:
    runs-on: ubuntu-latest
    services:
      keystone:
        image: openstack/keystone
    steps:
      - uses: actions/checkout@v2
      - run: pytest tests/test_backend_integration.py -v
```

---

## Tips for Junior Developers

### 1. **Start with Unit Tests**

When learning testing, start with unit tests:
- They're fast
- Easy to understand
- Give quick feedback
- Don't require infrastructure

### 2. **Follow AAA Pattern**

```python
def test_example():
    # Arrange: Set up test data
    mock_data = create_mock()

    # Act: Call the method being tested
    result = method_under_test(mock_data)

    # Assert: Verify the result
    assert result == expected_value
```

### 3. **Test One Thing Per Test**

â **Bad:**
```python
def test_everything():
    # Tests 10 different things
    result = ping()
    assert result
    domain = get_domain()
    assert domain
    # ... (too much!)
```

â **Good:**
```python
def test_ping_success():
    # Tests ONE thing
    result = ping()
    assert result is True

def test_ping_failure():
    # Tests ONE error case
    mock.side_effect = Exception()
    result = ping()
    assert result is False
```

### 4. **Name Tests Clearly**

â **Good names:**
- `test_ping_returns_true_when_token_obtained`
- `test_create_project_raises_error_when_name_invalid`
- `test_get_domain_returns_none_when_not_found`

â **Bad names:**
- `test_1`
- `test_ping`
- `test_stuff`

### 5. **Don't Test Implementation Details**

â **Bad** (testing how it works):
```python
def test_ping_calls_get_token():
    client.ping()
    mock_keystone.get_token.assert_called_once()  # Testing internal call
```

â **Good** (testing what it does):
```python
def test_ping_returns_true_when_connected():
    result = client.ping()
    assert result is True  # Testing behavior
```

---

## Common Testing Mistakes to Avoid

### 1. **Testing Too Much in E2E**

â **Bad:**
```python
# 100 E2E tests - takes 2 hours to run!
```

â **Good:**
```python
# 70 unit tests (1 minute)
# 20 integration tests (10 minutes)
# 10 E2E tests (30 minutes)
```

### 2. **Not Cleaning Up**

â **Bad:**
```python
def test_create_project():
    project = create_project("test")
    assert project.id
    # Doesn't delete - leaves garbage in OpenStack!
```

â **Good:**
```python
def test_create_project():
    project = create_project("test")
    try:
        assert project.id
    finally:
        delete_project(project)  # Always cleanup!
```

### 3. **Forgetting to Source test.env**

```bash
# â Integration tests fail
pytest tests/test_backend_integration.py

# â Load credentials first
source test.env
pytest tests/test_backend_integration.py
```

---

## Summary: Your Testing Workflow

### During Development (Every 5 minutes)

```bash
# Write code â Write unit test â Run it
pytest tests/test_openstack_client_unit.py -v
# â Fast feedback!
```

### Before Commit (Every hour)

```bash
# Run all unit tests
pytest tests/test_openstack_client_unit.py -v

# Run integration tests
source test.env
pytest tests/test_backend_integration.py -v
```

### Before Deployment (Weekly)

```bash
# Run everything
pytest tests/ -v

# Manual E2E testing with real Waldur
./test-plugin.sh
waldur-site-agent run --mode event_process ...
# Test in Waldur UI
```

---

## Key Takeaways

1. â **You CAN test without full Waldur** - use mocks!
2. â **Unit tests are your friend** - fast and easy
3. â **Integration tests test OpenStack** - no Waldur needed
4. â **E2E tests are for final validation** - use sparingly
5. â **Testing pyramid: Many unit, some integration, few E2E**

---

## Next Steps

1. â Try running the unit tests:
   ```bash
   pytest tests/test_openstack_client_unit.py -v
   ```

2. â Try running one integration test:
   ```bash
   source test.env
   pytest tests/test_backend_integration.py::TestBackendHealthChecks::test_ping_with_real_keystone -v
   ```

3. â Write your first test for a new feature

4. â Learn pytest documentation: https://docs.pytest.org/

---

**Questions?** Check the test files for more examples!

- `tests/test_openstack_client_unit.py` - Unit test examples
- `tests/test_backend_integration.py` - Integration test examples

**Pro Tip:** When in doubt, write a unit test first! ð
