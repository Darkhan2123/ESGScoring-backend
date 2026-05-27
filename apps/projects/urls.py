from django.urls import path

from .views import (
    AdminProjectDetailView,
    AdminProjectListView,
    MyProjectDetailView,
    MyProjectsView,
    ProjectDetailView,
    ProjectListView,
)

urlpatterns = [
    # Public (any authenticated user)
    path('', ProjectListView.as_view(), name='project_list'),
    path('my/', MyProjectsView.as_view(), name='my_projects'),
    path('my/<int:project_id>/', MyProjectDetailView.as_view(), name='my_project_detail'),
    path('<int:project_id>/', ProjectDetailView.as_view(), name='project_detail'),

    # Admin only
    path('admin/', AdminProjectListView.as_view(), name='admin_project_list'),
    path('admin/<int:project_id>/', AdminProjectDetailView.as_view(), name='admin_project_detail'),
]
