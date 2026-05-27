from django.contrib import admin

from .models import (
    DailyQuiz,
    DailyQuizQuestion,
    Question,
    QuizAnswer,
    QuizAttempt,
)


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ['id', 'text', 'correct_index', 'created_by', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_by']
    search_fields = ['text']
    raw_id_fields = ['created_by']


class DailyQuizQuestionInline(admin.TabularInline):
    model = DailyQuizQuestion
    extra = 0
    raw_id_fields = ['question']


@admin.register(DailyQuiz)
class DailyQuizAdmin(admin.ModelAdmin):
    list_display = ['id', 'date', 'created_by', 'is_published', 'created_at']
    list_filter = ['is_published', 'created_by']
    search_fields = ['date']
    raw_id_fields = ['created_by']
    inlines = [DailyQuizQuestionInline]


@admin.register(QuizAttempt)
class QuizAttemptAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'user', 'daily_quiz', 'status',
        'correct_count', 'points_awarded',
        'started_at', 'deadline_at', 'submitted_at',
    ]
    list_filter = ['status']
    search_fields = ['user__full_name', 'user__email']
    raw_id_fields = ['user', 'daily_quiz']
    readonly_fields = ['started_at', 'deadline_at']


@admin.register(QuizAnswer)
class QuizAnswerAdmin(admin.ModelAdmin):
    list_display = ['id', 'attempt', 'question', 'selected_index', 'is_correct']
    list_filter = ['is_correct']
    raw_id_fields = ['attempt', 'question']
