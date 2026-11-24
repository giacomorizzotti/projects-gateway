from django.conf import settings
from django.http import HttpResponse, JsonResponse


def health(request):
    """Unauthenticated liveness check, for Docker and monitoring."""
    return JsonResponse({'status': 'ok'})


def spa_index(request):
    """Every non-API route belongs to the Vue app: answer with its index.html."""
    index = settings.FRONTEND_DIST / 'index.html'
    if not index.is_file():
        return HttpResponse('Frontend not built (run npm run build in frontend/).', status=503,
                            content_type='text/plain')
    return HttpResponse(index.read_bytes(), content_type='text/html')
