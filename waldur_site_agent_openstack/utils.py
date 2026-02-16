"""
Utility functions for OpenStack plugin.

This module provides helper functions for:
- Retry logic with exponential backoff
- Logging formatters
- Data validation
- Connection testing
"""

import logging
import time
import functools
from typing import Callable, Any, Optional, TypeVar, cast
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def setup_plugin_logger(logger_instance: logging.Logger, level: int = logging.INFO) -> None:
    """
    Configure a logger with console handler for plugin visibility.

    This ensures plugin logs are visible even if waldur-site-agent
    hasn't configured handlers for plugin loggers.

    Args:
        logger_instance: The logger to configure
        level: Logging level (default: INFO)
    """
    logger_instance.setLevel(level)

    # Add console handler if not already present
    if not logger_instance.handlers:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)

        # Match waldur-site-agent's format
        # Note: %(msecs)03d provides milliseconds since %f is not supported in datefmt
        formatter = logging.Formatter(
            '[%(levelname)s] [%(asctime)s,%(msecs)03d] [%(name)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(formatter)
        logger_instance.addHandler(console_handler)

    # Prevent propagation to avoid duplicate logs
    logger_instance.propagate = False


# Configure the logger for this module
setup_plugin_logger(logger)

# Type variable for generic retry decorator
T = TypeVar('T')


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    exceptions: tuple = (Exception,)


def retry_on_exception(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    exceptions: tuple = (Exception,),
) -> Callable:
    """
    Decorator to retry a function on exception with exponential backoff.
    (Meaning that the retry process will wait more and more after each failure to prevent
    the retry from causing more damage.)

    Args:
        max_attempts: Maximum number of retry attempts
        base_delay: Initial delay between retries in seconds
        max_delay: Maximum delay between retries in seconds
        exponential_base: Base for exponential backoff calculation
        exceptions: Tuple of exception types to catch and retry

    Returns:
        Decorated function with retry logic

    Example:
        @retry_on_exception(max_attempts=3, base_delay=1.0)
        def connect_to_keystone():
            # Code that might fail
            pass
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception: Optional[Exception] = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt == max_attempts:
                        logger.error(
                                f"Function {func.__name__} failed after max attempts: {max_attempts} attempts: {e}"
                        )
                        raise

                    # Calculate delay with exponential backoff
                    delay = min(base_delay * (exponential_base ** (attempt - 1)), max_delay)

                    logger.warning(
                        f"Function {func.__name__} failed (attempt {attempt}/{max_attempts}): {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)

            # This should never be reached, but satisfies type checker
            if last_exception:
                raise last_exception
            raise RuntimeError("Unexpected retry logic error")

        return wrapper
    return decorator


def sanitize_for_openstack(name: str) -> str:
    """
    Sanitize a name for use in OpenStack.

    OpenStack has restrictions on project/user names:
    - Must start with alphanumeric
    - Can contain alphanumeric, dash, underscore, period
    - Cannot be only numbers

    Args:
        name: Original name to sanitize

    Returns:
        Sanitized name safe for OpenStack
    """
    import re

    # Replace spaces with underscores
    sanitized = name.replace(" ", "_")

    # Remove invalid characters
    sanitized = re.sub(r'[^a-zA-Z0-9_\-\.]', '', sanitized)

    # Ensure it doesn't start with non-alphanumeric
    sanitized = re.sub(r'^[^a-zA-Z0-9]+', '', sanitized)

    # Ensure it's not only numbers
    if sanitized.isdigit():
        sanitized = f"project_{sanitized}"

    # Ensure it's not empty
    if not sanitized:
        sanitized = "sanitizer_default_name"

    return sanitized


def validate_backend_id(backend_id: str, resource_type: str = "waldur_managed_resource") -> bool:
    """
    Valider un format de backend ID.

    Args:
        backend_id: The backend ID to validate
        resource_type: Type of resource for error messages

    Returns:
        True if valid

    Raises:
        ValueError: If backend_id is invalid
    """
    if not backend_id:
        raise ValueError(f"Backend ID validation ressource: {resource_type} backend_id cannot be empty")

    if not isinstance(backend_id, str):
        raise ValueError(f"{resource_type} backend_id must be a string")

    if len(backend_id) > 255:
        raise ValueError(f"{resource_type} backend_id is too long (max 255 characters)")

    return True


def format_openstack_error(exception: Exception) -> str:
    """
    Format an OpenStack exception for logging.

    Args:
        exception: The exception to format

    Returns:
        Formatted error message
    """
    error_msg = str(exception)

    # Extract HTTP status code if present
    if hasattr(exception, 'http_status'):
        status_code = getattr(exception, 'http_status')
        error_msg = f"[HTTP {status_code}] {error_msg}"

    # Extract details if present
    if hasattr(exception, 'details'):
        details = getattr(exception, 'details')
        if details:
            error_msg = f"\nERROR MESSAGE{error_msg}\nDETAILS: {details}"

    return error_msg


def get_safe_dict_value(data: dict, *keys: str, default: Any = None) -> Any:
    """
    Safely get a nested dictionary value.

    Args:
        data: The dictionary to query
        *keys: Keys to traverse (e.g., 'a', 'b', 'c' for data['a']['b']['c'])
        default: Default value if key not found

    Returns:
        The value if found, otherwise default

    Example:
        >>> data = {'user': {'profile': {'name': 'John'}}}
        >>> get_safe_dict_value(data, 'user', 'profile', 'name')
        'John'
        >>> get_safe_dict_value(data, 'user', 'missing', 'key', default='N/A')
        'N/A'
    """
    current = data
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    # en attendant de voir l'usage r�el.
    return current


class OpenStackConnectionTester:
    """
    Helper class for testing OpenStack connectivity.

    This is useful for health checks and diagnostics.
    """

    def __init__(self, config):
        """
        Initialize connection tester.

        Args:
            config: OpenStackConfig instance
        """
        self.config = config

    def test_keystone_reachability(self) -> tuple[bool, str]:
        """
        Test if Keystone endpoint is reachable.

        Returns:
            Tuple of (success, message de feedback/erreur)
        """
        import requests

        try:
            # Try to reach the Keystone endpoint
            response = requests.get(
                self.config.auth_url,
                timeout=10,
                verify=self.config.verify_ssl # normalement true par defaut
            )

            if response.status_code == 200:
                return True, f"Keystone reachable \nHTTP RESPONSE CODE: {response.status_code})"
            elif response.status_code < 500:
                return True, f"Keystone maybe reachable \nHTTP RESPONSE CODE: {response.status_code}"
            else:
                return False, f"Keystone returned error \nHTTP RESPONSE CODE: {response.status_code})"

        except requests.exceptions.ConnectionError as e:
            return False, f"Raised exception in test_keystone_reachability func.\nCannot connect to Keystone: {e}"
        except requests.exceptions.Timeout:
            return False, "Raised exception in test_keystone_reachability.\nConnection to Keystone timed out"
        except Exception as e:
            return False, f"Raised exception in test_keystone_reachability.\nUnexpected error testing Keystone: {e}"

    def test_authentication(self, client) -> tuple[bool, str]:
        """
        Test if authentication works.

        Args:
            client: KeystoneClient instance

        Returns:
            Tuple of (success, message)
        """
        try:
            token = client.get_token()
            if token:
                return True, f"Token returned, Authentication successful.\nToken:{token}"
            else:
                return False, "Authentication returned no token"
        except Exception as e:
            return False, f"Authentication failed in func test_authentication:\n{format_openstack_error(e)}"

    def run_full_diagnostics(self, client) -> dict[str, Any]:
        """
        Run full diagnostics and return results.

        Args:
            client: KeystoneClient instance

        Returns:
            Dictionary with diagnostic results
        """
        results = {
            "keystone_reachable": False,
            "authentication": False,
            "errors": [],
            "warnings": [],
        }


        # Test reachability
        reachable, msg = self.test_keystone_reachability()
        results["keystone_reachable"] = reachable
        print(f"full diagnostic\nReachable, msg: {reachable}, {msg}")
        if not reachable:
            results["errors"].append(msg)
            return results

        # Test authentication
        auth_ok, msg = self.test_authentication(client)
        results["authentication"] = auth_ok
        if not auth_ok:
            results["errors"].append(msg)
            return results

        # Test SSL certificate if enabled
        if self.config.verify_ssl:
            results["warnings"].append("SSL verification is enabled (good for production)")
        else:
            results["warnings"].append("⚠️  SSL verification is disabled (not recommended for production)")

        return results
