"""
Integration tests for OpenStackBackend - Testing WITH real OpenStack, WITHOUT Waldur.

These tests use REAL OpenStack Keystone but MOCK Waldur events.
This lets you test OpenStack integration without the full Waldur stack!

Requirements:
- OpenStack Keystone running (use test.env credentials)
- pytest and pytest-env installed

Run with: pytest tests/test_backend_integration.py -v
"""

import pytest
import os
from unittest.mock import Mock, MagicMock
from uuid import uuid4

from waldur_site_agent_openstack.backends import OpenStackBackend
from waldur_site_agent_openstack.config import OpenStackConfig
from waldur_site_agent_openstack.keystone_client import KeystoneClient
from waldur_site_agent_openstack.openstack_client import OpenStackClient


# Skip all tests if OpenStack credentials not available
pytestmark = pytest.mark.skipif(
    not os.getenv("OS_AUTH_URL"),
    reason="OpenStack credentials not available (source test.env first)"
)


@pytest.fixture(scope="module")
def backend_settings():
    """Load backend settings from environment variables."""
    return {
        "auth_url": os.getenv("OS_AUTH_URL"),
        "username": os.getenv("OS_USERNAME"),
        "password": os.getenv("OS_PASSWORD"),
        "project_name": os.getenv("OS_PROJECT_NAME"),
        "domain_name": os.getenv("OS_USER_DOMAIN_NAME", "default"),
        "default_role": os.getenv("OS_DEFAULT_ROLE", "member"),
    }


@pytest.fixture
def backend(backend_settings):
    """Create OpenStackBackend with real OpenStack connection."""
    backend = OpenStackBackend(backend_settings, backend_components={})
    yield backend
    # Cleanup happens in individual tests


def create_fake_waldur_resource(uuid_str=None, name=None, backend_id=None):
    """
    Create a fake waldur_resource object (mocking what Waldur would send).

    This is what Waldur sends to the plugin when an order is created.
    We can create it manually for testing!
    """
    resource = Mock()
    resource.uuid = uuid_str or uuid4()
    resource.name = name or f"test-resource-{resource.uuid}"
    resource.backend_id = backend_id  # None for new resources
    resource.description = "Test resource created by integration test"
    resource.state = "Creating"
    return resource


class TestBackendHealthChecks:
    """Test health check operations with real OpenStack."""

    def test_ping_with_real_keystone(self, backend):
        """Test ping connects to real Keystone."""
        result = backend.ping()
        assert result is True, "Should connect to real Keystone"

    def test_diagnostics_with_real_keystone(self, backend):
        """Test diagnostics checks real OpenStack setup."""
        result = backend.diagnostics()
        # diagnostics returns True if all checks pass
        # May return False if domain/role need to be created, but should not crash
        assert isinstance(result, bool)


class TestResourceCreation:
    """Test resource creation WITHOUT Waldur - just mock the resource object."""

    def test_create_and_delete_project(self, backend):
        """Test creating and deleting a project with mocked Waldur resource."""
        # 1. Create a fake waldur_resource (what Waldur would send)
        test_uuid = str(uuid4())
        fake_resource = create_fake_waldur_resource(
            uuid_str=test_uuid,
            name="Integration Test Project",
            backend_id=None  # New resource, no backend_id yet
        )

        try:
            # 2. Create the resource (calls our refactored _create_resource_in_backend)
            backend_id = backend._create_resource_in_backend(fake_resource)

            # 3. Verify it was created
            assert backend_id == test_uuid
            assert backend.client.get_project(test_uuid) is not None

            # 4. Verify metadata
            metadata = backend.get_resource_metadata(backend_id)
            assert metadata["project_name"] == test_uuid
            assert metadata["enabled"] is True

        finally:
            # 5. Cleanup: Delete the project
            fake_resource.backend_id = test_uuid  # Now it has a backend_id
            backend.delete_resource(fake_resource)

            # 6. Verify deletion
            assert backend.client.get_project(test_uuid) is None

    def test_create_project_idempotency(self, backend):
        """Test creating same project twice is idempotent."""
        test_uuid = str(uuid4())
        fake_resource = create_fake_waldur_resource(uuid_str=test_uuid)

        try:
            # Create first time
            backend_id1 = backend._create_resource_in_backend(fake_resource)

            # Create again (should return existing)
            backend_id2 = backend._create_resource_in_backend(fake_resource)

            # Should return same backend_id
            assert backend_id1 == backend_id2
            assert backend_id1 == test_uuid

        finally:
            # Cleanup
            fake_resource.backend_id = test_uuid
            backend.delete_resource(fake_resource)


class TestResourceStateManagement:
    """Test project enable/disable without Waldur."""

    def test_disable_and_enable_project(self, backend):
        """Test disabling and enabling a project."""
        test_uuid = str(uuid4())
        fake_resource = create_fake_waldur_resource(uuid_str=test_uuid)

        try:
            # 1. Create project
            backend_id = backend._create_resource_in_backend(fake_resource)

            # 2. Disable project
            result = backend.downscale_resource(backend_id)
            assert result is True

            # 3. Verify disabled
            metadata = backend.get_resource_metadata(backend_id)
            assert metadata["enabled"] is False

            # 4. Enable project
            result = backend.restore_resource(backend_id)
            assert result is True

            # 5. Verify enabled
            metadata = backend.get_resource_metadata(backend_id)
            assert metadata["enabled"] is True

        finally:
            # Cleanup
            fake_resource.backend_id = test_uuid
            backend.delete_resource(fake_resource)


