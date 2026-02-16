"""
OpenStack Backend for waldur-site-agent.

This module implements the BaseBackend interface for OpenStack Keystone,
providing real-time synchronization of users and projects between
Waldur and OpenStack.
"""

import logging
from typing import Dict, Any, Optional, Set

from waldur_site_agent.backend.backends import BaseBackend, AbstractUsernameManagementBackend
from waldur_site_agent.backend.exceptions import BackendError
from waldur_api_client.models.offering_user import OfferingUser

from waldur_site_agent_openstack.config import OpenStackConfig
from waldur_site_agent_openstack.keystone_client import KeystoneClient, KeystoneClientError
from waldur_site_agent_openstack.openstack_client import OpenStackClient
from waldur_site_agent_openstack.utils import (
    sanitize_for_openstack,
    validate_backend_id,
    setup_plugin_logger,
)

logger = logging.getLogger(__name__)
setup_plugin_logger(logger)


class OpenStackBackend(BaseBackend):
    """
    OpenStack Keystone backend for waldur-site-agent.

    This backend handles:
    - User synchronization (membership_sync_backend)
    - Project creation/deletion (order_processing_backend)
    - Health checks and diagnostics

    Architecture:
        waldur-site-agent → OpenStackBackend → KeystoneClient → OpenStack Keystone API
    """

    def __init__(self, backend_settings: Dict[str, Any], backend_components: Dict[str, Dict]):
        """
        Initialize OpenStack backend.

        Args:
            backend_settings: Configuration dict from waldur-site-agent config
            backend_components: Resource components definition

        Raises:
            BackendError: If initialization fails
        """
        super().__init__(backend_settings, backend_components)

        try:
            # Parse and validate configuration
            self.config = OpenStackConfig.from_backend_settings(backend_settings)
            self.config.validate()

            # Initialize low-level Keystone client (my keystone implementing op keystone api)
            self.keystone_client = KeystoneClient(self.config)

            # Initialize BaseClient wrapper (OpenStackClient)
            # This provides the standard BaseClient interface expected by waldur-site-agent
            self.client = OpenStackClient(self.keystone_client)

            # Set backend type
            self.backend_type = "openstack"

            logger.info(
                f"OpenStackBackend initialized successfully "
                f"(auth_url={self.config.auth_url}, domain={self.config.domain_name})"
            )
            logger.debug(f"Configuration: {self.config.sanitize_for_logging()}")

        except Exception as e:
            error_msg = f"Failed to initialize OpenStack backend: {e}"
            logger.error(error_msg, exc_info=True)
            raise BackendError(error_msg) from e

    # ========================================================================
    # HEALTH CHECKS
    # ========================================================================

    def ping(self, raise_exception: bool = False) -> bool:
        """
        Check if OpenStack Keystone is accessible.

        Args:
            raise_exception: If True, raise exception on failure

        Returns:
            True if backend is accessible, False otherwise
        """
        try:
            result = self.client.ping()
            if result:
                logger.debug("✓ Keystone ping successful")
            else:
                logger.error("Keystone ping failed")
            return result
        except Exception as err:
            logger.error(f"Keystone ping failed: {err}")
            if raise_exception:
                raise BackendError(f"Cannot connect to Keystone: {err}") from err
            return False

    def diagnostics(self) -> bool:
        """
        Run comprehensive diagnostics on OpenStack backend.

        Returns:
            True if all checks pass, False otherwise
        """
        logger.info("=" * 60)
        logger.info("OpenStack Backend Diagnostics")
        logger.info("=" * 60)

        all_checks_passed = True

        # Check 1: Keystone connectivity
        logger.info("Check 1: Keystone connectivity")
        try:
            if self.ping(raise_exception=True):
                logger.info("  ✓ Keystone is reachable and authentication works")
            else:
                logger.error("  ✗ Keystone ping failed")
                all_checks_passed = False
        except Exception as e:
            logger.error(f"  ✗ Keystone connectivity failed: {e}")
            all_checks_passed = False

        # Check 2: Domain access
        logger.info(f"Check 2: Domain '{self.config.domain_name}' access")
        try:
            domain = self.client.get_domain(self.config.domain_name)
            if domain:
                logger.info(f"  ✓ Domain '{self.config.domain_name}' accessible")
            else:
                logger.warning(f"  ⚠ Domain '{self.config.domain_name}' not found (will be created)")
        except Exception as e:
            logger.error(f"  ✗ Domain access failed: {e}")
            all_checks_passed = False

        # Check 3: Default role exists
        logger.info(f"Check 3: Default role '{self.config.default_role}' availability")
        try:
            role = self.client.get_role(self.config.default_role)
            if role:
                logger.info(f"  ✓ Role '{self.config.default_role}' exists")
            else:
                logger.warning(f"  ⚠ Role '{self.config.default_role}' not found (will be created)")
        except Exception as e:
            logger.error(f"  ✗ Role check failed: {e}")

        # Check 4: Configuration validation
        logger.info("Check 4: Configuration validation")
        try:
            self.config.validate()
            logger.info("  ✓ Configuration is valid")
        except Exception as e:
            logger.error(f"  ✗ Configuration validation failed: {e}")
            all_checks_passed = False

        # Summary
        logger.info("=" * 60)
        if all_checks_passed:
            logger.info("✓ All diagnostic checks passed")
        else:
            logger.warning("⚠ Some diagnostic checks failed")
        logger.info("=" * 60)

        return all_checks_passed

    def _log_waldur_resource(self, waldur_resource, context: str = "") -> None:
        """
        Log all key/value attributes of a waldur_resource object for debugging.

        Args:
            waldur_resource: The Waldur resource object to inspect
            context: Context string to identify where this log is coming from
        """
        try:
            logger.info(f"[{context}] === WALDUR_RESOURCE DEBUG ===")
            logger.info(f"[{context}] Type: {type(waldur_resource)}")
            logger.info(f"[{context}] Type name: {type(waldur_resource).__name__}")

            # Log all attributes
            if hasattr(waldur_resource, '__dict__'):
                logger.info(f"[{context}] Attributes via __dict__:")
                for key, value in waldur_resource.__dict__.items():
                    logger.info(f"[{context}]   {key} = {value} (type: {type(value).__name__})")
            else:
                logger.info(f"[{context}] No __dict__ attribute available")

            # Log common expected attributes explicitly
            common_attrs = ['uuid', 'name', 'backend_id', 'state', 'description', 'offering', 'project', 'customer']
            logger.info(f"[{context}] Common attributes check:")
            for attr in common_attrs:
                if hasattr(waldur_resource, attr):
                    value = getattr(waldur_resource, attr)
                    logger.info(f"[{context}]   {attr} = {value} (type: {type(value).__name__})")
                else:
                    logger.info(f"[{context}]   {attr} = NOT PRESENT")

            # Log dir() output for completeness
            logger.info(f"[{context}] All available attributes (dir):")
            public_attrs = [attr for attr in dir(waldur_resource) if not attr.startswith('_')]
            logger.info(f"[{context}]   {', '.join(public_attrs)}")

            logger.info(f"[{context}] === END WALDUR_RESOURCE DEBUG ===")
        except Exception as e:
            logger.error(f"[{context}] Error logging waldur_resource: {e}", exc_info=True)

    def _extract_backend_id(self, waldur_resource) -> str:
        """
        Extract or generate backend_id from waldur_resource.

        This helper ensures consistent backend_id extraction across all methods.

        Args:
            waldur_resource: Waldur resource object

        Returns:
            The backend_id string to use for OpenStack project name, or empty string if unavailable
        """
        # Case 1: backend_id already set by Waldur (used during delete/update operations)
        if hasattr(waldur_resource, 'backend_id') and waldur_resource.backend_id:
            backend_id = waldur_resource.backend_id
            logger.debug(f"[_extract_backend_id] Using existing backend_id: '{backend_id}' (length: {len(backend_id)})")
            return backend_id

        # Case 2: Generate backend_id from uuid (used during create operations)
        if hasattr(waldur_resource, 'uuid') and waldur_resource.uuid:
            backend_id = str(waldur_resource.uuid)
            logger.debug(f"[_extract_backend_id] Generated from UUID: '{backend_id}' (length: {len(backend_id)})")
            return backend_id

        # Case 3: Neither backend_id nor uuid available - return empty string
        # The caller should handle this by skipping the operation
        logger.warning(f"[_extract_backend_id] Resource has no backend_id or uuid - returning empty string")
        return ""

    def list_components(self) -> list[str]:
        """
        List available resource components.

        We don't track usage components.
        If integrating with Nova/Cinder, this would return ["vcpu", "ram", "storage"].

        Returns:
            List of component names
        """
        # Keystone doesn't track resource usage
        # Return empty list or components from backend_components config
        components = list(self.backend_components.keys()) if self.backend_components else []
        logger.debug(f"Available components: {components}")
        return components

    # ==================================================`======================
    # ORDER PROCESSING (Resource lifecycle)
    # ========================================================================

    def _pre_create_resource(self, waldur_resource, user_context: Optional[Dict] = None) -> None:
        """
        Pre-creation hook (no-op for OpenStack).

        This abstract method is required by BaseBackend but not needed for OpenStack.
        All project creation logic is handled by _create_resource_in_backend() which
        creates a single OpenStack project using the resource UUID as backend_id.

        Background:
            The BaseBackend framework calls both:
            1. _pre_create_resource() - Originally for Slurm "project" setup
            2. _create_resource_in_backend() - Originally for Slurm "allocation" under project

            For OpenStack's flat structure (Domain → Project), we only need step 2.
            We override _create_resource_in_backend() to create the project directly.

        Args:
            waldur_resource: Waldur resource object (unused)
            user_context: Optional user context (unused)
        """
        logger.debug(
            "[PRE_CREATE] No-op for OpenStack - project creation handled by _create_resource_in_backend()"
        )

    def _create_resource_in_backend(self, waldur_resource) -> str:
        """
        Create OpenStack project and return backend_id.

        This method overrides the BaseBackend implementation to adapt the Slurm-oriented
        framework to OpenStack's flat project structure. Instead of creating a hierarchical
        "allocation under project" (Slurm model), we create a single OpenStack project
        using the resource's UUID as the backend_id.

        Architecture:
            - Slurm: Customer → Project → Allocation (resource = allocation)
            - OpenStack: Domain → Project (resource = project)

        Strategy:
            1. Extract UUID from waldur_resource
            2. Create OpenStack project with UUID-based name
            3. Return UUID as backend_id for Waldur to track

        Args:
            waldur_resource: Waldur resource object (must have uuid attribute)

        Returns:
            backend_id (UUID string) to be stored in Waldur

        Raises:
            BackendError: If project creation fails or UUID is missing
        """
        try:
            logger.info("=" * 70)
            logger.info("[CREATE_RESOURCE] Creating OpenStack project")
            self._log_waldur_resource(waldur_resource, "CREATE_RESOURCE")

            # Extract UUID as backend_id (stable, unique identifier)
            if not hasattr(waldur_resource, 'uuid') or not waldur_resource.uuid:
                error_msg = (
                    "Cannot create resource: waldur_resource.uuid is missing. "
                    "UUID is required as the stable backend_id for OpenStack project naming."
                )
                logger.error(f"[CREATE_RESOURCE] ✗ FAILED - {error_msg}")
                logger.info("=" * 70)
                raise BackendError(error_msg)

            backend_id = str(waldur_resource.uuid)
            logger.info(f"[CREATE_RESOURCE] Backend ID (UUID): {backend_id}")

            # Validate and sanitize
            validate_backend_id(backend_id, "waldur_managed_project")
            project_name = sanitize_for_openstack(backend_id)

            if backend_id != project_name:
                logger.info(f"[CREATE_RESOURCE] Sanitized: '{backend_id}' → '{project_name}'")

            # Check if project already exists (idempotency)
            existing_project = self.client.get_project(project_name)
            if existing_project:
                logger.info(
                    f"[CREATE_RESOURCE] Project '{project_name}' already exists (id={existing_project.id})"
                )
                logger.info(f"[CREATE_RESOURCE] ✓ SUCCESS - Returning existing backend_id: {backend_id}")
                logger.info("=" * 70)
                return backend_id

            # Extract description from resource
            description = "Waldur managed project"
            if hasattr(waldur_resource, 'name') and waldur_resource.name:
                description = f"Waldur: {waldur_resource.name}"
            elif hasattr(waldur_resource, 'description') and waldur_resource.description:
                description = waldur_resource.description

            # Create project in OpenStack
            logger.info(f"[CREATE_RESOURCE] Creating project: '{project_name}'")
            logger.info(f"[CREATE_RESOURCE] Description: {description}")

            project = self.client.create_project(project_name, description)

            logger.info(f"[CREATE_RESOURCE] ✓ SUCCESS - Created OpenStack project:")
            logger.info(f"[CREATE_RESOURCE]   Project Name: {project_name}")
            logger.info(f"[CREATE_RESOURCE]   OpenStack ID: {project.id}")
            logger.info(f"[CREATE_RESOURCE]   Backend ID (returned to Waldur): {backend_id}")
            logger.info(f"[CREATE_RESOURCE]   Description: {description}")
            logger.info("=" * 70)

            return backend_id

        except BackendError:
            # Re-raise BackendError as-is
            raise
        except Exception as e:
            error_msg = f"Failed to create OpenStack project: {e}"
            logger.error(f"[CREATE_RESOURCE] ✗ FAILED - {error_msg}", exc_info=True)
            logger.info("=" * 70)
            raise BackendError(error_msg) from e

    def _collect_resource_limits(self, waldur_resource) -> tuple[dict, dict]:
        """
        Collect resource limits.

        NOTE: OpenStack Keystone does not manage resource quotas.
        Quota management requires integration with:
        - Nova (compute quotas: cores, instances, ram)
        - Cinder (storage quotas: volumes, snapshots, gigabytes)
        - Neutron (network quotas: networks, ports, routers)

        For a Keystone-only plugin, we return empty dicts.
        Future enhancement: Implement Nova/Cinder/Neutron clients for quota management.

        Args:
            waldur_resource: Waldur resource object

        Returns:
            Tuple of (backend_limits, waldur_limits) - both empty for Keystone-only
        """
        logger.debug("Quota management requires Nova/Cinder integration (future work)")
        return {}, {}

    def delete_resource(self, waldur_resource, **kwargs: str) -> None:
        """
        Delete OpenStack project.

        Args:
            waldur_resource: Waldur resource object (WaldurResource)
            **kwargs: Additional parameters (not used for OpenStack)

        Raises:
            BackendError: If deletion fails
        """
        try:
            logger.info("=" * 70)
            logger.info("[DELETE] Starting OpenStack project deletion")
            self._log_waldur_resource(waldur_resource, "DELETE")

            # Extract backend_id using helper method
            resource_backend_id = self._extract_backend_id(waldur_resource)

            logger.info(f"[DELETE] Resource backend_id: '{resource_backend_id}' (length: {len(resource_backend_id)})")

            # Guard: Skip if no backend_id
            if not resource_backend_id or not resource_backend_id.strip():
                logger.warning("[DELETE] SKIP - Resource has no backend_id, nothing to delete in OpenStack")
                logger.info("=" * 70)
                return

            # Validate backend_id
            validate_backend_id(resource_backend_id, "waldur_managed_project")
            project_name = sanitize_for_openstack(resource_backend_id)

            if resource_backend_id != project_name:
                logger.info(f"[DELETE] Sanitized project name: '{resource_backend_id}' → '{project_name}'")

            logger.info(f"[DELETE] Deleting OpenStack project: '{project_name}'")

            # Use BaseClient method
            result = self.client.delete_resource(project_name)

            logger.info(f"[DELETE] ✓ SUCCESS - {result}")
            logger.info("=" * 70)

        except Exception as e:
            error_msg = f"Error deleting project: {e}"
            logger.error(f"[DELETE] ✗ FAILED - {error_msg}", exc_info=True)
            logger.info("=" * 70)
            raise BackendError(error_msg) from e

    # ========================================================================
    # MEMBERSHIP SYNC (User synchronization)
    # ========================================================================

    def add_users_to_resource(
        self, resource_backend_id: str, user_ids: set[str], **kwargs: dict
    ) -> set[str]:
        """
        Add users to OpenStack project.

        This is the MAIN method for real-time user synchronization.
        Called when waldur-site-agent receives an "offering_user_added" event,
        Or when a user in team is updated (to confirm)
        Args:
            resource_backend_id: Backend ID (OpenStack project name) as string
            user_ids: Set of user identifiers (usernames)
            **kwargs: Additional parameters (email, role, etc.)

        Returns:
            Set of successfully added user IDs

        Raises:
            BackendError: If operation fails
        """
        logger.info(f"[DEBUG] ADD_USERS_TO_RESOURCE CALLED\n\n")
        logger.info(f"[DEBUG] Received resource_backend_id: {resource_backend_id}")
        logger.info(f"[DEBUG] USERS IDs TO ADD: {user_ids}")
        logger.info(f"[DEBUG] kwargs: {kwargs}")

        try:
            # Guard: Skip if no backend_id
            if not resource_backend_id or not resource_backend_id.strip():
                logger.warning("Skipping add_users : this resource has no backend_id")
                return set()

            validate_backend_id(resource_backend_id, "waldur_managed_project")
            project_name = sanitize_for_openstack(resource_backend_id)

            logger.info(f"Adding {len(user_ids)} user(s) to project: {project_name}")

            # Check if project exists - DO NOT CREATE IT FOR GOD SAKE!
            existing_resource = self.client.get_resource(project_name)
            if not existing_resource:
                error_msg = (
                    f"Project {project_name} not found in OpenStack! "
                    f"Projects should be created via _pre_create_resource(), not here. "
                    f"Skipping user sync."
                )
                logger.error(error_msg)
                raise BackendError(error_msg)

            added_users = set()

            for user_id in user_ids:
                try:
                    username = user_id
                    logger.info(f"  → Adding user '{username}' to project '{project_name}'")

                    # Use BaseClient method to create association
                    result = self.client.create_association(
                        username=username,
                        resource_id=project_name,
                    )

                    added_users.add(user_id)
                    logger.info(f"  ✓ {result}")

                except Exception as e:
                    logger.error(f"  ✗ Failed to add user '{user_id}': {e}", exc_info=True)

            logger.info(f"✓ Added {len(added_users)}/{len(user_ids)} users to {project_name}")
            return added_users

        except Exception as e:
            error_msg = f"Error adding users to project [{project_name}]: {e}"
            logger.error(error_msg, exc_info=True)
            raise BackendError(error_msg) from e

    def remove_users_from_resource(
        self, resource_backend_id: str, usernames: set[str]
    ) -> list[str]:
        """
        Remove users from OpenStack project.

        Called when waldur-site-agent receives an "offering_user_removed" event.

        Args:
            resource_backend_id: Backend ID (OpenStack project name) as string
            usernames: Set of user identifiers (usernames)

        Returns:
            List of successfully removed usernames

        Raises:
            BackendError: If operation fails
        """
        try:
            logger.info(f"[REMOVE_USERS] Received backend_id: {resource_backend_id}")

            # Guard: Skip if no backend_id
            if not resource_backend_id or not resource_backend_id.strip():
                logger.warning("Skipping remove_users: resource has no backend_id")
                return []

            validate_backend_id(resource_backend_id, "waldur_managed_project")
            project_name = sanitize_for_openstack(resource_backend_id)

            logger.info(f"Removing {len(usernames)} user(s) from project: {project_name}")

            # Check if project exists using BaseClient
            existing_resource = self.client.get_resource(project_name)
            if not existing_resource:
                logger.warning(f"Project {project_name} not found, nothing to remove")
                return []

            removed_users = []

            for username in usernames:
                try:
                    logger.info(f"  → Removing user '{username}' from project [{project_name}]")

                    # Use BaseClient method to delete association
                    result = self.client.delete_association(
                        username=username,
                        resource_id=project_name,
                    )

                    removed_users.append(username)
                    logger.info(f"  ✓ {result}")

                except Exception as e:
                    logger.error(f"  ✗ Failed to remove user '{username}' from project [{project_name}]: {e}", exc_info=True)

            logger.info(
                f"✓ Removed {len(removed_users)}/{len(usernames)} users from {project_name}"
            )
            return removed_users

        except Exception as e:
            error_msg = f"Error removing users from project [{project_name}]: {e}"
            logger.error(error_msg, exc_info=True)
            raise BackendError(error_msg) from e

    # ========================================================================
    # SLURM-SPECIFIC STUBS (Not Applicable to OpenStack)
    # ========================================================================

    def create_user_homedirs(self, usernames: set[str], umask: str = "0700") -> None:
        """
        NOT APPLICABLE to OpenStack Keystone.

        OpenStack manages virtual resources in the cloud, not Linux system users.
        Home directory creation is only relevant for HPC systems like Slurm.

        Args:
            usernames: Set of usernames
            umask: Umask for directory creation

        Note:
            This method logs a warning and returns without error to maintain
            compatibility with waldur-site-agent's workflow expectations.
        """
        logger.warning(
            f"create_user_homedirs() called for {len(usernames)} users. "
            f"This operation is not applicable to OpenStack Keystone. "
            f"OpenStack manages cloud users and projects, not Linux system users with home directories. "
            f"Ignoring this request."
        )
        # Don't raise exception - just log and skip to maintain compatibility

    # ========================================================================
    # RESOURCE STATE MANAGEMENT
    # ========================================================================

    def downscale_resource(self, resource_backend_id: str) -> bool:
        """
        Downscale resource (disable project).

        Args:
            resource_backend_id: Project identifier

        Returns:
            True if successful
        """
        project_name = sanitize_for_openstack(resource_backend_id)
        logger.info(f"Downscaling project: {project_name} (disabling)")
        return self.client.disable_project(project_name)

    def pause_resource(self, resource_backend_id: str) -> bool:
        """
        Pause resource (same as downscale for OpenStack).

        Args:
            resource_backend_id: Project identifier

        Returns:
            True if successful
        """
        return self.downscale_resource(resource_backend_id)

    def restore_resource(self, resource_backend_id: str) -> bool:
        """
        Restore resource (enable project).

        Args:
            resource_backend_id: Project identifier

        Returns:
            True if successful
        """
        project_name = sanitize_for_openstack(resource_backend_id)
        logger.info(f"Restoring project: {project_name} (enabling)")
        return self.client.enable_project(project_name)

    # ========================================================================
    # REPORTING
    # ========================================================================

    def _get_usage_report(self, resource_backend_ids: list[str]) -> dict:
        """
        Get usage report for resources.

        NOTE: OpenStack Keystone does not track resource usage.
        Usage tracking requires integration with:
        - Ceilometer (telemetry data collection)
        - Gnocchi (time-series database for metrics)
        - Or direct Nova/Cinder API queries for resource consumption

        For a Keystone-only plugin, we return empty usage reports.
        Future enhancement: Implement Ceilometer/Gnocchi integration for usage tracking.

        Args:
            resource_backend_ids: List of project identifiers

        Returns:
            Usage report dict (empty for Keystone-only)
        """
        logger.debug(
            f"Usage report requested for {len(resource_backend_ids)} projects. "
            f"Returning empty report (requires Ceilometer/Gnocchi integration)."
        )

        # Return empty report structure
        report = {}
        for backend_id in resource_backend_ids:
            report[backend_id] = {
                "users": {},
                "total": {},
                "components": {},
            }

        return report

    def get_resource_metadata(self, resource_backend_id: str) -> dict:
        """
        Get metadata for a resource.

        Args:
            resource_backend_id: Project identifier

        Returns:
            Metadata dict
        """
        project_name = sanitize_for_openstack(resource_backend_id)
        return self.client.get_project_metadata(project_name)


