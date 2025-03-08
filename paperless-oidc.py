# /// script
# dependencies = [
#   "requests",
#   "authlib",
# ]
# ///
#
# A shitty python script to demonstrate an oidc flow using allauth-headless and paperless-ngx
import threading
import urllib
from http.server import BaseHTTPRequestHandler
from http.server import HTTPServer

import requests
from authlib.common.security import generate_token
from authlib.integrations.requests_client import OAuth2Session

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

def run_server(port=9000):
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
session.get(PAPERLESS_URL)
csrf_token = session.cookies.get("csrftoken")
print("CSRF: "+csrf_token)

# Request headless config for provider id
response = session.get(PAPERLESS_URL + "_allauth/app/v1/config")
print("1. GET headless config: ",response.json())

# Select the first provider from the response
provider = response.json()["data"]["socialaccount"]["providers"][0]
print(provider)

"""
Obtaining the oidc provider endpoints should happen here.
"""


"""
Start of the oidc flow
"""
# 1. Discover OpenID Connect configuration
discovery_url = "https://auth.example.com/.well-known/openid-configuration"
oidc_config = requests.get(discovery_url).json()

# 2. Set up OAuth2 client
client_id = "paperless"
client_secret = "insecure_secret"
redirect_uri = "http://localhost:9000/callback/"
scope = "openid profile email"

client = OAuth2Session(client_id, redirect_uri=redirect_uri, scope=scope,
                       token_endpoint_auth_method="client_secret_post", code_challenge_method="S256")

# 3. Build the authorization URL and redirect the user
code_verifier = generate_token(48)
print(code_verifier)
code_verifier = "vGeeIkB3N4GYZWM9EbsMNOy6mw6hnLi5T274Bte2xrxe3qDv"
authorization_url, state = client.create_authorization_url(oidc_config["authorization_endpoint"],
                                                           code_verifier=code_verifier)
print("Go to this URL:", authorization_url)

# 4. Capture the callback
# Run the server in a separate thread to avoid blocking
server_thread = threading.Thread(target=run_server, kwargs={"port": 9000})
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
    client_secret=client_secret,
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
payload = {"provider": "authelia", "process": "login",
           "token": {"client_id": "paperless", "access_token": id_token,
                     "id_token": id_token},
           "csrfmiddlewaretoken": csrf_token}

response = session.post(PAPERLESS_URL + "_allauth/app/v1/auth/provider/token", headers=headers, json=payload)
print(response.status_code)
print(response.json())
