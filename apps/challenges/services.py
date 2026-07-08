from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, F
from django.utils import timezone

from apps.users.models import User

from .models import (
    Badge,
    Challenge,
    ChallengeCompletion,
    EcoLevel,
    EcoProfile,
    UserBadge,
)


def get_or_create_eco_profile(user):
    profile, _ = EcoProfile.objects.get_or_create(user=user)
    return profile


def get_period_range(challenge, current_date=None):
    current_date = current_date or timezone.localdate()

    if challenge.frequency == Challenge.Frequency.WEEKLY:
        period_start = current_date - timedelta(days=current_date.weekday())
        period_end = period_start + timedelta(days=6)
        return period_start, period_end

    return current_date, current_date


def get_streak_multiplier(streak):
    bonus = min(max(streak - 1, 0) * Decimal('0.03'), Decimal('0.50'))
    return Decimal('1.00') + bonus


def calculate_xp(base_xp, multiplier):
    value = Decimal(base_xp) * multiplier
    return int(value.to_integral_value(rounding=ROUND_HALF_UP))


def get_level_number(total_xp):
    level = (
        EcoLevel.objects
        .filter(required_xp__lte=total_xp)
        .order_by('-required_xp')
        .first()
    )

    if level:
        return level.level_number

    return 1


def update_streak(profile, current_date=None):
    current_date = current_date or timezone.localdate()

    if profile.last_completed_date == current_date:
        return profile.current_streak

    if profile.last_completed_date == current_date - timedelta(days=1):
        profile.current_streak += 1
    else:
        profile.current_streak = 1

    profile.longest_streak = max(profile.longest_streak, profile.current_streak)
    profile.last_completed_date = current_date

    return profile.current_streak


def award_badges(user, completion):
    profile = get_or_create_eco_profile(user)

    daily_count = ChallengeCompletion.objects.filter(
        user=user,
        challenge__frequency=Challenge.Frequency.DAILY,
        status=ChallengeCompletion.Status.APPROVED,
    ).count()

    weekly_count = ChallengeCompletion.objects.filter(
        user=user,
        challenge__frequency=Challenge.Frequency.WEEKLY,
        status=ChallengeCompletion.Status.APPROVED,
    ).count()

    badges = Badge.objects.filter(is_active=True)
    earned = []

    for badge in badges:
        is_earned = False

        if badge.condition_type == Badge.ConditionType.TOTAL_XP:
            is_earned = profile.total_xp >= badge.condition_value

        elif badge.condition_type == Badge.ConditionType.LEVEL:
            is_earned = profile.current_level >= badge.condition_value

        elif badge.condition_type == Badge.ConditionType.STREAK:
            is_earned = profile.longest_streak >= badge.condition_value

        elif badge.condition_type == Badge.ConditionType.COMPLETIONS:
            is_earned = profile.completed_challenges_count >= badge.condition_value

        elif badge.condition_type == Badge.ConditionType.DAILY_COMPLETIONS:
            is_earned = daily_count >= badge.condition_value

        elif badge.condition_type == Badge.ConditionType.WEEKLY_COMPLETIONS:
            is_earned = weekly_count >= badge.condition_value

        elif badge.condition_type == Badge.ConditionType.SINGLE_ACTION_XP:
            is_earned = completion.xp_awarded >= badge.condition_value

        if is_earned:
            user_badge, created = UserBadge.objects.get_or_create(
                user=user,
                badge=badge,
                defaults={
                    'context': {
                        'completion_id': completion.id,
                        'total_xp': profile.total_xp,
                        'streak': profile.current_streak,
                    }
                },
            )

            if created:
                earned.append(user_badge)

    return earned


@transaction.atomic
def complete_challenge(*, user, challenge, evidence_image=None, note=''):
    if not challenge.is_active:
        raise ValidationError('This challenge is not active.')

    if challenge.requires_evidence and not evidence_image:
        raise ValidationError('Evidence image is required for this challenge.')

    current_date = timezone.localdate()
    period_start, period_end = get_period_range(challenge, current_date)

    already_completed = ChallengeCompletion.objects.filter(
        user=user,
        challenge=challenge,
        period_start=period_start,
    ).exists()

    if already_completed:
        raise ValidationError('This challenge is already completed for this period.')

    profile = (
        EcoProfile.objects
        .select_for_update()
        .filter(user=user)
        .first()
    )

    if not profile:
        profile = EcoProfile.objects.create(user=user)

    streak_day = update_streak(profile, current_date)
    multiplier = get_streak_multiplier(streak_day)
    xp_awarded = calculate_xp(challenge.base_xp, multiplier)

    profile.total_xp += xp_awarded
    profile.completed_challenges_count += 1
    profile.current_level = get_level_number(profile.total_xp)
    profile.save(update_fields=[
        'total_xp',
        'current_level',
        'current_streak',
        'longest_streak',
        'last_completed_date',
        'completed_challenges_count',
        'updated_at',
    ])

    User.objects.filter(pk=user.pk).update(points=F('points') + xp_awarded)

    completion = ChallengeCompletion.objects.create(
        user=user,
        challenge=challenge,
        period_start=period_start,
        period_end=period_end,
        evidence_image=evidence_image,
        note=note,
        status=ChallengeCompletion.Status.APPROVED,
        base_xp=challenge.base_xp,
        streak_multiplier=multiplier,
        xp_awarded=xp_awarded,
        streak_day=streak_day,
        approved_at=timezone.now(),
    )

    earned_badges = award_badges(user, completion)

    return completion, earned_badges


def get_user_eco_summary(user):
    profile = get_or_create_eco_profile(user)

    rank = (
        EcoProfile.objects
        .filter(total_xp__gt=profile.total_xp)
        .count()
    ) + 1

    return {
        'profile': profile,
        'rank': rank,
        'badges_count': UserBadge.objects.filter(user=user).count(),
    }


def get_leaderboard(limit=10):
    return (
        EcoProfile.objects
        .select_related('user')
        .order_by('-total_xp', 'created_at')[:limit]
    )


def get_challenge_stats():
    return {
        'total_completions': ChallengeCompletion.objects.count(),
        'active_challenges': Challenge.objects.filter(is_active=True).count(),
        'participants': EcoProfile.objects.count(),
        'top_categories': (
            ChallengeCompletion.objects
            .values('challenge__category')
            .annotate(total=Count('id'))
            .order_by('-total')[:5]
        ),
    }