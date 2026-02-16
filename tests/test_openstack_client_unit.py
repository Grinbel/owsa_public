"""
Unit tests for OpenStackClient - Testing WITHOUT real OpenStack or Waldur.

These tests are FAST because they mock everything.
You can run these tests on your laptop without any infrastructure!

Run with: pytest tests/test_openstack_client_unit.py -v
"""

import pytest
from unittest.mock import MagicMock, Mock
from waldur_site_agent_openstack.openstack_client import OpenStackClient
from waldur_site_agent_openstack.keystone_client import KeystoneClientError


@pytest.fixture
def mock_keystone():
    """Create a mock KeystoneClient for testing."""
    mock = MagicMock()
    mock.config.domain_name = "default"
    mock.config.default_role = "member"
    return mock


@pytest.fixture
def client(mock_keystone):
    """Create OpenStackClient with mocked KeystoneClient."""
    return OpenStackClient(mock_keystone)


class TestHealthChecks:
    """Test health check methods without real Keystone."""

    def test_ping_success(self, client, mock_keystone):
        """Test ping returns True when token obtained."""
        # Arrange: Mock successful token retrieval
        mock_keystone.get_token.return_value = "fake-token-12345"

        # Act: Call ping
        result = client.ping()

        # Assert: Should return True
        assert result is True
        mock_keystone.get_token.assert_called_once()

    def test_ping_failure_no_token(self, client, mock_keystone):
        """Test ping returns False when no token."""
        # Arrange: Mock no token
        mock_keystone.get_token.return_value = None

        # Act: Call ping
        result = client.ping()

        # Assert: Should return False
        assert result is False

    def test_ping_failure_exception(self, client, mock_keystone):
        """Test ping returns False when exception occurs."""
        # Arrange: Mock exception
        mock_keystone.get_token.side_effect = Exception("Network error")

        # Act: Call ping
        result = client.ping()

        # Assert: Should return False (not raise exception)
        assert result is False

    def test_get_domain_found(self, client, mock_keystone):
        """Test get_domain returns domain when found."""
        # Arrange: Mock domain object
        fake_domain = Mock()
        fake_domain.id = "domain-123"
        fake_domain.name = "default"
        mock_keystone.get_domain.return_value = fake_domain

        # Act: Call get_domain
        domain = client.get_domain("default")

        # Assert: Should return the domain
        assert domain == fake_domain
        assert domain.name == "default"
        mock_keystone.get_domain.assert_called_once_with("default")

    def test_get_domain_not_found(self, client, mock_keystone):
        """Test get_domain returns None when not found."""
        # Arrange: Mock domain not found
        mock_keystone.get_domain.return_value = None

        # Act: Call get_domain
        domain = client.get_domain("nonexistent")

        # Assert: Should return None
        assert domain is None

    def test_get_role_found(self, client, mock_keystone):
        """Test get_role returns role when found."""
        # Arrange: Mock role object
        fake_role = Mock()
        fake_role.id = "role-456"
        fake_role.name = "member"
        mock_keystone.get_role.return_value = fake_role

        # Act: Call get_role
        role = client.get_role("member")

        # Assert: Should return the role
        assert role == fake_role
        assert role.name == "member"


