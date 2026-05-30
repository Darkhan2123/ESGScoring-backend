from django.contrib import admin

from .models import Project


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ['title', 'organization', 'points_reward', 'is_active', 'created_at']
    list_filter = ['is_active', 'organization']
    search_fields = ['title', 'organization__name']
    raw_id_fields = ['organization']
    readonly_fields = ['verification_code']
