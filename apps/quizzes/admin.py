from django.contrib import admin

from .models import (
    AttemptQuestion,
    DailyQuiz,
    Question,
    QuizAnswer,
    QuizAttempt,
)


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'text', 'question_type', 'answer', 'correct_index',
        'created_by', 'is_active', 'created_at',
    ]
    list_filter = ['question_type', 'is_active', 'created_by']
    search_fields = ['text']
    raw_id_fields = ['created_by']


@admin.register(DailyQuiz)
class DailyQuizAdmin(admin.ModelAdmin):
    list_display = ['id', 'date', 'created_at']
    search_fields = ['date']


class AttemptQuestionInline(admin.TabularInline):
    model = AttemptQuestion
    extra = 0
    raw_id_fields = ['question']


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
    inlines = [AttemptQuestionInline]


@admin.register(QuizAnswer)
class QuizAnswerAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'attempt', 'question',
        'selected_index', 'selected_bool', 'is_correct',
    ]
    list_filter = ['is_correct']
    raw_id_fields = ['attempt', 'question']
