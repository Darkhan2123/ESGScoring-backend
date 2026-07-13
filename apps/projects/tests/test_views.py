from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from apps.users.models import User
from apps.organizations.models import Organization
from apps.projects.models import Project

class ProjectViewTestCase(APITestCase):
    def setUp(self):
        # Create Users
        self.admin = User.objects.create_superuser(
            username='admin', email='admin@example.com', password='password', role=User.Role.ADMIN, full_name='Admin'
        )
        self.org_owner = User.objects.create_user(
            username='orgowner', email='org@example.com', password='password', role=User.Role.ORGANIZATION, full_name='Org Owner'
        )
        self.student = User.objects.create_user(
            username='student', email='student@example.com', password='password', role=User.Role.STUDENT, full_name='Student'
        )
        
        # Create Organization
        self.organization = Organization.objects.create(
            name='Test Organization', owner=self.org_owner, is_active=True
        )
        
        # Create Project
        self.project = Project.objects.create(
            title='Test Project',
            description='A test project',
            organization=self.organization,
            google_form_url='https://forms.google.com/example',
            points_reward=50,
            is_active=True,
        )

    # ProjectListView (Public)
    def test_project_list_success(self):
        self.client.force_authenticate(user=self.student)
        response = self.client.get(reverse('project_list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_project_list_unauthenticated(self):
        response = self.client.get(reverse('project_list'))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # ProjectDetailView (Public)
    def test_project_detail_success(self):
        self.client.force_authenticate(user=self.student)
        response = self.client.get(reverse('project_detail', kwargs={'project_id': self.project.id}))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_project_detail_not_found(self):
        self.client.force_authenticate(user=self.student)
        response = self.client.get(reverse('project_detail', kwargs={'project_id': 999}))

    # MyProjectsView (Org Owner)
    def test_my_projects_list_success(self):
        self.client.force_authenticate(user=self.org_owner)
        response = self.client.get(reverse('my_projects'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_my_projects_student_access(self):
        self.client.force_authenticate(user=self.student)
        response = self.client.get(reverse('my_projects'))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # MyProjectDetailView (Org Owner)
    def test_my_project_detail_success(self):
        self.client.force_authenticate(user=self.org_owner)
        response = self.client.get(reverse('my_project_detail', kwargs={'project_id': self.project.id}))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_my_project_detail_other_org(self):
        other_owner = User.objects.create_user(
            username='otherowner', email='other@example.com', password='password', role=User.Role.ORGANIZATION
        )
        other_org = Organization.objects.create(name='Other Org', owner=other_owner, is_active=True)
        other_project = Project.objects.create(
            title='Other Project', organization=other_org, google_form_url='https://forms.google.com/other', points_reward=10
        )
        
        self.client.force_authenticate(user=self.org_owner)
        response = self.client.get(reverse('my_project_detail', kwargs={'project_id': other_project.id}))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


    # ProjectVerifyView (Student)
    def test_project_verify_success(self):
        self.client.force_authenticate(user=self.student)
        response = self.client.post(
            reverse('project_verify', kwargs={'project_id': self.project.id}),
            {'code': self.project.verification_code}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_project_verify_invalid_code(self):
        self.client.force_authenticate(user=self.student)
        response = self.client.post(
            reverse('project_verify', kwargs={'project_id': self.project.id}),
            {'code': 'WRONGCODE'}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # AdminProjectListView (Admin)
    def test_admin_project_list_success(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(reverse('admin_project_list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_admin_project_list_unauthorized(self):
        self.client.force_authenticate(user=self.student)
        response = self.client.get(reverse('admin_project_list'))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # AdminProjectDetailView (Admin)
    def test_admin_project_detail_success(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(reverse('admin_project_detail', kwargs={'project_id': self.project.id}))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_admin_project_detail_unauthorized(self):
        self.client.force_authenticate(user=self.student)
        response = self.client.get(reverse('admin_project_detail', kwargs={'project_id': self.project.id}))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


    def test_project_list_method_not_allowed(self):
        self.client.force_authenticate(user=self.student)
        response = self.client.post(reverse('project_list'), {'title': 'New'})
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_project_detail_inactive(self):
        # 404 for inactive project
        self.project.is_active = False
        self.project.save()
        self.client.force_authenticate(user=self.student)
        response = self.client.get(reverse('project_detail', kwargs={'project_id': self.project.id}))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_my_projects_unauthenticated(self):
        response = self.client.get(reverse('my_projects'))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_my_project_detail_unauthenticated(self):
        response = self.client.get(reverse('my_project_detail', kwargs={'project_id': self.project.id}))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_project_verify_unauthorized(self):
        # Admin trying to verify
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            reverse('project_verify', kwargs={'project_id': self.project.id}),
            {'code': self.project.verification_code}
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_project_list_invalid_filter(self):
        self.client.force_authenticate(user=self.admin)
        # Assuming invalid filter returns 400 or just ignores, 
        # testing if it handles invalid param gracefully (e.g., non-existent org ID)
        response = self.client.get(reverse('admin_project_list') + '?organization=9999')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_admin_project_detail_patch_invalid_data(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.patch(
            reverse('admin_project_detail', kwargs={'project_id': self.project.id}),
            {'points_reward': -10} # Invalid data
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
