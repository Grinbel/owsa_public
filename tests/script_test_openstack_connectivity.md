  #!/usr/bin/env python3
import requests
import json
from requests.auth import HTTPBasicAuth

# Your OpenStack credentials
# i concat v3/... at line 42 for the auth/tokens path
KEYSTONE_URL = "http://195.220.87.127:5000/"
USERNAME = "admin"
PASSWORD = "Zi94sTd7D4Wol6ubi7Yhz1tMZZc6ZTyjRNX8Vqkh"
PROJECT_NAME = "admin"
USER_DOMAIN_NAME = "Default"
PROJECT_DOMAIN_NAME = "Default"

print("=" * 60)
print("TEST 1: Authenticate with Keystone v3")
print("=" * 60)

# Test 1: Get token (Keystone v3 API)
auth_payload = {
  "auth": {
      "identity": {
          "methods": ["password"],
          "password": {
              "user": {
                  "name": USERNAME,
                  "domain": {"name": USER_DOMAIN_NAME},
                  "password": PASSWORD
              }
          }
      },
      "scope": {
          "project": {
              "name": PROJECT_NAME,
              "domain": {"name": PROJECT_DOMAIN_NAME}
          }
      }
  }
}

response = requests.post(
  f"{KEYSTONE_URL}/v3/auth/tokens",
  json=auth_payload,
  verify=False
)

print(f"Status Code: {response.status_code}")
print(f"Response Headers: {dict(response.headers)}")
print(f"Response Body: {json.dumps(response.json(), indent=2)}")

if response.status_code == 201:
  token = response.headers.get('X-Subject-Token')
  print(f"\n✓ Authentication successful!")
  print(f"Token: {token[:50]}...")

  print("\n" + "=" * 60)
  print("TEST 2: Get Domain List")
  print("=" * 60)

  # Test 2: Get domain list
  headers = {"X-Auth-Token": token}
  response = requests.get(
      f"{KEYSTONE_URL}/v3/domains",
      headers=headers,
      verify=False
  )
  print(f"Status Code: {response.status_code}")
  print(f"Response Body: {json.dumps(response.json(), indent=2)}")

  print("\n" + "=" * 60)
  print("TEST 3: Get Project List")
  print("=" * 60)

  # Test 3: Get project list
  response = requests.get(
      f"{KEYSTONE_URL}/v3/projects",
      headers=headers,
      verify=False
  )
  print(f"Status Code: {response.status_code}")
  print(f"Response Body: {json.dumps(response.json(), indent=2)}")

else:
  print(f"\n✗ Authentication failed!")

