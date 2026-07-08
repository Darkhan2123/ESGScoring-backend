from rest_framework import serializers

from apps.core.serializers import absolute_url

from .models import (
    Badge,
    Challenge,
    ChallengeCompletion,
    ChallengeTeam,
    EcoProfile,
    UserBadge,
)


class ChallengeSerializer(serializers.ModelSerializer):
    requires_evidence = serializers.BooleanField(read_only=True)

    class Meta:
        model = Challenge
        fields = [
            'id',
            'title',
            'description',
            'frequency',
            'category',
            'base_xp',
            'verification_type',
            'requires_evidence',
            'is_active',
            'starts_at',
            'ends_at',
        ]


class CompleteChallengeSerializer(serializers.Serializer):
    evidence_image = serializers.ImageField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True, default='')


class ChallengeCompletionSerializer(serializers.ModelSerializer):
    challenge_title = serializers.CharField(source='challenge.title', read_only=True)
    challenge_frequency = serializers.CharField(source='challenge.frequency', read_only=True)
    evidence_image = serializers.SerializerMethodField()

    class Meta:
        model = ChallengeCompletion
        fields = [
            'id',
            'challenge',
            'challenge_title',
            'challenge_frequency',
            'period_start',
            'period_end',
            'evidence_image',
            'note',
            'status',
            'base_xp',
            'streak_multiplier',
            'xp_awarded',
            'streak_day',
            'completed_at',
        ]

    def get_evidence_image(self, obj):
        return absolute_url(obj.evidence_image, self.context.get('request'))


class BadgeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Badge
        fields = [
            'id',
            'key',
            'name',
            'description',
            'icon',
            'condition_type',
            'condition_value',
        ]


class UserBadgeSerializer(serializers.ModelSerializer):
    badge = BadgeSerializer(read_only=True)

    class Meta:
        model = UserBadge
        fields = [
            'id',
            'badge',
            'earned_at',
            'context',
        ]


class EcoProfileSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source='user.id', read_only=True)
    full_name = serializers.CharField(source='user.full_name', read_only=True)
    student_id = serializers.CharField(source='user.student_id', read_only=True)
    avatar = serializers.SerializerMethodField()

    class Meta:
        model = EcoProfile
        fields = [
            'user_id',
            'full_name',
            'student_id',
            'avatar',
            'total_xp',
            'current_level',
            'current_streak',
            'longest_streak',
            'completed_challenges_count',
            'last_completed_date',
        ]

    def get_avatar(self, obj):
        return absolute_url(obj.user.avatar, self.context.get('request'))


class EcoSummarySerializer(serializers.Serializer):
    profile = EcoProfileSerializer()
    rank = serializers.IntegerField()
    badges_count = serializers.IntegerField()


class LeaderboardEntrySerializer(serializers.ModelSerializer):
    rank = serializers.IntegerField(read_only=True)
    user_id = serializers.IntegerField(source='user.id', read_only=True)
    full_name = serializers.CharField(source='user.full_name', read_only=True)
    student_id = serializers.CharField(source='user.student_id', read_only=True)
    avatar = serializers.SerializerMethodField()

    class Meta:
        model = EcoProfile
        fields = [
            'rank',
            'user_id',
            'full_name',
            'student_id',
            'avatar',
            'total_xp',
            'current_level',
            'current_streak',
            'longest_streak',
            'completed_challenges_count',
        ]

    def get_avatar(self, obj):
        return absolute_url(obj.user.avatar, self.context.get('request'))


class ChallengeTeamSerializer(serializers.ModelSerializer):
    captain_name = serializers.CharField(source='captain.full_name', read_only=True)
    members_count = serializers.IntegerField(source='members.count', read_only=True)

    class Meta:
        model = ChallengeTeam
        fields = [
            'id',
            'name',
            'captain',
            'captain_name',
            'members_count',
            'is_active',
            'created_at',
        ]