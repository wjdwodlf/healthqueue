from django.shortcuts import render, get_object_or_404
# equipment/views.py

from rest_framework import viewsets, status
# IsAuthenticated를 import 합니다.
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Equipment
from .serializers import EquipmentSerializer
from users.models import UserProfile
from reports.models import Report
from gyms.models import GymMembership, Gym
from workouts.models import Reservation

# 추가: SSE(Server-Sent Events) 지원을 위한 임포트
from django.http import StreamingHttpResponse, HttpResponse
import json
import time
from django.conf import settings
from rest_framework_simplejwt.backends import TokenBackend
from django.contrib.auth import get_user_model


class EquipmentViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    # use select_related for gym to avoid N+1 when serializer accesses gym.name
    queryset = Equipment.objects.all().select_related('gym')
    serializer_class = EquipmentSerializer

    def list(self, request, *args, **kwargs):
        """Override list to batch-compute waiting counts to avoid N+1 queries."""
        qs = self.get_queryset()
        # Evaluate QS to get ids
        equips = list(qs)
        equip_ids = [e.id for e in equips]

        # Batch query waiting counts
        from django.db.models import Count
        waiting_qs = Reservation.objects.filter(equipment_id__in=equip_ids, status='WAITING')\
            .values('equipment_id')\
            .annotate(waiting_count=Count('id'))
        waiting_map = {item['equipment_id']: item['waiting_count'] for item in waiting_qs}

        serializer = self.get_serializer(equips, many=True)
        data = serializer.data
        # attach waiting_count to each serialized item
        for item in data:
            try:
                eid = int(item.get('id'))
            except Exception:
                eid = None
            item['waiting_count'] = waiting_map.get(eid, 0)

        return Response(data)

    @action(detail=True, methods=['patch'], url_path='operational-state')
    def set_operational_state(self, request, pk=None):
        """
        운영자 전용: 운영자의 JWT 토큰, gym id, equipment id, 그리고 변경할 상태를 받아
        해당 기구의 운영 상태를 설정합니다.

        요청 바디 예시:
        {
            "gym_id": 1,
            "operational_state": "NORMAL"  # 또는 "MAINTENANCE"
        }
        """
        user = request.user
        # userprofile 존재 및 운영자 권한 확인
        try:
            profile = user.userprofile
        except UserProfile.DoesNotExist:
            return Response({"detail": "유효한 운영자 프로필이 필요합니다."}, status=status.HTTP_403_FORBIDDEN)

        if profile.role != 'OPERATOR':
            return Response({"detail": "운영자 권한이 필요합니다."}, status=status.HTTP_403_FORBIDDEN)

        equipment = self.get_object()

        gym_id = request.data.get('gym_id')
        new_state = request.data.get('operational_state')

        if gym_id is None:
            return Response({"detail": "gym_id를 제공해주세요."}, status=status.HTTP_400_BAD_REQUEST)

        # gym_id가 해당 기구의 gym과 일치하는지 확인
        if str(equipment.gym.id) != str(gym_id) and int(gym_id) != equipment.gym.id:
            return Response({"detail": "제공된 gym_id가 기구의 소속 헬스장과 일치하지 않습니다."}, status=status.HTTP_400_BAD_REQUEST)

        if new_state not in dict(Equipment.OPERATIONAL_STATE_CHOICES).keys():
            return Response({"detail": f"허용되지 않은 상태입니다. 허용값: {list(dict(Equipment.OPERATIONAL_STATE_CHOICES).keys())}"}, status=status.HTTP_400_BAD_REQUEST)

        equipment.operational_state = new_state
        equipment.save()

        serializer = self.get_serializer(equipment)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='managed')
    def managed_equipments(self, request):
        """
        운영자가 관리하는(소속된) 헬스장의 모든 기구와 각 기구의 운영 상태 및
        불편 신고(대기) 건수를 반환합니다.

        규칙(가정):
        - 운영자가 관리하는 헬스장 = user가 `Gym.owner`인 헬스장 OR
          `GymMembership` 테이블에서 status='APPROVED'로 등록된 헬스장
        - report_count는 현재 상태가 PENDING인 신고 건수로 집계합니다.
        """
        user = request.user
        try:
            profile = user.userprofile
        except UserProfile.DoesNotExist:
            return Response({"detail": "유효한 운영자 프로필이 필요합니다."}, status=status.HTTP_403_FORBIDDEN)

        if profile.role != 'OPERATOR':
            return Response({"detail": "운영자 권한이 필요합니다."}, status=status.HTTP_403_FORBIDDEN)

        # gyms where user is owner
        owner_gyms = Gym.objects.filter(owner=user).values_list('id', flat=True)
        # gyms where user is an approved member (관리자 성격으로 가입한 경우)
        member_gyms = GymMembership.objects.filter(user=user, status='APPROVED').values_list('gym_id', flat=True)

        gym_ids = set(list(owner_gyms) + list(member_gyms))

        equipments = Equipment.objects.filter(gym_id__in=gym_ids)

        results = []
        for eq in equipments:
            pending_reports = Report.objects.filter(equipment=eq, status='PENDING').count()
            results.append({
                'id': eq.id,
                'name': eq.name,
                'gym_id': eq.gym.id,
                'gym_name': eq.gym.name,
                'operational_state': eq.operational_state,
                'report_count': pending_reports,
            })

        return Response(results, status=status.HTTP_200_OK)


