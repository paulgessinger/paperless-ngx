from allauth.headless.tokens.sessions import SessionTokenStrategy
from django.http import HttpRequest
from typing import Optional
from django.contrib.sessions.backends.base import SessionBase
from rest_framework.authtoken.models import Token


class TokenStrategy(SessionTokenStrategy):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def create_access_token(self, request: HttpRequest) -> Optional[str]:
        token, _ = Token.objects.get_or_create(user=request.user)
        return token.key
