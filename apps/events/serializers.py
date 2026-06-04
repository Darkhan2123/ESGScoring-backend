from rest_framework import serializers

from apps.core.serializers import resolve_image
from apps.users.models import User
from .models import Task, TaskParticipation


# ─── Task serializers ──────────────────────────────────────────────


class TaskListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing tasks."""

    organization_name = serializers.CharField(
        source='organization.name', read_only=True,
    )
    image = serializers.SerializerMethodField()
    participants_count = serializers.SerializerMethodField()
    registration_status = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            'id', 'title', 'description', 'organization_name', 'image',
            'points_reward', 'max_participants', 'participants_count',
            'registration_status', 'location', 'event_datetime', 'created_at',
        ]

    def get_image(self, obj):
        return resolve_image(obj, self.context.get('request'))

    def get_participants_count(self, obj):
        return obj.approved_count

    def get_registration_status(self, obj):
        if hasattr(obj, '_registration_status'):
            return obj._registration_status
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            participation = obj.participations.filter(student=request.user).first()
            return participation.status if participation else None
        return None


class TaskSerializer(serializers.ModelSerializer):
    """Full task output — without verification code (public view)."""

    organization_name = serializers.CharField(
        source='organization.name', read_only=True,
    )
    organization_id = serializers.IntegerField(
        source='organization.id', read_only=True,
    )
    image = serializers.SerializerMethodField()
    participants_count = serializers.SerializerMethodField()
    is_full = serializers.BooleanField(read_only=True)
    registration_status = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            'id', 'title', 'description', 'organization_id',
            'organization_name', 'image', 'points_reward', 'max_participants',
            'participants_count', 'is_full', 'registration_status', 'location', 'event_datetime', 'is_active',
            'created_at', 'updated_at',
        ]

    def get_image(self, obj):
        return resolve_image(obj, self.context.get('request'))

    def get_participants_count(self, obj):
        return obj.approved_count

    def get_registration_status(self, obj):
        if hasattr(obj, '_registration_status'):
            return obj._registration_status
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            participation = obj.participations.filter(student=request.user).first()
            return participation.status if participation else None
        return None


class TaskOrgSerializer(TaskSerializer):
    """Task output for org owner — includes verification code."""

    class Meta(TaskSerializer.Meta):
        fields = TaskSerializer.Meta.fields + ['verification_code']


class CreateTaskSerializer(serializers.Serializer):
    """Organization creates a new task."""

    title = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, default='')
    points_reward = serializers.IntegerField(min_value=1)
    max_participants = serializers.IntegerField(
        min_value=1, required=False, default=None,
    )
    location = serializers.CharField(max_length=255, required=False, default='')
    event_datetime = serializers.DateTimeField(required=False, default=None)
    image = serializers.ImageField(required=False, allow_null=True, default=None)

    def create(self, validated_data):
        organization = self.context['organization']
        return Task.objects.create(
            title=validated_data['title'],
            description=validated_data.get('description', ''),
            organization=organization,
            points_reward=validated_data['points_reward'],
            max_participants=validated_data.get('max_participants'),
            location=validated_data.get('location', ''),
            event_datetime=validated_data.get('event_datetime'),
            image=validated_data.get('image'),
        )


class UpdateTaskSerializer(serializers.ModelSerializer):
    """Organization updates their own task."""

    class Meta:
        model = Task
        fields = ['title', 'description', 'image', 'max_participants', 'location', 'event_datetime', 'is_active']


# ─── Participation serializers ─────────────────────────────────────


class ParticipationRequestSerializer(serializers.ModelSerializer):
    """Org views participation requests — shows student info."""

    student_name = serializers.CharField(
        source='student.full_name', read_only=True,
    )
    student_id = serializers.CharField(
        source='student.student_id', read_only=True,
    )
    student_email = serializers.CharField(
        source='student.email', read_only=True,
    )

    class Meta:
        model = TaskParticipation
        fields = [
            'id', 'student_name', 'student_id', 'student_email',
            'status', 'created_at',
        ]


class MyParticipationSerializer(serializers.ModelSerializer):
    """Student views their own participations — shows task info."""

    task_id = serializers.IntegerField(source='task.id', read_only=True)
    task_title = serializers.CharField(source='task.title', read_only=True)
    organization_name = serializers.CharField(
        source='task.organization.name', read_only=True,
    )
    image = serializers.SerializerMethodField()
    points_reward = serializers.IntegerField(
        source='task.points_reward', read_only=True,
    )
    event_datetime = serializers.DateTimeField(
        source='task.event_datetime', read_only=True,
    )

    class Meta:
        model = TaskParticipation
        fields = [
            'id', 'task_id', 'task_title', 'organization_name', 'image',
            'points_reward', 'event_datetime', 'status',
            'created_at', 'updated_at',
        ]

    def get_image(self, obj):
        return resolve_image(obj.task, self.context.get('request'))


class ApproveRejectSerializer(serializers.Serializer):
    """Org approves or rejects a participation request."""

    status = serializers.ChoiceField(
        choices=[
            TaskParticipation.Status.APPROVED,
            TaskParticipation.Status.REJECTED,
        ],
    )


class VerifyCodeSerializer(serializers.Serializer):
    """Student submits verification code to complete task."""

    code = serializers.CharField(max_length=8)


# ─── Leaderboard serializer ───────────────────────────────────────


class LeaderboardSerializer(serializers.ModelSerializer):
    """Leaderboard entry — student ranked by points."""

    class Meta:
        model = User
        fields = ['id', 'full_name', 'student_id', 'avatar', 'points']