def equipment_stream(request):
    """
    Simple SSE endpoint that accepts either session-authenticated requests
    or an `access_token` query parameter (Simple JWT). This view will
    stream an initial snapshot of equipments as an SSE 'initial' event,
    then keep the connection alive by sending heartbeat events.

    NOTE: This is a simple implementation intended to enable the FE to
    open EventSource with a token-in-query. For production push updates
    you should integrate with Django Channels, Redis pub/sub or another
    async push mechanism to send updates when equipments change.
    """
    # Authenticate by token-in-query OR session/cookie
    token = request.GET.get('access_token')
    user = None
    if token:
        try:
            tb = TokenBackend(algorithm=settings.SIMPLE_JWT.get('ALGORITHM', 'HS256'), signing_key=settings.SIMPLE_JWT.get('SIGNING_KEY', settings.SECRET_KEY))
            payload = tb.decode(token, verify=True)
            user_id = payload.get('user_id') or payload.get('user')
            if not user_id:
                return HttpResponse(status=401)
            User = get_user_model()
            try:
                user = User.objects.get(pk=user_id)
            except User.DoesNotExist:
                return HttpResponse(status=401)
        except Exception as e:
            return HttpResponse(status=401)
    else:
        # Fall back to Django authentication (session/cookie)
        if request.user and request.user.is_authenticated:
            user = request.user
        else:
            return HttpResponse(status=401)

    def event_stream():
        # initial snapshot: send all equipments as a single event
        # Batch compute waiting counts to avoid N+1 queries
        from django.db.models import Count
        equipments = Equipment.objects.all()
        equip_ids = [eq.id for eq in equipments]
        
        waiting_qs = Reservation.objects.filter(equipment_id__in=equip_ids, status='WAITING')\
            .values('equipment_id')\
            .annotate(waiting_count=Count('id'))
        waiting_map = {item['equipment_id']: item['waiting_count'] for item in waiting_qs}
        
        serialized = []
        for eq in equipments:
            serialized.append({
                'id': str(eq.id),
                'name': eq.name,
                'type': getattr(eq, 'type', None),
                'status': getattr(eq, 'status', None),
                'image_url': getattr(eq, 'image_url', '') or getattr(eq, 'image', ''),
                'base_session_time_minutes': getattr(eq, 'base_session_time_minutes', None),
                'waiting_count': waiting_map.get(eq.id, 0),
            })

        yield f"event: initial\ndata: {json.dumps(serialized)}\n\n"
        # build last-seen snapshot to detect changes
        last_state = {item['id']: item for item in serialized}

        # poll interval (seconds) can be configured in settings; default to 5s for responsive updates
        poll_interval = getattr(settings, 'EQUIPMENT_SSE_POLL_INTERVAL_SECONDS', 5)

        try:
            while True:
                time.sleep(poll_interval)

                # Fetch current equipments and compare against last_state
                # Batch compute waiting counts here too
                current_equips = Equipment.objects.all()
                current_ids = [eq.id for eq in current_equips]
                waiting_qs = Reservation.objects.filter(equipment_id__in=current_ids, status='WAITING')\
                    .values('equipment_id')\
                    .annotate(waiting_count=Count('id'))
                waiting_map = {item['equipment_id']: item['waiting_count'] for item in waiting_qs}
                
                for eq in current_equips:
                    eq_id = str(eq.id)
                    waiting_count = waiting_map.get(eq.id, 0)
                    current_repr = {
                        'id': eq_id,
                        'name': eq.name,
                        'type': getattr(eq, 'type', None),
                        'status': getattr(eq, 'status', None),
                        'image_url': getattr(eq, 'image_url', '') or getattr(eq, 'image', ''),
                        'base_session_time_minutes': getattr(eq, 'base_session_time_minutes', None),
                        'waiting_count': waiting_count,
                    }

                    last = last_state.get(eq_id)
                    if last is None or last.get('status') != current_repr['status'] or last.get('waiting_count') != current_repr['waiting_count']:
                        # send an update event for this equipment
                        yield f"event: update\ndata: {json.dumps(current_repr)}\n\n"
                        last_state[eq_id] = current_repr

        except GeneratorExit:
            # client disconnected
            return

    response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    return response