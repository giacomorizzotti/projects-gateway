from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import attention, local, notify
from .checks import HISTORY_DAYS
from .models import CheckEvent, LocalScan, MonitorState, UrlCheck

RECENT_EVENTS = 100


class UrlCheckSerializer(serializers.ModelSerializer):
    project = serializers.SerializerMethodField()
    environment_name = serializers.CharField(source='environment.name')
    environment_kind = serializers.CharField(source='environment.kind')
    platform = serializers.SerializerMethodField()

    class Meta:
        model = UrlCheck
        fields = ['id', 'environment', 'environment_name', 'environment_kind', 'project', 'platform',
                  'url', 'state', 'since', 'failing_since', 'checked_at', 'status_code', 'response_ms', 'final_url',
                  'error', 'attempts', 'ips', 'dns_match', 'tls_expires_at', 'tls_error', 'tls_names',
                  'tls_elsewhere']

    def get_project(self, obj):
        p = obj.environment.project
        return {'slug': p.slug, 'name': p.name}

    def get_platform(self, obj):
        p = obj.environment.platform
        return {'slug': p.slug, 'name': p.name} if p else None


class CheckEventSerializer(serializers.ModelSerializer):
    project = serializers.SerializerMethodField()
    environment_name = serializers.CharField(source='environment.name')

    class Meta:
        model = CheckEvent
        fields = ['id', 'environment', 'environment_name', 'project', 'url', 'at', 'state', 'detail']

    def get_project(self, obj):
        p = obj.environment.project
        return {'slug': p.slug, 'name': p.name}


@api_view(['GET'])
def status(request):
    """Everything live in one answer: checks, recent events, backups, the local scan, what needs attention."""
    now = timezone.now()
    state = MonitorState.get()
    checks = UrlCheck.objects.select_related('environment__project', 'environment__platform')
    events = (CheckEvent.objects.filter(at__gte=now - timedelta(days=HISTORY_DAYS))
              .select_related('environment__project')[:RECENT_EVENTS])
    scan = LocalScan.objects.first()
    return Response({
        'monitor': {
            'every_minutes': settings.HEALTH_CHECK_MINUTES,
            'checks_ran_at': state.checks_ran_at,
            'checks_seconds': state.checks_seconds,
            'checks_count': state.checks_count,
            'checks_offline': state.checks_offline,
            'check_requested_at': state.check_requested_at,
            'history_days': HISTORY_DAYS,
            'scan_read_at': scan.read_at if scan else None,
            'scan_error': scan.error if scan else '',
            # Which channels are set up, never their settings.
            'notify_channels': notify.channels(),
            'notify_sent_at': state.notify_sent_at,
            'notify_error': state.notify_error,
        },
        'attention': attention.items(now),
        'checks': UrlCheckSerializer(checks, many=True).data,
        'events': CheckEventSerializer(events, many=True).data,
        'local': local.analyse(scan),
    })


@api_view(['POST'])
def check_now(request):
    """"Check now": the worker runs the checks within seconds (they can take a minute with
    retries, too long for a request). The page polls until checks_ran_at passes this time."""
    state = MonitorState.get()
    state.check_requested_at = timezone.now()
    state.save(update_fields=['check_requested_at'])
    return Response({'check_requested_at': state.check_requested_at}, status=202)
