"""
API endpoint tests for the events app.

These tests follow the strategy: 1 good case + 2 bad cases per endpoint.
"""
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.users.models import User
from apps.organizations.models import Organization
from apps.events.models import Task, TaskParticipation


TEST_CACHE = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'test-cache-events',
    }
}

TEST_SETTINGS = {
    'CACHES': TEST_CACHE,
    'CACHE_TTL_SCHOOLS': 300,
}

NO_THROTTLE_SETTINGS = {
    'CACHES': TEST_CACHE,
    'REST_FRAMEWORK': {
        'DEFAULT_AUTHENTICATION_CLASSES': (
            'rest_framework_simplejwt.authentication.JWTAuthentication',
        ),
        'DEFAULT_PERMISSION_CLASSES': (
            'rest_framework.permissions.IsAuthenticated',
        ),
        'DEFAULT_FILTER_BACKENDS': (
            'django_filters.rest_framework.DjangoFilterBackend',
            'rest_framework.filters.SearchFilter',
            'rest_framework.filters.OrderingFilter',
        ),
        'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
        'PAGE_SIZE': 20,
        'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
        'EXCEPTION_HANDLER': 'apps.core.exception_handler.custom_exception_handler',
        'DEFAULT_THROTTLE_CLASSES': [
            'rest_framework.throttling.AnonRateThrottle',
            'rest_framework.throttling.UserRateThrottle',
            'rest_framework.throttling.ScopedRateThrottle',
        ],
        'DEFAULT_THROTTLE_RATES': {
            'anon': None,
            'user': None,
            'auth': None,
            'quiz': None,
            'purchases': None,
        },
    }
}


@override_settings(**TEST_SETTINGS)
class EventAPITestCase(APITestCase):
    """Base test case with common setup for event API tests."""

    def setUp(self):
        cache.clear()

        # Create Users
        self.admin = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='password',
            role=User.Role.ADMIN,
            full_name='Admin User',
            is_superuser=True,
        )
        self.org_owner = User.objects.create_user(
            username='orgowner',
            email='org@example.com',
            password='password',
            role=User.Role.ORGANIZATION,
            full_name='Org Owner',
        )
        self.org_owner_other = User.objects.create_user(
            username='orgownerother',
            email='orgother@example.com',
            password='password',
            role=User.Role.ORGANIZATION,
            full_name='Other Org Owner',
        )
        self.org_without_org = User.objects.create_user(
            username='orgwithoutorg',
            email='orgwithoutorg@example.com',
            password='password',
            role=User.Role.ORGANIZATION,
            full_name='Org Owner Without Org Model',
        )
        self.student = User.objects.create_user(
            username='student',
            email='student@example.com',
            password='password',
            role=User.Role.STUDENT,
            full_name='Student User',
            student_id='STU001',
        )
        self.student2 = User.objects.create_user(
            username='student2',
            email='student2@example.com',
            password='password',
            role=User.Role.STUDENT,
            full_name='Student Two',
            student_id='STU002',
        )

        # Create Organizations
        self.organization = Organization.objects.create(
            name='Test Organization',
            owner=self.org_owner,
            is_active=True,
        )
        self.organization_other = Organization.objects.create(
            name='Other Organization',
            owner=self.org_owner_other,
            is_active=True,
        )

        # Create Tasks
        self.task = Task.objects.create(
            title='Test Task',
            description='A test task description',
            organization=self.organization,
            points_reward=50,
            max_participants=5,
            verification_code='CODE123',
            is_active=True,
        )
        self.task_other = Task.objects.create(
            title='Other Task',
            description='Other task description',
            organization=self.organization_other,
            points_reward=30,
            max_participants=10,
            verification_code='OTHER456',
            is_active=True,
        )
        self.inactive_task = Task.objects.create(
            title='Inactive Task',
            description='Inactive task description',
            organization=self.organization,
            points_reward=20,
            max_participants=5,
            verification_code='INACTIVE789',
            is_active=False,
        )

    def assertHasFieldError(self, response_data, field_name):
        """Helper to check for field errors in both custom and DRF error formats."""
        if 'errors' in response_data:
            self.assertIn(field_name, response_data['errors'])
        else:
            self.assertIn(field_name, response_data)


