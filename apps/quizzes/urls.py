from django.urls import path

from .views import (
    DailyQuizAttemptsView,
    DailyQuizDetailView,
    DailyQuizListCreateView,
    MyAttemptsView,
    QuestionBulkCreateView,
    QuestionDetailView,
    QuestionListView,
    TodayForfeitView,
    TodayStartView,
    TodayStatusView,
    TodaySubmitView,
)

urlpatterns = [
    # Manager (admin / organization)
    path('questions/', QuestionListView.as_view(), name='quiz_question_list'),
    path('questions/bulk/', QuestionBulkCreateView.as_view(), name='quiz_question_bulk'),
    path('questions/<int:pk>/', QuestionDetailView.as_view(), name='quiz_question_detail'),

    path('daily/', DailyQuizListCreateView.as_view(), name='daily_quiz_list'),
    path('daily/<int:pk>/', DailyQuizDetailView.as_view(), name='daily_quiz_detail'),
    path('daily/<int:pk>/attempts/', DailyQuizAttemptsView.as_view(), name='daily_quiz_attempts'),

    # Student
    path('today/', TodayStatusView.as_view(), name='quiz_today_status'),
    path('today/start/', TodayStartView.as_view(), name='quiz_today_start'),
    path('today/submit/', TodaySubmitView.as_view(), name='quiz_today_submit'),
    path('today/forfeit/', TodayForfeitView.as_view(), name='quiz_today_forfeit'),
    path('my-attempts/', MyAttemptsView.as_view(), name='quiz_my_attempts'),
]