class OpenStackUsernameManagementBackend(AbstractUsernameManagementBackend):
    """
    OpenStack Keystone username management backend.

    This backend handles username generation and lookup for OpenStack Keystone.
    It integrates with Waldur's offering user model to provide username
    management functionality.
    """

    def __init__(self, backend_settings: Optional[Dict[str, Any]] = None):
        """
        Initialize the username management backend.

        Args:
            backend_settings: Optional configuration dictionary for backend initialization
        """
        self.backend_settings = backend_settings or {}
        try:
            # Initialize Keystone client and OpenStack client if settings provided
            if self.backend_settings:
                self.config = OpenStackConfig.from_backend_settings(self.backend_settings)
                self.keystone_client = KeystoneClient(self.config)
                self.client = OpenStackClient(self.keystone_client)
            else:
                self.keystone_client = None
                self.client = None
            logger.info("OpenStackUsernameManagementBackend initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize Keystone client: {e}")
            self.keystone_client = None
            self.client = None

    def generate_username(self, offering_user: OfferingUser) -> str:
        """
        Generate a username based on offering user details.

        The username is derived from the user's email address by taking the
        part before the @ symbol and sanitizing it for OpenStack requirements.

        Args:
            offering_user: The offering user object from Waldur

        Returns:
            Generated username

        Raises:
            ValueError: If username cannot be generated from provided data
        """
        try:
            # Extract email and use the local part as username
            if not offering_user.user_email:
                logger.error(f"Cannot generate username: no email provided for user {offering_user.uuid}")
                raise ValueError(f"No email address provided for user {offering_user.uuid}")

            # Extract local part of email (before @)
            email_local_part = offering_user.user_email.split("@")[0]

            # Sanitize for OpenStack naming requirements
            username = sanitize_for_openstack(email_local_part)

            if not username:
                raise ValueError(f"Email {offering_user.user_email} cannot be converted to valid username")

            logger.info(f"Generated username '{username}' for offering user {offering_user.uuid}")
            return username

        except Exception as e:
            error_msg = f"Failed to generate username for offering user {offering_user.uuid}: {e}"
            logger.error(error_msg, exc_info=True)
            raise

    def get_username(self, offering_user: OfferingUser) -> Optional[str]:
        """
        Get existing username from OpenStack Keystone by email lookup.

        This method searches for a user in Keystone that has the same email
        address as the offering user.

        Args:
            offering_user: The offering user object from Waldur

        Returns:
            Existing username if found, None otherwise
        """
        try:
            if not self.client:
                logger.debug(
                    f"OpenStack client not available, cannot lookup username for {offering_user.user_email}"
                )
                return None

            if not offering_user.user_email:
                logger.warning(f"No email provided for offering user {offering_user.uuid}")
                return None

            logger.debug(f"Looking up username in Keystone for email {offering_user.user_email}")

            # Query Keystone for users by email
            users = self.client.list_users(self.config.domain_name if self.config else None)

            for user in users:
                # Check if user email matches
                if hasattr(user, "email") and user.email == offering_user.user_email:
                    logger.info(
                        f"Found existing user '{user.name}' in Keystone for email {offering_user.user_email}"
                    )
                    return user.name

            logger.debug(f"No existing user found in Keystone for email {offering_user.user_email}")
            return None

        except Exception as e:
            logger.error(
                f"Error looking up username for {offering_user.user_email}: {e}",
                exc_info=True,
            )
            return None
