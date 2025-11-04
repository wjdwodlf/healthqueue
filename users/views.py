from django.shortcuts import render
# users/views.py

from django.contrib.auth.models import User
from rest_framework import viewsets, generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView
from .serializers import UserSerializer, RegisterSerializer
from .models import UserProfile
import logging

logger = logging.getLogger(__name__)

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

# JWT 토큰에 사용자 정보(role, username, name) 추가
class MyTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        
        # 토큰에 사용자 정보 추가
        token['username'] = user.username
        token['name'] = user.first_name or user.username
        
        # UserProfile에서 role 가져오기
        try:
            profile = user.userprofile
            token['role'] = profile.role
        except UserProfile.DoesNotExist:
            token['role'] = 'MEMBER'
        
        return token
    
    def validate(self, attrs):
        import sys
        data = super().validate(attrs)
        
        # 응답에 사용자 정보 추가 (id, username, name, role)
        data['id'] = self.user.id
        data['username'] = self.user.username
        data['name'] = self.user.first_name or self.user.username
        
        # UserProfile에서 role 가져오기
        try:
            profile = self.user.userprofile
            data['role'] = profile.role
            
            # 로그 출력 (여러 방식 동시 사용)
            log_msg = f"[LOGIN SUCCESS] id={self.user.id} | username={self.user.username} | role={profile.role} | is_staff={self.user.is_staff} | is_superuser={self.user.is_superuser}"
            print(log_msg, flush=True)
            sys.stdout.flush()
            logger.info(log_msg)
            
        except UserProfile.DoesNotExist:
            data['role'] = 'MEMBER'
            
            # 로그 출력
            log_msg = f"[LOGIN WARNING] id={self.user.id} | username={self.user.username} | NO PROFILE | is_staff={self.user.is_staff} | is_superuser={self.user.is_superuser}"
            print(log_msg, flush=True)
            sys.stdout.flush()
            logger.warning(log_msg)
        
        # 최종 응답 로그
        response_log = f"[LOGIN RESPONSE] {data}"
        print(response_log, flush=True)
        sys.stdout.flush()
        logger.info(response_log)
        
        return data

class MyTokenObtainPairView(TokenObtainPairView):
    serializer_class = MyTokenObtainPairSerializer