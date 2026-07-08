from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class EcoLevel(models.Model):
    level_number = models.PositiveSmallIntegerField(unique=True)
    title = models.CharField(max_length=100)
    required_xp = models.PositiveIntegerField(validators=[MinValueValidator(0)])

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'challenge_levels'
        ordering = ['level_number']

    def __str__(self):
        return f'Level {self.level_number}: {self.title}'


class Challenge(models.Model):
    class Frequency(models.TextChoices):
        DAILY = 'daily', 'Daily'
        WEEKLY = 'weekly', 'Weekly'

    class Category(models.TextChoices):
        TRANSPORT = 'transport', 'Transport'
        WASTE = 'waste', 'Waste'
        ENERGY = 'energy', 'Energy'
        ACTIVITY = 'activity', 'Activity'
        CAMPUS = 'campus', 'Campus'
        OTHER = 'other', 'Other'

    class VerificationType(models.TextChoices):
        NONE = 'none', 'No evidence'
        CAMERA_PHOTO = 'camera_photo', 'Camera photo'
        SCREENSHOT = 'screenshot', 'Screenshot'

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    frequency = models.CharField(
        max_length=20,
        choices=Frequency.choices,
        default=Frequency.DAILY,
    )
    category = models.CharField(
        max_length=20,
        choices=Category.choices,
        default=Category.OTHER,
    )

    base_xp = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    verification_type = models.CharField(
        max_length=20,
        choices=VerificationType.choices,
        default=VerificationType.NONE,
    )

    is_active = models.BooleanField(default=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'challenges'
        ordering = ['frequency', 'category', 'title']
        indexes = [
            models.Index(fields=['frequency', 'is_active']),
            models.Index(fields=['category']),
        ]

    def __str__(self):
        return f'{self.title} ({self.frequency})'

    @property
    def requires_evidence(self):
        return self.verification_type != self.VerificationType.NONE


class EcoProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='eco_profile',
    )

    total_xp = models.PositiveIntegerField(default=0)
    current_level = models.PositiveSmallIntegerField(default=1)

    current_streak = models.PositiveIntegerField(default=0)
    longest_streak = models.PositiveIntegerField(default=0)
    last_completed_date = models.DateField(null=True, blank=True)

    completed_challenges_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'eco_profiles'
        ordering = ['-total_xp']

    def __str__(self):
        return f'{self.user} — {self.total_xp} XP'


class ChallengeCompletion(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='challenge_completions',
    )
    challenge = models.ForeignKey(
        Challenge,
        on_delete=models.CASCADE,
        related_name='completions',
    )

    period_start = models.DateField()
    period_end = models.DateField()

    evidence_image = models.ImageField(
        upload_to='challenge_evidence/%Y/%m/%d/',
        null=True,
        blank=True,
    )
    note = models.TextField(blank=True)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.APPROVED,
    )

    base_xp = models.PositiveIntegerField(default=0)
    streak_multiplier = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal('1.00'),
    )
    xp_awarded = models.PositiveIntegerField(default=0)
    streak_day = models.PositiveIntegerField(default=0)

    completed_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'challenge_completions'
        ordering = ['-completed_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'challenge', 'period_start'],
                name='unique_challenge_completion_per_period',
            ),
        ]
        indexes = [
            models.Index(fields=['user', 'period_start']),
            models.Index(fields=['challenge', 'period_start']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f'{self.user} - {self.challenge.title}'


class Badge(models.Model):
    class ConditionType(models.TextChoices):
        TOTAL_XP = 'total_xp', 'Total XP'
        LEVEL = 'level', 'Level'
        STREAK = 'streak', 'Streak'
        COMPLETIONS = 'completions', 'Completions'
        DAILY_COMPLETIONS = 'daily_completions', 'Daily completions'
        WEEKLY_COMPLETIONS = 'weekly_completions', 'Weekly completions'
        SINGLE_ACTION_XP = 'single_action_xp', 'Single action XP'
        SPECIAL = 'special', 'Special'

    key = models.SlugField(max_length=80, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, blank=True)

    condition_type = models.CharField(
        max_length=30,
        choices=ConditionType.choices,
        default=ConditionType.SPECIAL,
    )
    condition_value = models.PositiveIntegerField(default=1)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'challenge_badges'
        ordering = ['condition_type', 'condition_value']

    def __str__(self):
        return self.name


class UserBadge(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='eco_badges',
    )
    badge = models.ForeignKey(
        Badge,
        on_delete=models.CASCADE,
        related_name='earned_by',
    )

    earned_at = models.DateTimeField(auto_now_add=True)
    context = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'user_challenge_badges'
        ordering = ['-earned_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'badge'],
                name='unique_user_challenge_badge',
            ),
        ]

    def __str__(self):
        return f'{self.user} - {self.badge.name}'


class ChallengeTeam(models.Model):
    name = models.CharField(max_length=120)
    captain = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='captained_challenge_teams',
    )
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through='ChallengeTeamMembership',
        related_name='challenge_teams',
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'challenge_teams'
        ordering = ['name']

    def __str__(self):
        return self.name


class ChallengeTeamMembership(models.Model):
    class Role(models.TextChoices):
        CAPTAIN = 'captain', 'Captain'
        MEMBER = 'member', 'Member'

    team = models.ForeignKey(
        ChallengeTeam,
        on_delete=models.CASCADE,
        related_name='memberships',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='challenge_team_memberships',
    )

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.MEMBER,
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'challenge_team_memberships'
        ordering = ['joined_at']
        constraints = [
            models.UniqueConstraint(
                fields=['team', 'user'],
                name='unique_challenge_team_member',
            ),
        ]

    def __str__(self):
        return f'{self.user} - {self.team}'