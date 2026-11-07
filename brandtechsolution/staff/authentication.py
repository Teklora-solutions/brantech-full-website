from django.utils import timezone
from rest_framework import authentication, exceptions

from .models import DeveloperApiKey


class DeveloperApiKeyAuthentication(authentication.BaseAuthentication):
    """Authenticate requests carrying a Teklora developer API key.

    Supported headers:
    1. Authorization: Bearer tkl_live_...
    2. Authorization: Api-Key tkl_live_...
    3. Authorization: Token tkl_live_...
    4. X-Teklora-Api-Key: tkl_live_...
    """

    def authenticate(self, request):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        api_key_header = request.META.get("HTTP_X_TEKLORA_API_KEY", "")

        raw_key = None
        if auth_header:
            parts = auth_header.split()
            if len(parts) == 2 and parts[0].lower() in ("bearer", "api-key", "token"):
                raw_key = parts[1]
        elif api_key_header:
            raw_key = api_key_header.strip()

        if not raw_key:
            return None

        if not raw_key.startswith(DeveloperApiKey.KEY_PREFIX):
            return None

        key_hash = DeveloperApiKey.hash_key(raw_key)
        try:
            api_key = DeveloperApiKey.objects.select_related("user").get(
                key_hash=key_hash, is_active=True
            )
        except DeveloperApiKey.DoesNotExist:
            raise exceptions.AuthenticationFailed("Invalid or revoked Teklora API key.")

        if api_key.expires_at and api_key.expires_at < timezone.now():
            raise exceptions.AuthenticationFailed("Teklora API key has expired.")

        if not api_key.user.is_active:
            raise exceptions.AuthenticationFailed("User account is inactive.")

        # Update last_used_at timestamp with a 60-second debounce
        now = timezone.now()
        if not api_key.last_used_at or (now - api_key.last_used_at).total_seconds() > 60:
            DeveloperApiKey.objects.filter(pk=api_key.pk).update(last_used_at=now)

        return (api_key.user, api_key)
