#!/usr/bin/env python3

# /// script
# dependencies = [
#   "requests",
#   "rich"
# ]
# ///

import requests
from rich import print
import webbrowser
from urllib.parse import urlparse, parse_qs

PAPERLESS_URL = "http://localhost:8000"
# OIDC provider key configured in allauth
provider = "authentik"

initial = requests.get(f"{PAPERLESS_URL}/accounts/login")
initial.raise_for_status()

cookies = initial.cookies

config = requests.get(f"{PAPERLESS_URL}/_allauth/app/v1/config")
print(config.json())

redirect_url = f"{PAPERLESS_URL}/_allauth/browser/v1/auth/provider/redirect"

entry = requests.post(
    redirect_url,
    headers={"X-CSRFToken": cookies["csrftoken"]},
    data={
        "provider": provider,
        # My understanding is this is the redirect URL that allauth will
        # redirect to after the OIDC login is completed
        # "callback_url": "http://localhost:8001/callback",
        "callback_url": PAPERLESS_URL,
        "process": "login",
        "csrfmiddlewaretoken": cookies["csrftoken"],
    },
    cookies=cookies,
    allow_redirects=False,
)
print(entry)
location = entry.headers["Location"]
print(location)
entry.raise_for_status()

parsed = urlparse(location)
print(parsed)
query = parse_qs(parsed.query)
print(query)

# webbrowser.open(location)