class TestUserManagement:
    """Test user management WITHOUT Waldur - mock the user add events."""

    def test_add_users_to_project(self, backend):
        """Test adding users to a project (mocking Waldur event)."""
        test_uuid = str(uuid4())
        fake_resource = create_fake_waldur_resource(uuid_str=test_uuid)

        try:
            # 1. Create project
            backend_id = backend._create_resource_in_backend(fake_resource)

            # 2. Mock adding users (what happens when Waldur sends user_added event)
            # This is what Waldur would send: set of usernames
            fake_user_ids = {"test-user-1", "test-user-2"}

            # 3. Add users to resource
            added_users = backend.add_users_to_resource(backend_id, fake_user_ids)

            # 4. Verify users were added
            assert len(added_users) == 2
            assert "test-user-1" in added_users
            assert "test-user-2" in added_users

            # 5. Verify users exist in OpenStack
            resource_users = backend.client.list_resource_users(backend_id)
            assert "test-user-1" in resource_users
            assert "test-user-2" in resource_users

            # 6. Remove users (mock user_removed event)
            removed_users = backend.remove_users_from_resource(backend_id, fake_user_ids)
            assert len(removed_users) == 2

        finally:
            # Cleanup
            fake_resource.backend_id = test_uuid
            backend.delete_resource(fake_resource)


class TestEventSimulation:
    """
    Simulate Waldur events without Waldur!

    This shows how you can test the full event flow:
    1. Order created → create_resource
    2. User added → add_users_to_resource
    3. User removed → remove_users_from_resource
    4. Resource deleted → delete_resource
    """

    def test_full_resource_lifecycle(self, backend):
        """Simulate complete resource lifecycle like Waldur would send."""
        test_uuid = str(uuid4())

        # Event 1: ORDER CREATED (from Waldur UI)
        print("\n📦 Simulating: User creates order in Waldur UI...")
        fake_resource = create_fake_waldur_resource(
            uuid_str=test_uuid,
            name="Customer Project Alpha",
        )

        # Plugin receives order and creates project
        backend_id = backend._create_resource_in_backend(fake_resource)
        print(f"✓ Project created in OpenStack: {backend_id}")
        assert backend_id == test_uuid

        try:
            # Event 2: USER ADDED TO TEAM (from Waldur UI)
            print("\n👤 Simulating: User adds team member in Waldur UI...")
            users_to_add = {"alice@example.com", "bob@example.com"}

            # Plugin receives user_added event
            added = backend.add_users_to_resource(backend_id, users_to_add)
            print(f"✓ Users added to OpenStack project: {added}")
            assert len(added) == 2

            # Event 3: USER REMOVED FROM TEAM (from Waldur UI)
            print("\n🗑️  Simulating: User removes team member in Waldur UI...")
            users_to_remove = {"alice@example.com"}

            # Plugin receives user_removed event
            removed = backend.remove_users_from_resource(backend_id, users_to_remove)
            print(f"✓ User removed from OpenStack project: {removed}")
            assert "alice@example.com" in removed

            # Verify only bob remains
            remaining_users = backend.client.list_resource_users(backend_id)
            assert "bob@example.com" in remaining_users
            assert "alice@example.com" not in remaining_users

        finally:
            # Event 4: RESOURCE DELETED (from Waldur UI)
            print("\n🗑️  Simulating: User deletes resource in Waldur UI...")
            fake_resource.backend_id = test_uuid
            backend.delete_resource(fake_resource)
            print(f"✓ Project deleted from OpenStack")

            # Verify deletion
            assert backend.client.get_project(test_uuid) is None


@pytest.mark.skip(reason="Example of how to test specific scenarios")
class TestEdgeCases:
    """Examples of edge cases you can test without full Waldur."""

    def test_create_resource_with_missing_uuid(self, backend):
        """Test error handling when UUID is missing."""
        fake_resource = Mock()
        fake_resource.uuid = None  # Missing UUID!
        fake_resource.name = "Bad Resource"

        with pytest.raises(Exception) as exc_info:
            backend._create_resource_in_backend(fake_resource)

        assert "uuid" in str(exc_info.value).lower()

    def test_add_users_to_nonexistent_project(self, backend):
        """Test adding users to a project that doesn't exist."""
        fake_backend_id = "nonexistent-project-12345"

        # This should handle gracefully (not crash)
        with pytest.raises(Exception):
            backend.add_users_to_resource(fake_backend_id, {"user1"})


if __name__ == "__main__":
    print("""
    Integration Tests - Testing OpenStack Without Waldur
    ======================================================

    These tests connect to REAL OpenStack but DON'T need Waldur!

    Before running:
    1. source test.env  # Load OpenStack credentials
    2. pytest tests/test_backend_integration.py -v -s

    What these tests do:
    - ✓ Connect to real OpenStack Keystone
    - ✓ Create/delete real projects
    - ✓ Add/remove real users
    - ✓ Test full lifecycle
    - ✗ NO Waldur needed!
    - ✗ NO RabbitMQ needed!

    This is MUCH faster than full end-to-end testing!
    """)

    pytest.main([__file__, "-v", "-s"])
