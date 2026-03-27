from django.urls import path

from .views import (
    TaskListView,
    TaskDetailView,
    LeaderboardView,
    JoinTaskView,
    VerifyTaskView,
    MyParticipationsView,
    CreateTaskView,
    TaskRequestsView,
    ManageRequestView,
    StudentHistoryView,
    AdminTaskListView,
    AdminDeactivateTaskView,
)

urlpatterns = [
    # Public (any authenticated user)
    path('tasks/', TaskListView.as_view(), name='task_list'),
    path('tasks/<int:task_id>/', TaskDetailView.as_view(), name='task_detail'),
    path('leaderboard/', LeaderboardView.as_view(), name='leaderboard'),

    # Student only
    path('tasks/<int:task_id>/join/', JoinTaskView.as_view(), name='join_task'),
    path('tasks/<int:task_id>/verify/', VerifyTaskView.as_view(), name='verify_task'),
    path('my-participations/', MyParticipationsView.as_view(), name='my_participations'),

    # Organization only
    path('tasks/create/', CreateTaskView.as_view(), name='create_task'),
    path('tasks/<int:task_id>/requests/', TaskRequestsView.as_view(), name='task_requests'),
    path('requests/<int:participation_id>/', ManageRequestView.as_view(), name='manage_request'),
    path('students/<int:student_id>/history/', StudentHistoryView.as_view(), name='student_history'),

    # Admin only
    path('admin/tasks/', AdminTaskListView.as_view(), name='admin_task_list'),
    path('admin/tasks/<int:task_id>/', AdminDeactivateTaskView.as_view(), name='admin_deactivate_task'),
]
