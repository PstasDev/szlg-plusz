from django.conf import settings
from django.core.checks import Tags, Warning, register

LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "[::1]", "testserver"}


@register(Tags.security)
def debug_on_public_host(app_configs, **kwargs):
    public_hosts = [host for host in settings.ALLOWED_HOSTS if host not in LOCAL_HOSTS]
    if settings.DEBUG and public_hosts:
        return [
            Warning(
                "DEBUG=True, de az ALLOWED_HOSTS nem csak helyi címeket tartalmaz "
                f"({', '.join(public_hosts)}).",
                hint=(
                    "Élesben állítsd a DEBUG=False értéket a .env fájlban: DEBUG mellett "
                    "a hibaoldalak a beállításokat is kiírják, a HTTPS-védelmek pedig kikapcsolnak."
                ),
                id="szlgplus.W001",
            )
        ]
    return []