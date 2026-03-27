from django.contrib import admin

from .models import Task, TaskParticipation


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'organization', 'points_reward',
        'verification_code', 'is_active', 'created_at',
    ]
    list_filter = ['is_active', 'organization']
    search_fields = ['title', 'organization__name', 'verification_code']
    raw_id_fields = ['organization']
    readonly_fields = ['verification_code']


@admin.register(TaskParticipation)
class TaskParticipationAdmin(admin.ModelAdmin):
    list_display = ['student', 'task', 'status', 'created_at']
    list_filter = ['status']
    search_fields = [
        'student__full_name', 'student__email', 'task__title',
    ]
    raw_id_fields = ['task', 'student']
