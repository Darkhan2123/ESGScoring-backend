from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Badge, Challenge, ChallengeCompletion, UserBadge
from .serializers import (
    BadgeSerializer,
    ChallengeCompletionSerializer,
    ChallengeSerializer,
    CompleteChallengeSerializer,
    EcoSummarySerializer,
    LeaderboardEntrySerializer,
    UserBadgeSerializer,
)
from .services import (
    complete_challenge,
    get_challenge_stats,
    get_leaderboard,
    get_user_eco_summary,
)


def get_active_challenges_queryset():
    now = timezone.now()

    return Challenge.objects.filter(
        is_active=True,
    ).filter(
        Q(starts_at__isnull=True) | Q(starts_at__lte=now),
        Q(ends_at__isnull=True) | Q(ends_at__gte=now),
    )


class DailyChallengesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        challenges = get_active_challenges_queryset().filter(
            frequency=Challenge.Frequency.DAILY,
        )

        serializer = ChallengeSerializer(
            challenges,
            many=True,
            context={'request': request},
        )
        return Response(serializer.data)


class WeeklyChallengesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        challenges = get_active_challenges_queryset().filter(
            frequency=Challenge.Frequency.WEEKLY,
        )

        serializer = ChallengeSerializer(
            challenges,
            many=True,
            context={'request': request},
        )
        return Response(serializer.data)


class CompleteChallengeView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, challenge_id):
        challenge = get_object_or_404(Challenge, id=challenge_id)

        serializer = CompleteChallengeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            completion, earned_badges = complete_challenge(
                user=request.user,
                challenge=challenge,
                evidence_image=serializer.validated_data.get('evidence_image'),
                note=serializer.validated_data.get('note', ''),
            )
        except DjangoValidationError as error:
            return Response(
                {'detail': error.messages[0] if error.messages else str(error)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                'completion': ChallengeCompletionSerializer(
                    completion,
                    context={'request': request},
                ).data,
                'earned_badges': UserBadgeSerializer(
                    earned_badges,
                    many=True,
                    context={'request': request},
                ).data,
            },
            status=status.HTTP_201_CREATED,
        )


class EcoProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        summary = get_user_eco_summary(request.user)

        serializer = EcoSummarySerializer(
            summary,
            context={'request': request},
        )
        return Response(serializer.data)


class MyCompletionsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        completions = (
            ChallengeCompletion.objects
            .filter(user=request.user)
            .select_related('challenge')
            .order_by('-completed_at')
        )

        serializer = ChallengeCompletionSerializer(
            completions,
            many=True,
            context={'request': request},
        )
        return Response(serializer.data)


class MyBadgesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        badges = (
            UserBadge.objects
            .filter(user=request.user)
            .select_related('badge')
            .order_by('-earned_at')
        )

        serializer = UserBadgeSerializer(
            badges,
            many=True,
            context={'request': request},
        )
        return Response(serializer.data)


class AllBadgesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        badges = Badge.objects.filter(is_active=True)

        serializer = BadgeSerializer(
            badges,
            many=True,
            context={'request': request},
        )
        return Response(serializer.data)


class EcoLeaderboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        limit = request.query_params.get('limit', 10)

        try:
            limit = int(limit)
        except ValueError:
            limit = 10

        limit = min(max(limit, 1), 50)

        leaderboard = list(get_leaderboard(limit=limit))

        for index, profile in enumerate(leaderboard, start=1):
            profile.rank = index

        serializer = LeaderboardEntrySerializer(
            leaderboard,
            many=True,
            context={'request': request},
        )
        return Response(serializer.data)


class ChallengeStatsView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        return Response(get_challenge_stats())