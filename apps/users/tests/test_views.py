"""
API endpoint tests for the users app.

These tests follow the strategy: 1 good case + 2 bad cases per endpoint.
"""
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.users.models import User


TEST_CACHE = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'test-cache',
    }
}

TEST_SETTINGS = {
    'CACHES': TEST_CACHE,
    'CACHE_TTL_SCHOOLS': 300,
}


@override_settings(**TEST_SETTINGS)
class UserAPITestCase(APITestCase):
    """Base test case with common setup for user API tests."""

    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='password',
            role=User.Role.ADMIN,
            full_name='Admin',
            is_superuser=True,
        )
        self.organization = User.objects.create_user(
            username='orgowner',
            email='org@example.com',
            password='password',
            role=User.Role.ORGANIZATION,
            full_name='Org Owner',
        )
        self.student = User.objects.create_user(
            username='student',
            email='student@example.com',
            password='password',
            role=User.Role.STUDENT,
            full_name='Student',
            student_id='STU001',
            school=User.School.IT_ENGINEERING,
        )
        self.shop_owner = User.objects.create_user(
            username='shopowner',
            email='shop@example.com',
            password='password',
            role=User.Role.SHOP_OWNER,
            full_name='Shop Owner',
        )
        self.inactive_user = User.objects.create_user(
            username='inactive',
            email='inactive@example.com',
            password='password',
            role=User.Role.STUDENT,
            full_name='Inactive Student',
            is_active=False,
        )

    def assertHasFieldError(self, response_data, field_name):
        """Helper to check for field errors in both custom and DRF error formats."""
        if 'errors' in response_data:
            self.assertIn(field_name, response_data['errors'])
        else:
            self.assertIn(field_name, response_data)


# Disable throttling for tests that hit throttled endpoints
NO_THROTTLE_SETTINGS = {
    'CACHES': TEST_CACHE,
    'CACHE_TTL_SCHOOLS': 300,
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


class SchoolListViewTests(UserAPITestCase):
    """Tests for GET /schools/ (public school list)."""

    def test_get_school_list_success(self):
        """Unauthenticated user can successfully get school list and it is cached."""
        response1 = self.client.get(reverse('schools'))
        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        data = response1.json()
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)
        self.assertIn('value', data[0])
        self.assertIn('label', data[0])

        # Verify caching works
        response2 = self.client.get(reverse('schools'))
        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        self.assertEqual(response1.json(), response2.json())

    def test_get_school_list_post_method_not_allowed(self):
        """POST to school list endpoint is not allowed."""
        response = self.client.post(reverse('schools'), {})
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_get_school_list_put_method_not_allowed(self):
        """PUT to school list endpoint is not allowed."""
        response = self.client.put(reverse('schools'), {})
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


