from rest_framework.decorators import api_view
from rest_framework.response import Response


@api_view(['GET'])
def me(request):
    user = request.user
    return Response({
        'id': user.id,
        'username': user.username,
        'name': user.get_full_name() or user.username,
    })
