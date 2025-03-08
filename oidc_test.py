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

url = "http://localhost:8000"

initial = requests.get(f"{url}/accounts/login")
initial.raise_for_status()

cookies = initial.cookies

config = requests.get(f"{url}/_allauth/app/v1/config")
print(config.json())
# print(config.headers)

redirect_url = f"{url}/_allauth/browser/v1/auth/provider/redirect"

# redirect_initial = requests.get(redirect_url)
# csrftoken = redirect_initial.cookies["csrftoken"]
# print(f"csrftoken: {csrftoken}")

entry = requests.post(
    redirect_url,
    headers={"X-CSRFToken": cookies["csrftoken"]},
    data={
        "provider": "authentik",
        "callback_url": "http://localhost:8001/callback",
        "process": "login",
        "csrfmiddlewaretoken": cookies["csrftoken"],
    },
    cookies=cookies,
    allow_redirects=False,
)
print(entry)
print(entry.headers.get("Location"))
entry.raise_for_status()

webbrowser.open(entry.headers.get("Location"))
