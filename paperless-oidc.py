# /// script
# dependencies = [
#   "requests",
#   "authlib",
#   "rich",
# ]
# ///
#
# A shitty python script to demonstrate an oidc flow using allauth-headless and paperless-ngx
import threading
import urllib
from http.server import BaseHTTPRequestHandler
from http.server import HTTPServer
import webbrowser

import requests
from authlib.common.security import generate_token
from authlib.integrations.requests_client import OAuth2Session
from urllib.parse import urlparse
from rich import print
from urllib.parse import urlparse, parse_qs

"""
Ignore this, it's just to capture the callback
"""


class RequestHandler(BaseHTTPRequestHandler):
    captured_params = None  # Store the captured parameters

    def do_GET(self):
        if self.path.startswith("/callback"):
            # Parse query parameters
            parsed_url = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed_url.query)
            RequestHandler.captured_params = params

            # Respond to the request
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Parameters captured. You can close this page.")

            # Stop the server after capturing the parameters
            threading.Thread(target=self.server.shutdown).start()


def run_server(port=8001):
    server = HTTPServer(("localhost", port), RequestHandler)
    print(f"Server listening on http://localhost:{port}/callback")
    server.serve_forever()
    return RequestHandler.captured_params


"""
Obtain Provider from paperless
"""
PAPERLESS_URL = "http://localhost:8000/"

# Obtain CSRF Token from main site
session = requests.Session()
session.get(PAPERLESS_URL + "accounts/login")
csrf_token = session.cookies.get("csrftoken")
print("CSRF: " + csrf_token)

# Request headless config for provider id
response = session.get(PAPERLESS_URL + "_allauth/app/v1/config")
print("1. GET headless config: ", response.json())

# Select the first provider from the response
provider = response.json()["data"]["socialaccount"]["providers"][0]
print(provider)

"""
Get oidc provider url since the _allauth/browser/v1/auth/provider/redirect api endpoint doesn't work
"""
# response = session.post(
#     PAPERLESS_URL + f"/accounts/oidc/{provider['id']}/login/",
#     data={"csrfmiddlewaretoken": csrf_token},
#     allow_redirects=False,
# )
# print(response.status_code)
# print(response.headers)
#
# old_redirect = response.headers.get("Location")
# oidc_provder_url = urlparse(old_redirect).netloc

browser_entry_url = f"{PAPERLESS_URL}/_allauth/browser/v1/auth/provider/redirect"

entry = session.post(
    browser_entry_url,
    # headers={"X-CSRFToken": cookies["csrftoken"]},
    data={
        "provider": provider["id"],
        # My understanding is this is the redirect URL that allauth will
        # redirect to after the OIDC login is completed
        # "callback_url": "http://localhost:8001/callback",
        "callback_url": PAPERLESS_URL,
        "process": "login",
        "csrfmiddlewaretoken": csrf_token,
    },
    # cookies=cookies,
    allow_redirects=False,
)
entry.raise_for_status()
location = entry.headers["Location"]
print(location)
parsed = urlparse(location)
query = parse_qs(parsed.query)
print(query)

scope = query["scope"][0]
print(scope)


"""
Start our own oidc flow
"""
# 1. Discover OpenID Connect configuration
# discovery_url = f"https://{oidc_provder_url}/.well-known/openid-configuration"
# discovery_url = "https://authentik.gessinger.xyz/application/o/paperless-dev/.well-known/openid-configuration"
discovery_url = provider["server_url"]
print("Discovery URL: ", discovery_url)
oidc_config_res = requests.get(discovery_url)
oidc_config_res.raise_for_status()
oidc_config = oidc_config_res.json()

# 2. Set up OAuth2 client
# client_id = "paperless"  # configurable or hardcoded in app
client_id = provider["client_id"]
# scope = "openid profile email"  # configurable or hardcoded in app
redirect_uri = "http://localhost:8001/callback/"  # replace with app redirect


client = OAuth2Session(
    client_id, redirect_uri=redirect_uri, scope=scope, code_challenge_method="S256"
)

# 3. Build the authorization URL and redirect the user
code_verifier = generate_token(48)
authorization_url, state = client.create_authorization_url(
    oidc_config["authorization_endpoint"], code_verifier=code_verifier
)
print("Go to this URL:", authorization_url)
webbrowser.open(authorization_url)

# 4. Capture the callback
# Run the server in a separate thread to avoid blocking
server_thread = threading.Thread(target=run_server, kwargs={"port": 8001})
server_thread.start()

# Wait for the request and continue execution
while RequestHandler.captured_params is None:
    pass  # Wait for parameters to be captured

print("Captured Parameters:", RequestHandler.captured_params)
authorization_code = RequestHandler.captured_params["code"][0]
print("Authorization code", authorization_code)

# 4. Exchange the authorization code at the oidc token endpoint for the ID Token
token_response = client.fetch_token(
    oidc_config["token_endpoint"],
    code=authorization_code,
    code_verifier=code_verifier,
)

# 5. Decode and validate ID Token (validation skipped)
id_token = token_response["id_token"]

print("ID Token: ", id_token)

"""
Passing the ID Token to Django allauth
"""
headers = {
    "X-CSRFToken": csrf_token,  # CSRF token goes in the headers
    "Referer": PAPERLESS_URL,
}
payload = {
    "provider": provider["id"],
    "process": "login",
    "token": {"client_id": client_id, "access_token": id_token, "id_token": id_token},
    "csrfmiddlewaretoken": csrf_token,
}

response = session.post(
    PAPERLESS_URL + "_allauth/app/v1/auth/provider/token", headers=headers, json=payload
)
print(response.status_code)
payload = response.json()
print(payload)

token = payload["meta"]["access_token"]
print(token)

ui_settings = requests.get(
    f"{PAPERLESS_URL}/api/ui_settings/", headers={"Authorization": f"Token {token}"}
)
print(ui_settings.status_code)
ui_settings.raise_for_status()
print("SUCCESS")
# print(ui_settings.json())
