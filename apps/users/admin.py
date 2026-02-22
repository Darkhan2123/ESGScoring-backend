from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ['username', 'email', 'full_name', 'role', 'stars', 'student_id', 'is_active']
    list_filter = ['role', 'is_active']
    search_fields = ['username', 'email', 'full_name', 'student_id']

    fieldsets = UserAdmin.fieldsets + (
        ('ESG Fields', {
            'fields': ('role', 'full_name', 'student_id', 'phone', 'avatar', 'stars'),
        }),
    )

    add_fieldsets = UserAdmin.add_fieldsets + (
        ('ESG Fields', {
            'fields': ('role', 'full_name', 'student_id', 'email'),
        }),
    )
