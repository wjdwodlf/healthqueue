from django.shortcuts import render
# users/views.py

from django.contrib.auth.models import User
from rest_framework import viewsets, generics
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.views import TokenObtainPairView # 기본 뷰
from .serializers import UserSerializer, RegisterSerializer, MyTokenObtainPairSerializer # 1단계에서 만든 Serializer 임포트

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

# 1. '우리만의 특별한 로그인 창구' 뷰를 만듭니다.
class MyTokenObtainPairView(TokenObtainPairView):
    # 2. 이 뷰가 '우리만의 특별한 토큰 생성기'를 사용하도록 설정합니다.
    serializer_class = MyTokenObtainPairSerializer