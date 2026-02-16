"""
Waldur Site Agent __ OpenStack Plugin

This plugin provides real-time synchronization (In case you use event processing mode) of Waldur users to OpenStack Keystone.
It supports event-based processing for immediate updates via STOMP messaging.

Features:
- Automatic ser and role synchronization (membership_sync_backend)
- Event listening mode coming soon ....
- Project creation and deletion (order_processing_backend) coming soon ...
- Production-ready with retry logic and error handling

Usage:
    1. Install: pip install waldur-site-agent-openstack (read configuration doc of the agent)
    2. Configure in waldur-site-agent-config.yaml (provided test-config.yaml example)
    3. Run: waldur-site-agent run --mode [MODE] 
"""

__version__ = "0.1.0"
__author__ = "Grinbel"

from waldur_site_agent_openstack.backends import OpenStackBackend

__all__ = [
    "OpenStackBackend",
]
