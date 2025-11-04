# users/serializers.py

from django.contrib.auth.models import User
from rest_framework import serializers, generics
from .models import UserProfile

# User 모델의 데이터를 JSON 형태로 번역할 Serializer
class UserSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    name = serializers.CharField(source='first_name', read_only=True)

    class Meta:
        model = User
        # API를 통해 보여줄 필드들을 지정합니다.
        fields = ['id', 'username', 'email', 'name', 'role', 'is_staff']

    def get_role(self, obj):
        # UserProfile에서 role 가져오기
        try:
            profile = obj.userprofile
            return profile.role
        except UserProfile.DoesNotExist:
            return 'MEMBER'

# 회원가입을 위한 Serializer를 새로 추가합니다.
class RegisterSerializer(serializers.ModelSerializer):
    # role 필드 추가 (write_only: 요청에서만 사용하고 응답에는 포함하지 않음)
    role = serializers.ChoiceField(
        choices=['MEMBER', 'OPERATOR'],
        default='MEMBER',
        write_only=True
    )
    # name 필드 추가 (선택적)
    name = serializers.CharField(max_length=150, required=False, write_only=True)

    class Meta:
        model = User
        fields = ['username', 'password', 'email', 'role', 'name']
        # password 필드는 API 응답에 포함되지 않도록 설정합니다.
        extra_kwargs = {'password': {'write_only': True}}

    def create(self, validated_data):
        # role과 name을 추출 (validated_data에서 제거)
        role = validated_data.pop('role', 'MEMBER')
        name = validated_data.pop('name', '')
        
        # Serializer의 create 메서드를 오버라이드하여 비밀번호를 해싱(암호화)합니다.
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password']
        )
        
        # 이름이 제공된 경우 User 모델에 저장
        if name:
            user.first_name = name
            user.save()
        
        # role이 'OPERATOR'인 경우 is_staff를 True로 설정
        if role == 'OPERATOR':
            user.is_staff = True
            user.save()
        
        # UserProfile 생성 (role 저장)
        from users.models import UserProfile
        UserProfile.objects.create(user=user, role=role)
        
        return user
    
class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            print("유효성 검사 실패:", serializer.errors)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        return super().post(request, *args, **kwargs)