@override_settings(**NO_THROTTLE_SETTINGS)
class RegisterViewTests(UserAPITestCase):
    """Tests for POST /register/ (public registration)."""

    def test_register_student_successfully(self):
        """Unauthenticated user can successfully register as student."""
        payload = {
            'email': 'newstudent@example.com',
            'full_name': 'New Student',
            'password': 'password123',
            'student_id': 'STU002',
            'school': User.School.BUSINESS,
        }
        response = self.client.post(reverse('register'), payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertIn('token', data)
        self.assertIn('refresh', data)
        self.assertIn('user', data)
        self.assertEqual(data['user']['email'], 'newstudent@example.com')
        self.assertEqual(data['user']['role'], User.Role.STUDENT)
        
        # Verify user was created
        user = User.objects.get(email='newstudent@example.com')
        self.assertEqual(user.full_name, 'New Student')
        self.assertEqual(user.student_id, 'STU002')

    def test_register_with_duplicate_email(self):
        """Cannot register with an email that already exists."""
        payload = {
            'email': 'student@example.com',  # Already exists
            'full_name': 'Duplicate Student',
            'password': 'password123',
            'student_id': 'STU003',
        }
        response = self.client.post(reverse('register'), payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertHasFieldError(data, 'email')

    def test_register_with_duplicate_student_id(self):
        """Cannot register with a student_id that already exists."""
        payload = {
            'email': 'another@example.com',
            'full_name': 'Another Student',
            'password': 'password123',
            'student_id': 'STU001',  # Already exists
        }
        response = self.client.post(reverse('register'), payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertHasFieldError(data, 'student_id')


@override_settings(**NO_THROTTLE_SETTINGS)
class LoginViewTests(UserAPITestCase):
    """Tests for POST /login/ (public login)."""

    def test_login_with_valid_credentials(self):
        """User can successfully login with valid credentials."""
        payload = {
            'email': 'student@example.com',
            'password': 'password',
        }
        response = self.client.post(reverse('login'), payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('token', data)
        self.assertIn('refresh', data)
        self.assertIn('user', data)
        self.assertEqual(data['user']['email'], 'student@example.com')

    def test_login_with_invalid_credentials(self):
        """Cannot login with invalid email or password."""
        payload = {
            'email': 'student@example.com',
            'password': 'wrongpassword',
        }
        response = self.client.post(reverse('login'), payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertHasFieldError(data, 'non_field_errors')

    def test_login_with_inactive_account(self):
        """Cannot login with inactive user account."""
        payload = {
            'email': 'inactive@example.com',
            'password': 'password',
        }
        response = self.client.post(reverse('login'), payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertHasFieldError(data, 'non_field_errors')


@override_settings(**NO_THROTTLE_SETTINGS)
class RefreshTokenViewTests(UserAPITestCase):
    """Tests for POST /token/refresh/ (public token refresh)."""

    def test_refresh_token_with_valid_token(self):
        """User can successfully refresh access token with valid refresh token."""
        # First login to get refresh token
        login_payload = {
            'email': 'student@example.com',
            'password': 'password',
        }
        login_response = self.client.post(reverse('login'), login_payload, format='json')
        refresh_token = login_response.json()['refresh']
        
        # Now refresh the token
        refresh_payload = {'refresh': refresh_token}
        response = self.client.post(reverse('token_refresh'), refresh_payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('token', data)
        self.assertIn('refresh', data)
        self.assertIsInstance(data['token'], str)

    def test_refresh_token_without_refresh_token(self):
        """Cannot refresh without providing refresh token."""
        response = self.client.post(reverse('token_refresh'), {}, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertIn('error', data)

    def test_refresh_token_with_invalid_token(self):
        """Cannot refresh with invalid or expired refresh token."""
        payload = {'refresh': 'invalid.refresh.token'}
        response = self.client.post(reverse('token_refresh'), payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        data = response.json()
        self.assertIn('error', data)


class LogoutViewTests(UserAPITestCase):
    """Tests for POST /logout/ (authenticated logout)."""

    def test_logout_with_valid_token(self):
        """Authenticated user can successfully logout."""
        self.client.force_authenticate(self.student)
        
        # Get refresh token first
        login_payload = {
            'email': 'student@example.com',
            'password': 'password',
        }
        login_response = self.client.post(reverse('login'), login_payload, format='json')
        refresh_token = login_response.json()['refresh']
        
        # Logout
        logout_payload = {'refresh': refresh_token}
        response = self.client.post(reverse('logout'), logout_payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('detail', data)

    def test_logout_without_refresh_token(self):
        """Cannot logout without providing refresh token."""
        self.client.force_authenticate(self.student)
        
        response = self.client.post(reverse('logout'), {}, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertIn('error', data)

    def test_logout_unauthenticated(self):
        """Unauthenticated user cannot logout."""
        response = self.client.post(reverse('logout'), {}, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class MeViewGetTests(UserAPITestCase):
    """Tests for GET /me/ (authenticated user profile retrieval)."""

    def test_get_own_profile_success(self):
        """Authenticated user can successfully get their own profile."""
        self.client.force_authenticate(self.student)
        
        response = self.client.get(reverse('me'))
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['id'], self.student.pk)
        self.assertEqual(data['email'], 'student@example.com')
        self.assertEqual(data['full_name'], 'Student')

    def test_get_profile_unauthenticated(self):
        """Unauthenticated user cannot access profile endpoint."""
        response = self.client.get(reverse('me'))
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_profile_post_method_not_allowed(self):
        """POST to profile endpoint is not allowed."""
        self.client.force_authenticate(self.student)
        response = self.client.post(reverse('me'), {})
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class MeViewPatchTests(UserAPITestCase):
    """Tests for PATCH /me/ (authenticated user profile update)."""

    def test_patch_own_profile_success(self):
        """Authenticated user can successfully update their own profile."""
        self.client.force_authenticate(self.student)
        
        payload = {
            'full_name': 'Updated Student Name',
            'phone': '+1234567890',
        }
        response = self.client.patch(reverse('me'), payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['full_name'], 'Updated Student Name')
        self.assertEqual(data['phone'], '+1234567890')
        
        # Verify database was updated
        self.student.refresh_from_db()
        self.assertEqual(self.student.full_name, 'Updated Student Name')

    def test_patch_profile_unauthenticated(self):
        """Unauthenticated user cannot update profile."""
        payload = {'full_name': 'Hacked Name'}
        response = self.client.patch(reverse('me'), payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_patch_profile_invalid_phone_number(self):
        """Cannot update profile with a phone number longer than 20 characters."""
        self.client.force_authenticate(self.student)
        payload = {'phone': '1234567890' * 3}  # 30 chars, exceeds max_length=20
        response = self.client.patch(reverse('me'), payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertHasFieldError(data, 'phone')


class ChangePasswordViewTests(UserAPITestCase):
    """Tests for POST /change-password/ (authenticated password change)."""

    @override_settings(**NO_THROTTLE_SETTINGS)
    def test_change_password_success(self):
        """Authenticated user can successfully change their password."""
        self.client.force_authenticate(self.student)
        
        payload = {
            'old_password': 'password',
            'new_password': 'newpassword123',
        }
        response = self.client.post(reverse('change_password'), payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('detail', data)
        
        # Verify password was changed
        self.student.refresh_from_db()
        self.assertTrue(self.student.check_password('newpassword123'))
        self.assertFalse(self.student.check_password('password'))

    @override_settings(**NO_THROTTLE_SETTINGS)
    def test_change_password_with_wrong_old_password(self):
        """Cannot change password with incorrect old password."""
        self.client.force_authenticate(self.student)
        
        payload = {
            'old_password': 'wrongpassword',
            'new_password': 'newpassword123',
        }
        response = self.client.post(reverse('change_password'), payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertHasFieldError(data, 'old_password')

    @override_settings(**NO_THROTTLE_SETTINGS)
    def test_change_password_unauthenticated(self):
        """Unauthenticated user cannot change password."""
        payload = {
            'old_password': 'password',
            'new_password': 'newpassword123',
        }
        response = self.client.post(reverse('change_password'), payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class AdminCreateUserViewTests(UserAPITestCase):
    """Tests for POST /admin/create-user/ (admin user creation)."""

    def test_admin_create_user_with_valid_data(self):
        """Admin can successfully create a user with any role."""
        self.client.force_authenticate(self.admin)
        
        payload = {
            'email': 'newadmin@example.com',
            'full_name': 'New Admin',
            'password': 'password123',
            'role': User.Role.ADMIN,
            'student_id': 'ADM001',
            'phone': '+1234567890',
            'school': User.School.BUSINESS,
        }
        response = self.client.post(reverse('admin_create_user'), payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertIn('user', data)
        self.assertEqual(data['user']['email'], 'newadmin@example.com')
        self.assertEqual(data['user']['role'], User.Role.ADMIN)
        
        # Verify user was created
        user = User.objects.get(email='newadmin@example.com')
        self.assertEqual(user.full_name, 'New Admin')

    def test_non_admin_cannot_create_user(self):
        """Non-admin user cannot create users via admin endpoint."""
        self.client.force_authenticate(self.student)
        
        payload = {
            'email': 'hack@example.com',
            'full_name': 'Hacked User',
            'password': 'password123',
            'role': User.Role.ADMIN,
        }
        response = self.client.post(reverse('admin_create_user'), payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_create_user_with_duplicate_email(self):
        """Admin cannot create user with duplicate email."""
        self.client.force_authenticate(self.admin)
        
        payload = {
            'email': 'student@example.com',  # Already exists
            'full_name': 'Duplicate Email',
            'password': 'password123',
            'role': User.Role.STUDENT,
        }
        response = self.client.post(reverse('admin_create_user'), payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertHasFieldError(data, 'email')


class AdminListUsersViewTests(UserAPITestCase):
    """Tests for GET /admin/users/ (admin user list)."""

    def test_admin_get_user_list_success(self):
        """Admin can successfully get list of all users, with support for filtering."""
        self.client.force_authenticate(self.admin)
        
        # 1. Standard list
        response = self.client.get(reverse('admin_list_users'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('results', data)
        self.assertGreater(len(data['results']), 0)

        # 2. Filtered list
        response_filtered = self.client.get(reverse('admin_list_users'), {'role': User.Role.STUDENT})
        self.assertEqual(response_filtered.status_code, status.HTTP_200_OK)
        data_filtered = response_filtered.json()
        self.assertIn('results', data_filtered)
        for user in data_filtered['results']:
            self.assertEqual(user['role'], User.Role.STUDENT)

    def test_non_admin_cannot_get_user_list(self):
        """Non-admin user cannot access admin user list."""
        self.client.force_authenticate(self.student)
        
        response = self.client.get(reverse('admin_list_users'))
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_get_user_list_unauthenticated(self):
        """Unauthenticated user cannot access admin user list."""
        response = self.client.get(reverse('admin_list_users'))
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class AdminUserDetailGetTests(UserAPITestCase):
    """Tests for GET /admin/users/<id>/ (admin user details retrieval)."""

    def test_admin_get_user_detail_success(self):
        """Admin can successfully get any user's details."""
        self.client.force_authenticate(self.admin)
        
        response = self.client.get(reverse('admin_user_detail', args=[self.student.pk]))
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['id'], self.student.pk)
        self.assertEqual(data['email'], 'student@example.com')

    def test_non_admin_cannot_get_user_detail(self):
        """Non-admin user cannot access admin user detail endpoint."""
        self.client.force_authenticate(self.student)
        
        response = self.client.get(reverse('admin_user_detail', args=[self.student.pk]))
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_get_nonexistent_user(self):
        """Admin cannot get detail of non-existent user."""
        self.client.force_authenticate(self.admin)
        
        response = self.client.get(reverse('admin_user_detail', args=[99999]))
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class AdminUserDetailPatchTests(UserAPITestCase):
    """Tests for PATCH /admin/users/<id>/ (admin user update)."""

    def test_admin_patch_user_success(self):
        """Admin can successfully update user details."""
        self.client.force_authenticate(self.admin)
        
        payload = {
            'full_name': 'Admin Updated Name',
            'role': User.Role.SHOP_OWNER,
            'points': 100,
        }
        response = self.client.patch(
            reverse('admin_user_detail', args=[self.student.pk]),
            payload,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['full_name'], 'Admin Updated Name')
        self.assertEqual(data['role'], User.Role.SHOP_OWNER)
        self.assertEqual(data['points'], 100)

    def test_non_admin_cannot_patch_user(self):
        """Non-admin user cannot update user via admin endpoint."""
        self.client.force_authenticate(self.organization)
        
        payload = {'full_name': 'Hacked Update'}
        response = self.client.patch(
            reverse('admin_user_detail', args=[self.student.pk]),
            payload,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_patch_with_invalid_role(self):
        """Admin cannot update user with invalid role."""
        self.client.force_authenticate(self.admin)
        
        payload = {'role': 'invalid_role'}
        response = self.client.patch(
            reverse('admin_user_detail', args=[self.student.pk]),
            payload,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertHasFieldError(data, 'role')


class AdminUserDetailDeleteTests(UserAPITestCase):
    """Tests for DELETE /admin/users/<id>/ (admin user deactivation)."""

    def test_admin_delete_user_success(self):
        """Admin can successfully deactivate user account."""
        self.client.force_authenticate(self.admin)
        
        response = self.client.delete(
            reverse('admin_user_detail', args=[self.student.pk])
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('deactivated', data['detail'].lower())
        
        # Verify user was deactivated
        self.student.refresh_from_db()
        self.assertFalse(self.student.is_active)

    def test_non_admin_cannot_delete_user(self):
        """Non-admin user cannot deactivate user via admin endpoint."""
        self.client.force_authenticate(self.organization)
        
        response = self.client.delete(
            reverse('admin_user_detail', args=[self.student.pk])
        )
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        
        # Verify user is still active
        self.student.refresh_from_db()
        self.assertTrue(self.student.is_active)

    def test_admin_delete_nonexistent_user(self):
        """Admin cannot delete non-existent user."""
        self.client.force_authenticate(self.admin)
        
        response = self.client.delete(
            reverse('admin_user_detail', args=[99999])
        )
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