class TestProjectManagement:
    """Test project management methods without real Keystone."""

    def test_get_project_found(self, client, mock_keystone):
        """Test get_project returns project when found."""
        # Arrange: Mock project object
        fake_project = Mock()
        fake_project.id = "proj-789"
        fake_project.name = "test-project"
        mock_keystone.get_project.return_value = fake_project

        # Act: Call get_project
        project = client.get_project("test-project")

        # Assert: Should return the project
        assert project == fake_project
        assert project.name == "test-project"

    def test_create_project_success(self, client, mock_keystone):
        """Test create_project creates project successfully."""
        # Arrange: Mock created project
        fake_project = Mock()
        fake_project.id = "new-proj-123"
        fake_project.name = "new-project"
        mock_keystone.create_project.return_value = fake_project

        # Act: Call create_project
        project = client.create_project("new-project", "Test description")

        # Assert: Should create and return project
        assert project == fake_project
        mock_keystone.create_project.assert_called_once_with(
            project_name="new-project",
            description="Test description"
        )

    def test_create_project_failure(self, client, mock_keystone):
        """Test create_project raises error on failure."""
        # Arrange: Mock creation failure
        mock_keystone.create_project.side_effect = Exception("Keystone error")

        # Act & Assert: Should raise KeystoneClientError
        with pytest.raises(KeystoneClientError) as exc_info:
            client.create_project("bad-project", "")

        assert "Failed to create project" in str(exc_info.value)

    def test_disable_project_success(self, client, mock_keystone):
        """Test disable_project succeeds."""
        # Arrange: Mock successful disable
        mock_keystone.disable_project.return_value = None

        # Act: Call disable_project
        result = client.disable_project("test-project")

        # Assert: Should return True
        assert result is True
        mock_keystone.disable_project.assert_called_once_with("test-project")

    def test_disable_project_failure(self, client, mock_keystone):
        """Test disable_project returns False on error."""
        # Arrange: Mock failure
        mock_keystone.disable_project.side_effect = Exception("Cannot disable")

        # Act: Call disable_project
        result = client.disable_project("test-project")

        # Assert: Should return False (not raise exception)
        assert result is False

    def test_enable_project_success(self, client, mock_keystone):
        """Test enable_project succeeds."""
        # Arrange: Mock successful enable
        mock_keystone.enable_project.return_value = None

        # Act: Call enable_project
        result = client.enable_project("test-project")

        # Assert: Should return True
        assert result is True

    def test_get_project_metadata_success(self, client, mock_keystone):
        """Test get_project_metadata returns correct metadata."""
        # Arrange: Mock project with metadata
        fake_project = Mock()
        fake_project.id = "proj-123"
        fake_project.name = "test-project"
        fake_project.domain_id = "default"
        fake_project.enabled = True
        fake_project.description = "Test description"
        mock_keystone.get_project.return_value = fake_project

        # Act: Call get_project_metadata
        metadata = client.get_project_metadata("test-project")

        # Assert: Should return correct metadata
        assert metadata == {
            "project_id": "proj-123",
            "project_name": "test-project",
            "domain": "default",
            "enabled": True,
            "description": "Test description",
        }

    def test_get_project_metadata_not_found(self, client, mock_keystone):
        """Test get_project_metadata returns empty dict when not found."""
        # Arrange: Mock project not found
        mock_keystone.get_project.return_value = None

        # Act: Call get_project_metadata
        metadata = client.get_project_metadata("nonexistent")

        # Assert: Should return empty dict
        assert metadata == {}


class TestUserManagement:
    """Test user management methods without real Keystone."""

    def test_list_users_success(self, client, mock_keystone):
        """Test list_users returns users from domain."""
        # Arrange: Mock domain and users
        fake_domain = Mock()
        fake_domain.id = "domain-123"
        mock_keystone.get_domain.return_value = fake_domain

        fake_user1 = Mock()
        fake_user1.name = "user1"
        fake_user1.email = "user1@example.com"
        fake_user2 = Mock()
        fake_user2.name = "user2"
        fake_user2.email = "user2@example.com"
        mock_keystone.keystone.users.list.return_value = [fake_user1, fake_user2]

        # Act: Call list_users
        users = client.list_users("default")

        # Assert: Should return list of users
        assert len(users) == 2
        assert users[0].name == "user1"
        assert users[1].name == "user2"
        mock_keystone.keystone.users.list.assert_called_once_with(domain=fake_domain)

    def test_list_users_domain_not_found(self, client, mock_keystone):
        """Test list_users returns empty list when domain not found."""
        # Arrange: Mock domain not found
        mock_keystone.get_domain.return_value = None

        # Act: Call list_users
        users = client.list_users("nonexistent")

        # Assert: Should return empty list
        assert users == []

    def test_list_users_uses_default_domain(self, client, mock_keystone):
        """Test list_users uses default domain when none specified."""
        # Arrange: Mock domain
        fake_domain = Mock()
        mock_keystone.get_domain.return_value = fake_domain
        mock_keystone.keystone.users.list.return_value = []

        # Act: Call list_users without domain (uses default)
        client.list_users()

        # Assert: Should use default domain from config
        mock_keystone.get_domain.assert_called_once_with("default")


class TestLogging:
    """Test that methods log with correct format."""

    def test_ping_logs_function_name(self, client, mock_keystone, caplog):
        """Test ping logs with [PING] prefix."""
        mock_keystone.get_token.return_value = "token"

        client.ping()

        # Check logs contain [PING] prefix
        assert any("[PING]" in record.message for record in caplog.records)

    def test_create_project_logs_parameters(self, client, mock_keystone, caplog):
        """Test create_project logs parameters."""
        fake_project = Mock()
        fake_project.id = "123"
        fake_project.name = "test"
        mock_keystone.create_project.return_value = fake_project

        client.create_project("test-project", "Test description")

        # Check logs contain function name and parameters
        log_messages = " ".join(record.message for record in caplog.records)
        assert "[CREATE_PROJECT]" in log_messages
        assert "test-project" in log_messages
        assert "Test description" in log_messages


if __name__ == "__main__":
    # Run tests with: python tests/test_openstack_client_unit.py
    pytest.main([__file__, "-v", "--tb=short"])
