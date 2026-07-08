from django.contrib import admin

from .models import (
    Badge,
    Challenge,
    ChallengeCompletion,
    ChallengeTeam,
    ChallengeTeamMembership,
    EcoLevel,
    EcoProfile,
    UserBadge,
)


@admin.register(EcoLevel)
class EcoLevelAdmin(admin.ModelAdmin):
    list_display = ['level_number', 'title', 'required_xp', 'created_at']
    search_fields = ['title']
    ordering = ['level_number']


@admin.register(Challenge)
class ChallengeAdmin(admin.ModelAdmin):
    list_display = [
        'title',
        'frequency',
        'category',
        'base_xp',
        'verification_type',
        'is_active',
    ]
    list_filter = ['frequency', 'category', 'verification_type', 'is_active']
    search_fields = ['title', 'description']
    ordering = ['frequency', 'category', 'title']


@admin.register(EcoProfile)
class EcoProfileAdmin(admin.ModelAdmin):
    list_display = [
        'user',
        'total_xp',
        'current_level',
        'current_streak',
        'longest_streak',
        'completed_challenges_count',
        'last_completed_date',
    ]
    list_filter = ['current_level']
    search_fields = [
        'user__full_name',
        'user__email',
        'user__student_id',
    ]
    raw_id_fields = ['user']
    ordering = ['-total_xp']


@admin.register(ChallengeCompletion)
class ChallengeCompletionAdmin(admin.ModelAdmin):
    list_display = [
        'user',
        'challenge',
        'status',
        'xp_awarded',
        'streak_day',
        'period_start',
        'completed_at',
    ]
    list_filter = [
        'status',
        'challenge__frequency',
        'challenge__category',
        'period_start',
    ]
    search_fields = [
        'user__full_name',
        'user__email',
        'user__student_id',
        'challenge__title',
    ]
    raw_id_fields = ['user', 'challenge']
    readonly_fields = ['completed_at', 'approved_at', 'rejected_at']
    ordering = ['-completed_at']


@admin.register(Badge)
class BadgeAdmin(admin.ModelAdmin):
    list_display = [
        'name',
        'key',
        'condition_type',
        'condition_value',
        'is_active',
    ]
    list_filter = ['condition_type', 'is_active']
    search_fields = ['name', 'key', 'description']
    ordering = ['condition_type', 'condition_value']


@admin.register(UserBadge)
class UserBadgeAdmin(admin.ModelAdmin):
    list_display = ['user', 'badge', 'earned_at']
    list_filter = ['badge__condition_type', 'earned_at']
    search_fields = [
        'user__full_name',
        'user__email',
        'user__student_id',
        'badge__name',
    ]
    raw_id_fields = ['user', 'badge']
    readonly_fields = ['earned_at']
    ordering = ['-earned_at']


@admin.register(ChallengeTeam)
class ChallengeTeamAdmin(admin.ModelAdmin):
    list_display = ['name', 'captain', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = [
        'name',
        'captain__full_name',
        'captain__email',
    ]
    raw_id_fields = ['captain']
    readonly_fields = ['created_at']
    ordering = ['name']


@admin.register(ChallengeTeamMembership)
class ChallengeTeamMembershipAdmin(admin.ModelAdmin):
    list_display = ['user', 'team', 'role', 'joined_at']
    list_filter = ['role', 'joined_at']
    search_fields = [
        'user__full_name',
        'user__email',
        'team__name',
    ]
    raw_id_fields = ['user', 'team']
    readonly_fields = ['joined_at']
    ordering = ['-joined_at']