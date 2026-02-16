"""
Configuration management for OpenStack backend.

This module handles backend_settings dictionary passed by waldur-site-agent.
The backend receives its configuration from the agent's YAML config file.

Configuration Flow:
    waldur-site-agent-config.yaml (provided file test-config.yaml)
    └── offerings[].backend_settings  # Dict passed to __init__
        └── OpenStackConfig.from_dict(backend_settings)
"""

import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass

from waldur_site_agent_openstack.utils import setup_plugin_logger

logger = logging.getLogger(__name__)
setup_plugin_logger(logger)


@dataclass
class OpenStackConfig:
    """
    Configuration for OpenStack Keystone backend.

    This configuration is extracted from backend_settings in the
    waldur-site-agent configuration file.

    Example in waldur-site-agent-config.yaml:
        offerings:
          - backend_type: "openstack"
            backend_settings:
              auth_url: "https://keystone.example.com:5000/v3"
              username: "admin"
              password: "secret"
              project_name: "admin"
              domain_name: "Default"
              default_role: "_member_"
              create_users_if_not_exist: true
    """

    # Required Keystone authentication settings
    auth_url: str
    username: str
    password: str

    # Optional authentication settings (with defaults)
    project_name: str = "admin"
    domain_name: str = "Default"
    user_domain_name: Optional[str] = "Default"
    project_domain_name: Optional[str] = "Default"
    region_name: Optional[str] = None
    interface: str = "public"
    verify_ssl: bool = True # to overwrite if needed with your own config file. 

    # User management settings
    default_role: str = "_member_"
    create_users_if_not_exist: bool = True
    sync_user_emails: bool = True
    user_enabled_by_default: bool = True

    # Retry settings
    max_retry_attempts: int = 2
    retry_delay_seconds: int = 5

    def __post_init__(self):
        """Set default domain names if not provided."""
        if self.user_domain_name is None:
            self.user_domain_name = self.domain_name
        if self.project_domain_name is None:
            self.project_domain_name = self.domain_name

    @classmethod
    def from_backend_settings(cls, backend_settings: Dict[str, Any]) -> "OpenStackConfig":
        """
        Create configuration from backend_settings dictionary.

        This is the main initialization method called by the backend.

        Args:
            backend_settings: Dictionary "backend_settings" entry from waldur-site-agent config file

        Returns:
            OpenStackConfig instance

        Raises:
            ValueError: If required settings are missing
        """
        required_fields = ["auth_url", "username", "password"]
        missing_fields = [field for field in required_fields if field not in backend_settings]

        if missing_fields:
            raise ValueError(
                f"Missing required OpenStack configuration fields in backend_settings: "
                f"{', '.join(missing_fields)}"
            )

        # Extract only valid configuration fields
        valid_fields = cls.__dataclass_fields__.keys()
        filtered_settings = {
            key: value
            for key, value in backend_settings.items()
            if key in valid_fields
        }

        return cls(**filtered_settings)

    def validate(self) -> bool:
        """
        Validate configuration parameters.

        Returns:
            True if configuration is valid

        Raises:
            ValueError: If configuration is invalid
        """
        # Validate URL format
        if not self.auth_url.startswith(("http://", "https://")):
            raise ValueError(
                f"Invalid auth_url format: {self.auth_url}."
                f"Please check your auth_url in config or env file and try again"
            )
        # Validate credentials are not empty
        if not self.username or not self.password:
            raise ValueError("Username and password cannot be empty")

        # Validate interface type
        valid_interfaces = ["public", "internal", "admin"]
        if self.interface not in valid_interfaces:
            raise ValueError(
                f"Invalid interface '{self.interface}'. "
                f"Must be one of: {', '.join(valid_interfaces)}"
            )

        # Validate numeric ranges
        if self.max_retry_attempts < 0:
            raise ValueError("max_retry_attempts must be non-negative")

        if self.retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds must be non-negative")

        logger.info("OpenStack configuration validated successfully")
        return True

    def get_keystone_auth_params(self) -> Dict[str, Any]:
        """
        Get authentication parameters for Keystone client.

        Returns:
            Dictionary with auth parameters for keystoneclient
        """
        return {
            "auth_url": self.auth_url,
            "username": self.username,
            "password": self.password,
            "project_name": self.project_name,
            "user_domain_name": self.user_domain_name,
            "project_domain_name": self.project_domain_name,
        }

    def sanitize_for_logging(self) -> Dict[str, Any]:
        """
        Get configuration dict with sensitive values masked for logging.

        Returns:
            Dictionary with masked sensitive values
        """
        return {
            "auth_url": self.auth_url,
            "username": self.username,
            "password": "***REDACTED***",
            "project_name": self.project_name,
            "domain_name": self.domain_name,
            "user_domain_name": self.user_domain_name,
            "project_domain_name": self.project_domain_name,
            "region_name": self.region_name,
            "interface": self.interface,
            "verify_ssl": self.verify_ssl,
            "max_retry_attempts": self.max_retry_attempts,
            "retry_delay_seconds": self.retry_delay_seconds,
            "default_role": self.default_role,
            "create_users_if_not_exist": self.create_users_if_not_exist,
            "sync_user_emails": self.sync_user_emails,
            "user_enabled_by_default": self.user_enabled_by_default,
        }
