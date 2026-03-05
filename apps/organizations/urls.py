from django.urls import path

from .views import (
    OrganizationListView,
    OrganizationDetailView,
    MyOrganizationView,
    AdminCreateOrganizationView,
    AdminOrganizationListView,
    AdminOrganizationDetailView,
)

urlpatterns = [
    # Public (any authenticated user)
    path('', OrganizationListView.as_view(), name='organization_list'),
    path('my/', MyOrganizationView.as_view(), name='my_organization'),
    path('<int:org_id>/', OrganizationDetailView.as_view(), name='organization_detail'),

    # Admin only
    path('admin/create/', AdminCreateOrganizationView.as_view(), name='admin_create_organization'),
    path('admin/', AdminOrganizationListView.as_view(), name='admin_organization_list'),
    path('admin/<int:org_id>/', AdminOrganizationDetailView.as_view(), name='admin_organization_detail'),
]
