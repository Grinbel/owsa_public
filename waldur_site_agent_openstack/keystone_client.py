"""
OpenStack Keystone Client Wrapper.

This module provides a simplified interface to OpenStack Keystone API v3.
It handles authentication, user management, project management, and role assignment.
"""

import logging
from typing import Optional, List, Any

from keystoneclient.v3 import client as keystone_client
from keystoneclient import session
from keystoneclient.auth.identity import v3
from keystoneclient import exceptions as keystone_exceptions

from waldur_site_agent_openstack.config import OpenStackConfig
from waldur_site_agent_openstack.utils import retry_on_exception, format_openstack_error

logger = logging.getLogger(__name__)


class KeystoneClientError(Exception):
    """Base exception for Keystone client errors."""
    pass


class KeystoneClient:
    """
    High-level wrapper for OpenStack Keystone API.

    Usage:
        config = OpenStackConfig.from_backend_settings(backend_settings)
        client = KeystoneClient(config)

        # Create user and assign to project
        user = client.ensure_user("john.doe", "john@example.com")
        project = client.get_project("my-project")
        client.assign_role(user, project, "_member_")
    """

    def __init__(self, config: OpenStackConfig):
        """
        Initialize Keystone client.

        Args:
            config: OpenStackConfig instance

        Raises:
            KeystoneClientError: If initialization fails
        """
        self.config = config
        self._keystone = None
        self._session = None

        try:
            self._initialize_session()
            logger.info(f"KeystoneClient initialized for {config.auth_url}")
        except Exception as e:
            error_msg = f"Failed to initialize Keystone client: {format_openstack_error(e)}"
            logger.error(error_msg)
            raise KeystoneClientError(error_msg) from e

    def _initialize_session(self):
        """Initialize Keystone session and client."""
        auth = v3.Password(
            auth_url=self.config.auth_url,
            username=self.config.username,
            password=self.config.password,
            project_name=self.config.project_name,
            user_domain_name=self.config.user_domain_name,
            project_domain_name=self.config.project_domain_name,
        )

        self._session = session.Session(auth=auth, verify=self.config.verify_ssl)
        self._keystone = keystone_client.Client(
            session=self._session,
            interface=self.config.interface,
            region_name=self.config.region_name,
        )

    @property
    def keystone(self):
        """Get Keystone client instance."""
        if self._keystone is None:
            self._initialize_session()
        return self._keystone

    # ========================================================================
    # AUTHENTICATION
    # ========================================================================

    @retry_on_exception(max_attempts=3, base_delay=1.0)
    def get_token(self) -> str:
        """Get authentication token."""
        if self._session is None:
            self._initialize_session()
        try:
            return self._session.get_token()
        except Exception as e:
            raise KeystoneClientError(f"Failed to get token, make sure the session is properly initialized before asking for token: {e}") from e

    # ========================================================================
    # DOMAIN OPERATIONS
    # ========================================================================

    def get_domain(self, domain_name: str):
        """Get domain by name."""
        try:
            domains = self.keystone.domains.list(name=domain_name)
            return domains[0] if domains else None
        except Exception as e:
            logger.error(f"Error getting domain {domain_name}: {format_openstack_error(e)}")
            return None

    def ensure_domain(self, domain_name: str):
        """Get or create domain."""
        domain = self.get_domain(domain_name)
        if domain:
            return domain

        try:
            domain = self.keystone.domains.create(
                name=domain_name, description=f"Domain {domain_name} created by ensure_domain", enabled=True
            )
            logger.info(f"✓ Created domain: {domain_name}")
            return domain
        except keystone_exceptions.Conflict:
            return self.get_domain(domain_name)
        except Exception as e:
            logger.error(f"Error creating domain: {format_openstack_error(e)}")
            raise KeystoneClientError(f"Failed to create domain: {e}") from e

    # ========================================================================
    # PROJECT OPERATIONS
    # ========================================================================

    def get_project(self, project_name: str, domain=None):
        """Get project by name."""
        try:
            if domain is None:
                domain = self.get_domain(self.config.domain_name)

            projects = self.keystone.projects.list(name=project_name, domain=domain)
            return projects[0] if projects else None
        except Exception as e:
            logger.error(f"Error getting project: {format_openstack_error(e)}")
            return None

    def get_resource(self, resource_backend_id: str) -> Optional[dict]:
        """
        Get resource (project) information by backend ID.

        This method is required by waldur-site-agent's BaseBackend interface.
        For OpenStack, a resource corresponds to a project.

        Args:
            resource_backend_id: Project identifier (project name)

        Returns:
            Dictionary with resource information, or None if not found
        """
        try:
            project = self.get_project(resource_backend_id)
            if not project:
                logger.debug(f"Resource (project) '{resource_backend_id}' not found")
                return None

            # Return project information as a dictionary
            resource_info = {
                "backend_id": resource_backend_id,
                "project_id": project.id,
                "project_name": project.name,
                "enabled": project.enabled,
                "domain_id": project.domain_id,
                "description": getattr(project, "description", ""),
            }

            logger.debug(f"Retrieved resource info for '{resource_backend_id}': {resource_info}")
            return resource_info

        except Exception as e:
            logger.error(f"Error getting resource '{resource_backend_id}': {format_openstack_error(e)}")
            return None

    @retry_on_exception(max_attempts=3, base_delay=1.0)
    def create_project(self, project_name: str, domain=None, description: str = ""):
        """Create a new project."""
        try:
            if domain is None:
                domain = self.ensure_domain(self.config.domain_name)

            project = self.keystone.projects.create(
                name=project_name,
                domain=domain,
                description=description or f"Project {project_name}",
                enabled=True,
            )
            logger.info(f"✓ Created project: {project_name}")
            return project
        except keystone_exceptions.Conflict:
            logger.debug(f"Project {project_name} already exists")
            return self.get_project(project_name, domain)
        except Exception as e:
            error_msg = f"Failed to create project in create_project func {project_name}: {format_openstack_error(e)}"
            logger.error(error_msg)
            raise KeystoneClientError(error_msg) from e

    def delete_project(self, project_name: str, domain=None) -> bool:
        """Delete a project."""
        try:
            project = self.get_project(project_name, domain)
            if not project:
                logger.warning(f"Project {project_name} not found")
                return False

            self.keystone.projects.delete(project)
            logger.info(f"✓ Deleted project: {project_name}")
            return True
        except Exception as e:
            logger.error(f"Error deleting project: {format_openstack_error(e)}")
            return False

    def enable_project(self, project_name: str, domain=None):
        """Enable a project."""
        project = self.get_project(project_name, domain)
        if project:
            self.keystone.projects.update(project, enabled=True)
            logger.info(f"✓ Enabled project: {project_name}")

    def disable_project(self, project_name: str, domain=None):
        """Disable a project."""
        project = self.get_project(project_name, domain)
        if project:
            self.keystone.projects.update(project, enabled=False)
            logger.info(f"✓ Disabled project: {project_name}")

            self.keystone.projects.update(project, enabled=False)
            logger.info(f"✓ Disabled project: {project_name}")

    # ========================================================================
    # USER OPERATIONS
    # ========================================================================

    def get_user(self, username: str, domain=None):
        """Get user by username."""
        try:
            if domain is None:
                domain = self.get_domain(self.config.domain_name)

            users = self.keystone.users.list(name=username, domain=domain)
            return users[0] if users else None
        except Exception as e:
            logger.error(f"Error getting user: {format_openstack_error(e)}")
            return None

    @retry_on_exception(max_attempts=3, base_delay=1.0)
    def ensure_user(
        self, username: str, email: Optional[str] = None, domain=None, enabled: Optional[bool] = None
    ):
        """Get or create user."""
        user = self.get_user(username, domain)
        if user:
            # Update email if needed
            if email and self.config.sync_user_emails and hasattr(user, "email") and user.email != email:
                try:
                    self.keystone.users.update(user, email=email)
                    logger.info(f"Updated email for user {username}")
                except Exception as e:
                    logger.warning(f"Failed to update email: {e}")
            return user

        # Create user
        logger.info(f"create user if not exist ? : {self.config.create_users_if_not_exist}")
        if not self.config.create_users_if_not_exist:
            raise KeystoneClientError(f"User {username} not found and auto-creation disabled")

        try:
            if domain is None:
                domain = self.ensure_domain(self.config.domain_name)

            if enabled is None:
                enabled = self.config.user_enabled_by_default

            user = self.keystone.users.create(
                name=username, email=email, domain=domain, enabled=enabled
            )
            logger.info(f"✓ Created user: {username}")
            return user
        except keystone_exceptions.Conflict:
            return self.get_user(username, domain)
        except Exception as e:
            error_msg = f"Failed to create user {username}: {format_openstack_error(e)}"
            logger.error(error_msg)
            raise KeystoneClientError(error_msg) from e

    # ========================================================================
    # ROLE OPERATIONS
    # ========================================================================

    def get_role(self, role_name: str):
        """Get role by name."""
        try:
            roles = self.keystone.roles.list(name=role_name)
            return roles[0] if roles else None
        except Exception as e:
            logger.error(f"Error getting role: {format_openstack_error(e)}")
            return None

    def ensure_role(self, role_name: str):
        """Get or create role."""
        role = self.get_role(role_name)
        if role:
            return role

        try:
            role = self.keystone.roles.create(name=role_name)
            logger.info(f"✓ Created role: {role_name}")
            return role
        except keystone_exceptions.Conflict:
            return self.get_role(role_name)
        except Exception as e:
            logger.error(f"Error creating role: {format_openstack_error(e)}")
            raise KeystoneClientError(f"Failed to create role: {e}") from e

    @retry_on_exception(max_attempts=3, base_delay=1.0)
    def assign_role(self, user, project, role_name: str) -> bool:
        """Assign role to user in project."""
        try:
            role = self.ensure_role(role_name)
            self.keystone.roles.grant(role=role, user=user, project=project)
            logger.info(f"✓ Assigned '{role_name}' to '{user.name}' in '{project.name}'")
            return True
        except keystone_exceptions.Conflict:
            logger.debug(f"Role already assigned: {role_name} → {user.name}")
            return True
        except Exception as e:
            logger.error(f"Error assigning role: {format_openstack_error(e)}")
            return False

    def revoke_role(self, user, project, role_name: str) -> bool:
        """Revoke role from user in project."""
        try:
            role = self.get_role(role_name)
            if not role:
                return False

            self.keystone.roles.revoke(role=role, user=user, project=project)
            logger.info(f"✓ Revoked '{role_name}' from '{user.name}' in '{project.name}'")
            return True
        except Exception as e:
            logger.error(f"Error revoking role: {format_openstack_error(e)}")
            return False

    def revoke_all_project_roles(self, user, project) -> bool:
        """Revoke all roles from user in project."""
        try:
            assignments = self.keystone.role_assignments.list(user=user, project=project)
            if not assignments:
                return True

            success = True
            for assignment in assignments:
                try:
                    role_id = assignment.role["id"]
                    self.keystone.roles.revoke(role=role_id, user=user, project=project)
                except Exception as e:
                    logger.error(f"Failed to revoke role {role_id}: {e}")
                    success = False

            if success:
                logger.info(f"✓ Revoked all roles from '{user.name}' in '{project.name}'")

            return success
        except Exception as e:
            logger.error(f"Error revoking all roles: {format_openstack_error(e)}")
            return False
