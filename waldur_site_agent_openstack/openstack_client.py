"""
OpenStack Client - BaseClient Implementation.

This module implements the BaseClient interface for OpenStack Keystone,
mapping waldur-site-agent abstractions to OpenStack concepts:
- Resource = Project
- Association = Role Assignment
- Limits = Quotas (future: Nova/Cinder integration)
- Usage = Usage tracking (future: Ceilometer/Gnocchi integration)
"""

import logging
from typing import Optional, List

from waldur_site_agent.backend.clients import BaseClient, ClientResource, Association
from waldur_site_agent_openstack.keystone_client import KeystoneClient, KeystoneClientError
from waldur_site_agent_openstack.utils import setup_plugin_logger

logger = logging.getLogger(__name__)
setup_plugin_logger(logger)


class OpenStackClient(BaseClient):
    """
    BaseClient implementation for OpenStack Keystone.

    This client wraps KeystoneClient to provide the standard BaseClient interface
    expected by waldur-site-agent. It translates between waldur-site-agent's
    Slurm-inspired abstractions and OpenStack Keystone concepts.

    Conceptual Mapping:
        - Resource (waldur) → Project (OpenStack)
        - Association (waldur) → Role Assignment (OpenStack)
        - User (waldur) → User (OpenStack)
        - Limits (waldur) → Quotas (Nova/Cinder - not in Keystone)
        - Usage (waldur) → Telemetry (Ceilometer/Gnocchi - not in Keystone)
    """

    def __init__(self, keystone_client: KeystoneClient):
        """
        Initialize OpenStackClient with KeystoneClient wrapper.

        Args:
            keystone_client: Low-level KeystoneClient instance
        """
        self.keystone = keystone_client
        logger.info("OpenStackClient initialized successfully")

    # ========================================================================
    # HEALTH CHECK OPERATIONS
    # ========================================================================

    def ping(self) -> bool:
        """
        Check if OpenStack Keystone is accessible.

        Returns:
            True if Keystone is accessible and can authenticate, False otherwise
        """
        logger.info("[PING] Checking Keystone connectivity")
        try:
            token = self.keystone.get_token()
            if token:
                logger.info("[PING] Success: Keystone is accessible")
                return True
            logger.warning("[PING] Failed: No token obtained")
            return False
        except Exception as e:
            logger.error(f"[PING] Failed: {e}", exc_info=True)
            return False

    def get_domain(self, domain_name: str):
        """
        Get domain by name.

        Args:
            domain_name: Name of the domain to retrieve

        Returns:
            Domain object if found, None otherwise
        """
        logger.info(f"[GET_DOMAIN] Called with domain_name='{domain_name}'")
        try:
            domain = self.keystone.get_domain(domain_name)
            if domain:
                logger.info(f"[GET_DOMAIN] Success: Domain '{domain_name}' found (id={domain.id})")
            else:
                logger.info(f"[GET_DOMAIN] Not found: Domain '{domain_name}' does not exist")
            return domain
        except Exception as e:
            logger.error(f"[GET_DOMAIN] Failed: {e}", exc_info=True)
            return None

    def get_role(self, role_name: str):
        """
        Get role by name.

        Args:
            role_name: Name of the role to retrieve

        Returns:
            Role object if found, None otherwise
        """
        logger.info(f"[GET_ROLE] Called with role_name='{role_name}'")
        try:
            role = self.keystone.get_role(role_name)
            if role:
                logger.info(f"[GET_ROLE] Success: Role '{role_name}' found (id={role.id})")
            else:
                logger.info(f"[GET_ROLE] Not found: Role '{role_name}' does not exist")
            return role
        except Exception as e:
            logger.error(f"[GET_ROLE] Failed: {e}", exc_info=True)
            return None

    # ========================================================================
    # RESOURCE OPERATIONS (Project Management)
    # ========================================================================

    def list_resources(self) -> list[ClientResource]:
        """
        List all projects as resources.

        Returns:
            List of ClientResource objects representing OpenStack projects
        """
        try:
            domain = self.keystone.get_domain(self.keystone.config.domain_name)
            if not domain:
                logger.warning(f"Domain '{self.keystone.config.domain_name}' not found")
                return []

            projects = self.keystone.keystone.projects.list(domain=domain)
            logger.debug(f"Found {len(projects)} projects in domain '{domain.name}'")

            resources = []
            for project in projects:
                resource = ClientResource(
                    name=project.name,
                    description=getattr(project, "description", ""),
                    organization=domain.name,  # Map domain as organization
                )
                resources.append(resource)

            return resources

        except Exception as e:
            logger.error(f"Error listing resources: {e}", exc_info=True)
            return []

    def get_resource(self, resource_id: str) -> Optional[ClientResource]:
        """
        Get project by name (resource_id = project_name).

        Args:
            resource_id: Project name (OpenStack project name)

        Returns:
            ClientResource if found, None otherwise
        """
        try:
            project = self.keystone.get_project(resource_id)
            if not project:
                logger.debug(f"Resource '{resource_id}' not found")
                return None

            domain = self.keystone.get_domain(self.keystone.config.domain_name)
            resource = ClientResource(
                name=project.name,
                description=getattr(project, "description", ""),
                organization=domain.name if domain else "",
            )

            logger.debug(f"Retrieved resource: {resource_id}")
            return resource

        except Exception as e:
            logger.error(f"Error getting resource '{resource_id}': {e}", exc_info=True)
            return None

    def create_resource(
        self, name: str, description: str, organization: str, parent_name: Optional[str] = None
    ) -> str:
        """
        Create OpenStack project.

        Args:
            name: Project name (becomes resource_backend_id)
            description: Project description (from Waldur resource name)
            organization: Parent organization (not used in flat OpenStack structure)
            parent_name: Parent project (not used in flat structure)

        Returns:
            Project name (resource_backend_id)

        Raises:
            KeystoneClientError: If project creation fails
        """
        try:
            logger.info(f"Creating resource (project): {name}")

            # Check if project already exists
            existing_project = self.keystone.get_project(name)
            if existing_project:
                logger.info(f"Project '{name}' already exists, returning existing")
                return name

            # Create the project
            project = self.keystone.create_project(
                project_name=name,
                description=description,
            )

            logger.info(f"✓ Created resource (project): {name} (id={project.id})")
            return name

        except Exception as e:
            error_msg = f"Failed to create resource '{name}': {e}"
            logger.error(error_msg, exc_info=True)
            raise KeystoneClientError(error_msg) from e

    def delete_resource(self, name: str) -> str:
        """
        Delete project by name.

        Args:
            name: Project name to delete

        Returns:
            Success message or error message

        Raises:
            KeystoneClientError: If deletion fails
        """
        try:
            logger.info(f"Deleting resource (project): {name}")

            success = self.keystone.delete_project(name)
            if success:
                logger.info(f"✓ Deleted resource (project): {name}")
                return f"Successfully deleted project '{name}'"
            else:
                logger.warning(f"Project '{name}' not found or already deleted")
                return f"Project '{name}' not found"

        except Exception as e:
            error_msg = f"Failed to delete resource '{name}': {e}"
            logger.error(error_msg, exc_info=True)
            raise KeystoneClientError(error_msg) from e

    def get_project(self, project_name: str):
        """
        Get project by name.

        Args:
            project_name: Name of the project to retrieve

        Returns:
            Project object if found, None otherwise
        """
        logger.info(f"[GET_PROJECT] Called with project_name='{project_name}'")
        try:
            project = self.keystone.get_project(project_name)
            if project:
                logger.info(f"[GET_PROJECT] Success: Project '{project_name}' found (id={project.id})")
            else:
                logger.info(f"[GET_PROJECT] Not found: Project '{project_name}' does not exist")
            return project
        except Exception as e:
            logger.error(f"[GET_PROJECT] Failed: {e}", exc_info=True)
            return None

    def create_project(self, project_name: str, description: str = ""):
        """
        Create OpenStack project.

        Args:
            project_name: Name of the project to create
            description: Optional description

        Returns:
            Created project object

        Raises:
            KeystoneClientError: If project creation fails
        """
        logger.info(f"[CREATE_PROJECT] Called with project_name='{project_name}', description='{description}'")
        try:
            project = self.keystone.create_project(
                project_name=project_name,
                description=description,
            )
            logger.info(f"[CREATE_PROJECT] Success: Project '{project_name}' created (id={project.id})")
            return project
        except Exception as e:
            logger.error(f"[CREATE_PROJECT] Failed: {e}", exc_info=True)
            raise KeystoneClientError(f"Failed to create project '{project_name}': {e}") from e

    def disable_project(self, project_name: str) -> bool:
        """
        Disable project.

        Args:
            project_name: Name of the project to disable

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"[DISABLE_PROJECT] Called with project_name='{project_name}'")
        try:
            self.keystone.disable_project(project_name)
            logger.info(f"[DISABLE_PROJECT] Success: Project '{project_name}' disabled")
            return True
        except Exception as e:
            logger.error(f"[DISABLE_PROJECT] Failed: {e}", exc_info=True)
            return False

    def enable_project(self, project_name: str) -> bool:
        """
        Enable project.

        Args:
            project_name: Name of the project to enable

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"[ENABLE_PROJECT] Called with project_name='{project_name}'")
        try:
            self.keystone.enable_project(project_name)
            logger.info(f"[ENABLE_PROJECT] Success: Project '{project_name}' enabled")
            return True
        except Exception as e:
            logger.error(f"[ENABLE_PROJECT] Failed: {e}", exc_info=True)
            return False

    def get_project_metadata(self, project_name: str) -> dict:
        """
        Get metadata for a project.

        Args:
            project_name: Name of the project

        Returns:
            Dictionary with project metadata, empty dict if not found
        """
        logger.info(f"[GET_PROJECT_METADATA] Called with project_name='{project_name}'")
        try:
            project = self.keystone.get_project(project_name)
            if not project:
                logger.info(f"[GET_PROJECT_METADATA] Not found: Project '{project_name}' does not exist")
                return {}

            metadata = {
                "project_id": project.id,
                "project_name": project.name,
                "domain": project.domain_id,
                "enabled": project.enabled,
                "description": getattr(project, "description", ""),
            }
            logger.info(f"[GET_PROJECT_METADATA] Success: Retrieved metadata for '{project_name}'")
            logger.debug(f"[GET_PROJECT_METADATA] Metadata: {metadata}")
            return metadata

        except Exception as e:
            logger.error(f"[GET_PROJECT_METADATA] Failed: {e}", exc_info=True)
            return {}

    # ========================================================================
    # QUOTA/LIMITS OPERATIONS (Future: Nova/Cinder Integration)
    # ========================================================================

    def set_resource_limits(self, resource_id: str, limits_dict: dict[str, int]) -> Optional[str]:
        """
        Set quotas (requires Nova/Cinder integration - log warning for now).

        NOTE: OpenStack Keystone does not manage resource quotas.
        Quota management requires integration with:
        - Nova (compute quotas: cores, instances, ram)
        - Cinder (storage quotas: volumes, snapshots, gigabytes)
        - Neutron (network quotas: networks, ports, routers)

        Args:
            resource_id: Project name
            limits_dict: Dictionary of limits (e.g., {"cores": 20, "ram": 51200})

        Returns:
            Warning message about unimplemented feature
        """
        logger.warning(
            f"set_resource_limits() called for project '{resource_id}' with limits {limits_dict}. "
            f"Quota management requires Nova/Cinder integration (not implemented in Keystone-only plugin)."
        )
        return "Quota management requires Nova/Cinder integration (future enhancement)"

    def get_resource_limits(self, resource_id: str) -> dict[str, int]:
        """
        Get quotas (not implemented for Keystone-only).

        NOTE: Requires Nova/Cinder integration for actual quota retrieval.

        Args:
            resource_id: Project name

        Returns:
            Empty dict (quotas not available in Keystone-only)
        """
        logger.debug(
            f"get_resource_limits() called for project '{resource_id}'. "
            f"Returning empty dict (requires Nova/Cinder integration)."
        )
        return {}

    def get_resource_user_limits(self, resource_id: str) -> dict[str, dict[str, int]]:
        """
        Get per-user quotas (not implemented for Keystone-only).

        NOTE: Requires Nova/Cinder integration for per-user quota retrieval.

        Args:
            resource_id: Project name

        Returns:
            Empty dict (per-user quotas not available in Keystone-only)
        """
        logger.debug(
            f"get_resource_user_limits() called for project '{resource_id}'. "
            f"Returning empty dict (requires Nova/Cinder integration)."
        )
        return {}

    def set_resource_user_limits(
        self, resource_id: str, username: str, limits_dict: dict[str, int]
    ) -> str:
        """
        Set per-user quotas (not implemented for Keystone-only).

        NOTE: Requires Nova/Cinder integration for per-user quota management.

        Args:
            resource_id: Project name
            username: Username
            limits_dict: Dictionary of limits

        Returns:
            Warning message about unimplemented feature
        """
        logger.warning(
            f"set_resource_user_limits() called for user '{username}' in project '{resource_id}' "
            f"with limits {limits_dict}. Per-user quotas require Nova/Cinder integration "
            f"(not implemented in Keystone-only plugin)."
        )
        return "Per-user quota management requires Nova/Cinder integration (future enhancement)"

    # ========================================================================
    # ASSOCIATION OPERATIONS (Role Assignment)
    # ========================================================================

    def get_association(self, user: str, resource_id: str) -> Optional[Association]:
        """
        Check if user has ANY role in project.

        Args:
            user: Username
            resource_id: Project name

        Returns:
            Association if user has role assignment, None otherwise
        """
        try:
            project = self.keystone.get_project(resource_id)
            if not project:
                logger.debug(f"Project '{resource_id}' not found")
                return None

            user_obj = self.keystone.get_user(user)
            if not user_obj:
                logger.debug(f"User '{user}' not found")
                return None

            # Check if user has any role assignments in this project
            assignments = self.keystone.keystone.role_assignments.list(
                user=user_obj, project=project
            )

            if assignments:
                logger.debug(f"User '{user}' has {len(assignments)} role(s) in project '{resource_id}'")
                # Create Association object
                association = Association(
                    account=resource_id,
                    user=user,
                    value=len(assignments),  # Number of role assignments
                )
                return association
            else:
                logger.debug(f"User '{user}' has no roles in project '{resource_id}'")
                return None

        except Exception as e:
            logger.error(f"Error checking association for user '{user}' in project '{resource_id}': {e}")
            return None

    def create_association(
        self, username: str, resource_id: str, default_account: Optional[str] = None
    ) -> str:
        """
        Assign default role to user in project.

        Args:
            username: OpenStack username
            resource_id: Project name
            default_account: Ignored (Slurm-specific parameter)

        Returns:
            Success message

        Raises:
            KeystoneClientError: If role assignment fails
        """
        try:
            logger.info(f"Creating association: user '{username}' → project '{resource_id}'")

            # Get or create project
            project = self.keystone.get_project(resource_id)
            if not project:
                logger.warning(f"Project '{resource_id}' not found, creating it")
                project = self.keystone.create_project(resource_id)

            # Get or create user
            user = self.keystone.ensure_user(username)

            # Assign default role
            role_name = self.keystone.config.default_role
            success = self.keystone.assign_role(user, project, role_name)

            if success:
                logger.info(f"✓ Created association: '{username}' → '{resource_id}' with role '{role_name}'")
                return f"Successfully assigned role '{role_name}' to user '{username}' in project '{resource_id}'"
            else:
                error_msg = f"Failed to assign role to user '{username}' in project '{resource_id}'"
                logger.error(error_msg)
                raise KeystoneClientError(error_msg)

        except Exception as e:
            error_msg = f"Failed to create association for user '{username}' in project '{resource_id}': {e}"
            logger.error(error_msg, exc_info=True)
            raise KeystoneClientError(error_msg) from e

    def delete_association(self, username: str, resource_id: str) -> str:
        """
        Revoke all roles from user in project.

        Args:
            username: Username
            resource_id: Project name

        Returns:
            Success message

        Raises:
            KeystoneClientError: If role revocation fails
        """
        try:
            logger.info(f"Deleting association: user '{username}' from project '{resource_id}'")

            project = self.keystone.get_project(resource_id)
            if not project:
                logger.warning(f"Project '{resource_id}' not found")
                return f"Project '{resource_id}' not found"

            user = self.keystone.get_user(username)
            if not user:
                logger.warning(f"User '{username}' not found")
                return f"User '{username}' not found"

            # Revoke all roles from user in project
            success = self.keystone.revoke_all_project_roles(user, project)

            if success:
                logger.info(f"✓ Deleted association: '{username}' from '{resource_id}'")
                return f"Successfully revoked all roles from user '{username}' in project '{resource_id}'"
            else:
                error_msg = f"Failed to revoke roles from user '{username}' in project '{resource_id}'"
                logger.error(error_msg)
                raise KeystoneClientError(error_msg)

        except Exception as e:
            error_msg = f"Failed to delete association for user '{username}' from project '{resource_id}': {e}"
            logger.error(error_msg, exc_info=True)
            raise KeystoneClientError(error_msg) from e

    # ========================================================================
    # USAGE & REPORTING (Future: Ceilometer/Gnocchi Integration)
    # ========================================================================

    def get_usage_report(self, resource_ids: list[str]) -> list:
        """
        Get usage (requires Ceilometer/Gnocchi - return empty for now).

        NOTE: OpenStack Keystone does not track resource usage.
        Usage tracking requires integration with:
        - Ceilometer (telemetry data collection)
        - Gnocchi (time-series database for metrics)
        - Or direct Nova/Cinder API queries

        Args:
            resource_ids: List of project names

        Returns:
            Empty list (usage tracking not available in Keystone-only)
        """
        logger.debug(
            f"get_usage_report() called for {len(resource_ids)} projects. "
            f"Returning empty list (requires Ceilometer/Gnocchi integration)."
        )
        return []

    def list_resource_users(self, resource_id: str) -> list[str]:
        """
        List all users with role assignments in project.

        Args:
            resource_id: Project name

        Returns:
            List of usernames with roles in the project
        """
        try:
            project = self.keystone.get_project(resource_id)
            if not project:
                logger.warning(f"Project '{resource_id}' not found")
                return []

            # Get all role assignments for this project
            assignments = self.keystone.keystone.role_assignments.list(project=project)

            # Extract unique usernames
            usernames = set()
            for assignment in assignments:
                # assignment.user is a dict with 'id' key
                if hasattr(assignment, 'user') and assignment.user:
                    user_id = assignment.user.get('id')
                    if user_id:
                        # Look up user by ID to get username
                        try:
                            user_obj = self.keystone.keystone.users.get(user_id)
                            if user_obj and hasattr(user_obj, 'name'):
                                usernames.add(user_obj.name)
                        except Exception as e:
                            logger.debug(f"Could not resolve user ID {user_id}: {e}")

            logger.debug(f"Found {len(usernames)} users in project '{resource_id}'")
            return list(usernames)

        except Exception as e:
            logger.error(f"Error listing users for project '{resource_id}': {e}", exc_info=True)
            return []

    def list_users(self, domain_name: Optional[str] = None) -> list:
        """
        List all users in domain.

        Args:
            domain_name: Optional domain name (uses default if None)

        Returns:
            List of user objects
        """
        domain_name = domain_name or self.keystone.config.domain_name
        logger.info(f"[LIST_USERS] Called with domain_name='{domain_name}'")
        try:
            domain = self.keystone.get_domain(domain_name)
            if not domain:
                logger.warning(f"[LIST_USERS] Domain '{domain_name}' not found")
                return []

            users = self.keystone.keystone.users.list(domain=domain)
            logger.info(f"[LIST_USERS] Success: Found {len(users)} users in domain '{domain_name}'")
            return users

        except Exception as e:
            logger.error(f"[LIST_USERS] Failed: {e}", exc_info=True)
            return []

    # ========================================================================
    # LINUX USER MANAGEMENT (Not Applicable)
    # ========================================================================

    def create_linux_user_homedir(self, username: str, umask: str = "0700") -> None:
        """
        NOT APPLICABLE for OpenStack Keystone.

        OpenStack manages virtual resources in the cloud, not Linux system users.
        Home directory creation is only relevant for HPC systems like Slurm.

        Args:
            username: Username
            umask: Umask for directory creation

        Raises:
            NotImplementedError: Always raised with explanation
        """
        raise NotImplementedError(
            "create_linux_user_homedir() is not applicable to OpenStack Keystone. "
            "OpenStack manages cloud users and projects, not Linux system users with home directories. "
            "This method is only relevant for HPC backends like Slurm."
        )
