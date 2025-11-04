from django.shortcuts import render
# users/views.py

from django.contrib.auth.models import User
from rest_framework import viewsets, generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from .serializers import UserSerializer, RegisterSerializer

class UserViewSet(viewsets.ModelViewSet):
    # 이 줄을 추가하여 '출입증 검사'를 설정합니다.
    permission_classes = [IsAuthenticated]
    queryset = User.objects.all()
    serializer_class = UserSerializer

# RegisterView는 누구나 접근해야 하므로 수정하지 않습니다.
class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = (AllowAny,)
    serializer_class = RegisterSerializer

# 현재 로그인한 사용자 정보를 가져오는 View
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_current_user(request):
    serializer = UserSerializer(request.user)
    return Response(serializer.data)