class TaskListViewTests(EventAPITestCase):
    """Tests for GET /api/events/tasks/ (role-scoped task list)."""

    def test_get_task_list_student_success(self):
        """Student retrieves only active tasks successfully."""
        self.client.force_authenticate(self.student)
        response = self.client.get(reverse('task_list'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('results', data)
        # Students should only see active tasks
        titles = [task['title'] for task in data['results']]
        self.assertIn('Test Task', titles)
        self.assertIn('Other Task', titles)
        self.assertNotIn('Inactive Task', titles)

    def test_get_task_list_unauthenticated(self):
        """Unauthenticated user cannot retrieve task list."""
        response = self.client.get(reverse('task_list'))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_task_list_org_without_assigned_org(self):
        """Organization owner without assigned organization gets 404."""
        self.client.force_authenticate(self.org_without_org)
        response = self.client.get(reverse('task_list'))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('error', response.json())


class TaskDetailGetTests(EventAPITestCase):
    """Tests for GET /api/events/tasks/<task_id>/ (task detail retrieval)."""

    def test_get_task_detail_success(self):
        """Student can successfully get task details without verification code."""
        self.client.force_authenticate(self.student)
        response = self.client.get(reverse('task_detail', args=[self.task.pk]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['id'], self.task.pk)
        self.assertEqual(data['title'], 'Test Task')
        self.assertNotIn('verification_code', data)  # code hidden from public/student

    def test_get_task_detail_unauthenticated(self):
        """Unauthenticated user cannot view task details."""
        response = self.client.get(reverse('task_detail', args=[self.task.pk]))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_task_detail_nonexistent(self):
        """Requesting non-existent task returns 404."""
        self.client.force_authenticate(self.student)
        response = self.client.get(reverse('task_detail', args=[99999]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class TaskDetailPatchTests(EventAPITestCase):
    """Tests for PATCH /api/events/tasks/<task_id>/ (task detail update)."""

    def test_patch_task_success(self):
        """Organization owner can successfully patch details of their own task."""
        self.client.force_authenticate(self.org_owner)
        payload = {'title': 'Updated Title', 'location': 'New Location'}
        response = self.client.patch(
            reverse('task_detail', args=[self.task.pk]), payload, format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['title'], 'Updated Title')
        self.assertEqual(data['location'], 'New Location')

        self.task.refresh_from_db()
        self.assertEqual(self.task.title, 'Updated Title')
        self.assertEqual(self.task.location, 'New Location')

    def test_patch_task_non_org_forbidden(self):
        """Non-organization users (e.g., student) cannot update task."""
        self.client.force_authenticate(self.student)
        payload = {'title': 'Hacked Title'}
        response = self.client.patch(
            reverse('task_detail', args=[self.task.pk]), payload, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_patch_task_not_owner(self):
        """Organization owner cannot update a task owned by another organization."""
        self.client.force_authenticate(self.org_owner)
        payload = {'title': 'Hacked Title'}
        response = self.client.patch(
            reverse('task_detail', args=[self.task_other.pk]), payload, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class TaskDetailDeleteTests(EventAPITestCase):
    """Tests for DELETE /api/events/tasks/<task_id>/ (task soft-deactivation)."""

    def test_delete_task_success(self):
        """Organization owner can successfully deactivate their own task."""
        self.client.force_authenticate(self.org_owner)
        response = self.client.delete(reverse('task_detail', args=[self.task.pk]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.task.refresh_from_db()
        self.assertFalse(self.task.is_active)

    def test_delete_task_non_org_forbidden(self):
        """Non-organization user (student) cannot deactivate task."""
        self.client.force_authenticate(self.student)
        response = self.client.delete(reverse('task_detail', args=[self.task.pk]))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_task_not_owner(self):
        """Organization owner cannot deactivate a task they do not own."""
        self.client.force_authenticate(self.org_owner)
        response = self.client.delete(reverse('task_detail', args=[self.task_other.pk]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class LeaderboardViewTests(EventAPITestCase):
    """Tests for GET /api/events/leaderboard/ (leaderboard)."""

    def test_get_leaderboard_success(self):
        """Authenticated user retrieves student leaderboard successfully."""
        self.client.force_authenticate(self.student)
        # Give student2 some points to verify ranking/sorting
        self.student2.points = 150
        self.student2.save(update_fields=['points'])

        response = self.client.get(reverse('leaderboard'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('results', data)
        results = data['results']
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0]['id'], self.student2.pk)
        self.assertEqual(results[0]['rank'], 1)

    def test_get_leaderboard_unauthenticated(self):
        """Unauthenticated user cannot retrieve leaderboard."""
        response = self.client.get(reverse('leaderboard'))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_leaderboard_post_not_allowed(self):
        """POST method on leaderboard is not allowed."""
        self.client.force_authenticate(self.student)
        response = self.client.post(reverse('leaderboard'), {})
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


@override_settings(**NO_THROTTLE_SETTINGS)
class JoinTaskViewTests(EventAPITestCase):
    """Tests for POST /api/events/tasks/<task_id>/join/ (join task)."""

    def test_join_task_success(self):
        """Student can request to join an active task successfully."""
        self.client.force_authenticate(self.student)
        response = self.client.post(reverse('join_task', args=[self.task.pk]))

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertIn('participation_id', data)
        self.assertEqual(data['status'], TaskParticipation.Status.PENDING)

    def test_join_task_non_student_forbidden(self):
        """Non-student user (e.g. admin) cannot join task."""
        self.client.force_authenticate(self.admin)
        response = self.client.post(reverse('join_task', args=[self.task.pk]))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_join_task_inactive_task(self):
        """Student cannot request to join an inactive task."""
        self.client.force_authenticate(self.student)
        response = self.client.post(reverse('join_task', args=[self.inactive_task.pk]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


@override_settings(**NO_THROTTLE_SETTINGS)
class VerifyTaskViewTests(EventAPITestCase):
    """Tests for POST /api/events/tasks/<task_id>/verify/ (verify task participation)."""

    def test_verify_task_success(self):
        """Student submits correct verification code and earns points."""
        TaskParticipation.objects.create(
            student=self.student, task=self.task, status=TaskParticipation.Status.APPROVED
        )
        self.client.force_authenticate(self.student)
        payload = {'code': 'CODE123'}

        response = self.client.post(
            reverse('verify_task', args=[self.task.pk]), payload, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['points_earned'], 50)
        self.student.refresh_from_db()
        self.assertEqual(self.student.points, 50)

    def test_verify_task_invalid_code(self):
        """Submitting an invalid code returns 400 Bad Request."""
        TaskParticipation.objects.create(
            student=self.student, task=self.task, status=TaskParticipation.Status.APPROVED
        )
        self.client.force_authenticate(self.student)
        payload = {'code': 'WRONGCODE'}

        response = self.client.post(
            reverse('verify_task', args=[self.task.pk]), payload, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.json())

    def test_verify_task_no_approved_participation(self):
        """Student cannot verify code without an approved participation request."""
        # No participation is created
        self.client.force_authenticate(self.student)
        payload = {'code': 'CODE123'}

        response = self.client.post(
            reverse('verify_task', args=[self.task.pk]), payload, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.json())


class MyParticipationsViewTests(EventAPITestCase):
    """Tests for GET /api/events/my-participations/ (my participation history)."""

    def test_get_my_participations_success(self):
        """Student gets their own participation list successfully."""
        TaskParticipation.objects.create(
            student=self.student, task=self.task, status=TaskParticipation.Status.PENDING
        )
        self.client.force_authenticate(self.student)

        response = self.client.get(reverse('my_participations'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['task_title'], 'Test Task')

    def test_get_my_participations_unauthenticated(self):
        """Unauthenticated user cannot view participations list."""
        response = self.client.get(reverse('my_participations'))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_my_participations_non_student_forbidden(self):
        """Non-student user (e.g. organization owner) cannot view this list."""
        self.client.force_authenticate(self.org_owner)
        response = self.client.get(reverse('my_participations'))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


@override_settings(**NO_THROTTLE_SETTINGS)
class CreateTaskViewTests(EventAPITestCase):
    """Tests for POST /api/events/tasks/create/ (create task)."""

    def test_create_task_success(self):
        """Organization owner can successfully create a new task."""
        self.client.force_authenticate(self.org_owner)
        payload = {
            'title': 'New Created Task',
            'description': 'Description',
            'points_reward': 40,
            'max_participants': 8,
            'verification_code': 'NEWCODE1',
        }
        response = self.client.post(reverse('create_task'), payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data['title'], 'New Created Task')
        self.assertEqual(data['points_reward'], 40)

        # Verify task was created in database
        self.assertTrue(Task.objects.filter(title='New Created Task').exists())

    def test_create_task_non_org_forbidden(self):
        """Student cannot create tasks."""
        self.client.force_authenticate(self.student)
        payload = {
            'title': 'Hack Task',
            'description': 'Description',
            'points_reward': 40,
            'max_participants': 8,
            'verification_code': 'HACK',
        }
        response = self.client.post(reverse('create_task'), payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_task_org_without_assigned_org(self):
        """Organization owner without assigned organization gets 404."""
        self.client.force_authenticate(self.org_without_org)
        payload = {
            'title': 'Orphan Task',
            'description': 'Description',
            'points_reward': 40,
            'max_participants': 8,
            'verification_code': 'ORPHAN',
        }
        response = self.client.post(reverse('create_task'), payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class TaskRequestsViewTests(EventAPITestCase):
    """Tests for GET /api/events/tasks/<task_id>/requests/ (task participation requests)."""

    def test_get_task_requests_success(self):
        """Organization owner can successfully retrieve list of participation requests."""
        TaskParticipation.objects.create(
            student=self.student, task=self.task, status=TaskParticipation.Status.PENDING
        )
        self.client.force_authenticate(self.org_owner)

        response = self.client.get(reverse('task_requests', args=[self.task.pk]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['student_email'], 'student@example.com')

    def test_get_task_requests_non_org_forbidden(self):
        """Student cannot view task requests."""
        self.client.force_authenticate(self.student)
        response = self.client.get(reverse('task_requests', args=[self.task.pk]))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_task_requests_not_owner(self):
        """Organization owner cannot view requests for a task owned by another organization."""
        self.client.force_authenticate(self.org_owner)
        response = self.client.get(reverse('task_requests', args=[self.task_other.pk]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class ManageRequestViewTests(EventAPITestCase):
    """Tests for PATCH /api/events/requests/<participation_id>/ (decide participation request)."""

    def test_manage_request_success(self):
        """Organization owner can successfully approve a request."""
        participation = TaskParticipation.objects.create(
            student=self.student, task=self.task, status=TaskParticipation.Status.PENDING
        )
        self.client.force_authenticate(self.org_owner)
        payload = {'status': TaskParticipation.Status.APPROVED}

        response = self.client.patch(
            reverse('manage_request', args=[participation.pk]), payload, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['status'], TaskParticipation.Status.APPROVED)

        participation.refresh_from_db()
        self.assertEqual(participation.status, TaskParticipation.Status.APPROVED)

    def test_manage_request_non_org_forbidden(self):
        """Student cannot approve/reject participation requests."""
        participation = TaskParticipation.objects.create(
            student=self.student, task=self.task, status=TaskParticipation.Status.PENDING
        )
        self.client.force_authenticate(self.student)
        payload = {'status': TaskParticipation.Status.APPROVED}

        response = self.client.patch(
            reverse('manage_request', args=[participation.pk]), payload, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_manage_request_not_owner(self):
        """Organization owner cannot decide a request for a task owned by another organization."""
        participation = TaskParticipation.objects.create(
            student=self.student, task=self.task_other, status=TaskParticipation.Status.PENDING
        )
        self.client.force_authenticate(self.org_owner)
        payload = {'status': TaskParticipation.Status.APPROVED}

        response = self.client.patch(
            reverse('manage_request', args=[participation.pk]), payload, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class StudentHistoryViewTests(EventAPITestCase):
    """Tests for GET /api/events/students/<student_id>/history/ (student participation history)."""

    def test_get_student_history_success(self):
        """Admin can successfully view student history."""
        TaskParticipation.objects.create(
            student=self.student, task=self.task, status=TaskParticipation.Status.COMPLETED
        )
        self.client.force_authenticate(self.admin)

        response = self.client.get(reverse('student_history', args=[self.student.pk]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_get_student_history_student_role_forbidden(self):
        """Student cannot view another student's participation history."""
        self.client.force_authenticate(self.student)
        response = self.client.get(reverse('student_history', args=[self.student2.pk]))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_student_history_org_without_assigned_org(self):
        """Organization owner without assigned organization gets 404."""
        self.client.force_authenticate(self.org_without_org)
        response = self.client.get(reverse('student_history', args=[self.student.pk]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class AdminTaskListViewTests(EventAPITestCase):
    """Tests for GET /api/events/admin/tasks/ (admin list all tasks)."""

    def test_admin_get_task_list_success(self):
        """Admin can successfully retrieve every task."""
        self.client.force_authenticate(self.admin)
        response = self.client.get(reverse('admin_task_list'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('results', data)
        self.assertEqual(len(data['results']), 3)  # active, other active, inactive

    def test_admin_get_task_list_non_admin_forbidden(self):
        """Non-admin user (e.g., student) cannot retrieve the admin task list."""
        self.client.force_authenticate(self.student)
        response = self.client.get(reverse('admin_task_list'))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_get_task_list_unauthenticated(self):
        """Unauthenticated user cannot retrieve the admin task list."""
        response = self.client.get(reverse('admin_task_list'))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class AdminDeactivateTaskViewTests(EventAPITestCase):
    """Tests for DELETE /api/events/admin/tasks/<task_id>/ (admin soft-deactivate)."""

    def test_admin_deactivate_task_success(self):
        """Admin can successfully soft-deactivate any task."""
        self.client.force_authenticate(self.admin)
        response = self.client.delete(reverse('admin_deactivate_task', args=[self.task.pk]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.task.refresh_from_db()
        self.assertFalse(self.task.is_active)

    def test_admin_deactivate_task_non_admin_forbidden(self):
        """Non-admin user (e.g., organization owner) cannot deactivate tasks through admin endpoint."""
        self.client.force_authenticate(self.org_owner)
        response = self.client.delete(reverse('admin_deactivate_task', args=[self.task.pk]))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_deactivate_task_nonexistent(self):
        """Admin cannot deactivate non-existent task."""
        self.client.force_authenticate(self.admin)
        response = self.client.delete(reverse('admin_deactivate_task', args=[99999]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
