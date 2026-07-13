"""
API endpoint tests for the organizations app.

These tests follow the strategy: 1 good case + 2 bad cases per endpoint.
"""
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.organizations.models import Organization
from apps.users.models import User


TEST_CACHE = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'test-cache',
    }
}

TEST_SETTINGS = {
    'CACHES': TEST_CACHE,
    'CACHE_TTL_DETAIL': 300,
}


@override_settings(**TEST_SETTINGS)
class OrganizationAPITestCase(APITestCase):
    """Base test case with common setup for organization API tests."""

    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='password',
            role=User.Role.ADMIN,
            full_name='Admin',
            is_superuser=True,
        )
        self.org_owner = User.objects.create_user(
            username='orgowner',
            email='org@example.com',
            password='password',
            role=User.Role.ORGANIZATION,
            full_name='Org Owner',
        )
        self.org_owner2 = User.objects.create_user(
            username='orgowner2',
            email='org2@example.com',
            password='password',
            role=User.Role.ORGANIZATION,
            full_name='Org Owner 2',
        )
        self.org_owner3 = User.objects.create_user(
            username='orgowner3',
            email='org3@example.com',
            password='password',
            role=User.Role.ORGANIZATION,
            full_name='Org Owner 3',
        )
        self.student = User.objects.create_user(
            username='student',
            email='student@example.com',
            password='password',
            role=User.Role.STUDENT,
            full_name='Student',
        )
        self.organization = Organization.objects.create(
            name='Test Organization',
            description='A test organization',
            owner=self.org_owner,
            is_active=True,
        )
        self.organization2 = Organization.objects.create(
            name='Another Organization',
            description='Another test organization',
            owner=self.org_owner2,
            is_active=True,
        )
        self.inactive_org = Organization.objects.create(
            name='Inactive Organization',
            description='An inactive organization',
            owner=self.org_owner3,
            is_active=False,
        )


class OrganizationListViewTests(OrganizationAPITestCase):
    """Tests for GET /organizations/ (public list)."""

    def test_get_organization_list_authenticated(self):
        """Authenticated user can successfully get organization list."""
        self.client.force_authenticate(self.student)
        response = self.client.get(reverse('organization_list'))
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 2)  # Only active orgs
        org_names = [org['name'] for org in data]
        self.assertIn('Test Organization', org_names)
        self.assertIn('Another Organization', org_names)

    def test_get_organization_list_unauthenticated(self):
        """Unauthenticated user cannot get organization list."""
        response = self.client.get(reverse('organization_list'))
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_organization_list_invalid_page(self):
        """Invalid page parameter is ignored (no pagination)."""
        self.client.force_authenticate(self.student)
        response = self.client.get(reverse('organization_list'), {'page': 'invalid'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 2)


class OrganizationDetailViewTests(OrganizationAPITestCase):
    """Tests for GET /organizations/<id>/ (public detail)."""

    def test_get_organization_detail_authenticated(self):
        """Authenticated user can successfully get organization detail."""
        self.client.force_authenticate(self.student)
        response = self.client.get(reverse('organization_detail', args=[self.organization.pk]))
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['id'], self.organization.pk)
        self.assertEqual(data['name'], 'Test Organization')
        self.assertEqual(data['owner']['id'], self.org_owner.pk)

    def test_get_organization_detail_unauthenticated(self):
        """Unauthenticated user cannot get organization detail."""
        response = self.client.get(reverse('organization_detail', args=[self.organization.pk]))
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_organization_detail_inactive(self):
        """Cannot get detail of inactive organization."""
        self.client.force_authenticate(self.student)
        response = self.client.get(reverse('organization_detail', args=[self.inactive_org.pk]))
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class MyOrganizationViewTests(OrganizationAPITestCase):
    """Tests for GET/PATCH /organizations/my/ (owner endpoints)."""

    def test_get_my_organization_as_owner(self):
        """Organization owner can successfully get their organization."""
        self.client.force_authenticate(self.org_owner)
        response = self.client.get(reverse('my_organization'))
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['id'], self.organization.pk)
        self.assertEqual(data['name'], 'Test Organization')

    def test_get_my_organization_non_owner(self):
        """Non-organization user cannot access my organization endpoint."""
        self.client.force_authenticate(self.student)
        response = self.client.get(reverse('my_organization'))
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_my_organization_unauthenticated(self):
        """Unauthenticated user cannot access my organization endpoint."""
        response = self.client.get(reverse('my_organization'))
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_patch_my_organization_as_owner(self):
        """Organization owner can successfully update their organization."""
        self.client.force_authenticate(self.org_owner)
        payload = {
            'name': 'Updated Organization',
            'description': 'Updated description',
        }
        response = self.client.patch(reverse('my_organization'), payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['name'], 'Updated Organization')
        self.assertEqual(data['description'], 'Updated description')

    def test_patch_my_organization_non_owner(self):
        """Non-organization user cannot update organization."""
        self.client.force_authenticate(self.student)
        payload = {'name': 'Hacked Organization'}
        response = self.client.patch(reverse('my_organization'), payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_patch_my_organization_duplicate_name(self):
        """Cannot update organization to duplicate name."""
        self.client.force_authenticate(self.org_owner)
        payload = {'name': 'Another Organization'}  # Already exists
        response = self.client.patch(reverse('my_organization'), payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertIn('errors', data)
        self.assertIn('name', data['errors'])


class AdminCreateOrganizationViewTests(OrganizationAPITestCase):
    """Tests for POST /organizations/admin/create/ (admin create)."""

    def test_admin_create_organization(self):
        """Admin can successfully create organization."""
        # Create a new org owner that doesn't have an organization yet
        new_org_owner = User.objects.create_user(
            username='neworgowner',
            email='neworg@example.com',
            password='password',
            role=User.Role.ORGANIZATION,
            full_name='New Org Owner',
        )
        
        self.client.force_authenticate(self.admin)
        payload = {
            'name': 'New Organization',
            'description': 'A new organization',
            'owner_id': new_org_owner.pk,
        }
        response = self.client.post(reverse('admin_create_organization'), payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data['name'], 'New Organization')
        self.assertEqual(data['owner']['id'], new_org_owner.pk)

    def test_non_admin_cannot_create_organization(self):
        """Non-admin user cannot create organization."""
        self.client.force_authenticate(self.student)
        payload = {
            'name': 'New Organization',
            'description': 'A new organization',
            'owner_id': self.org_owner.pk,
        }
        response = self.client.post(reverse('admin_create_organization'), payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_create_with_invalid_owner(self):
        """Admin cannot create organization with non-organization role owner."""
        self.client.force_authenticate(self.admin)
        payload = {
            'name': 'New Organization',
            'description': 'A new organization',
            'owner_id': self.student.pk,  # Student, not organization role
        }
        response = self.client.post(reverse('admin_create_organization'), payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertIn('errors', data)
        self.assertIn('owner_id', data['errors'])


class AdminOrganizationListViewTests(OrganizationAPITestCase):
    """Tests for GET /organizations/admin/ (admin list)."""

    def test_admin_get_organization_list(self):
        """Admin can successfully get all organizations including inactive."""
        self.client.force_authenticate(self.admin)
        response = self.client.get(reverse('admin_organization_list'))
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('results', data)
        self.assertEqual(len(data['results']), 3)  # Including inactive
        org_names = [org['name'] for org in data['results']]
        self.assertIn('Test Organization', org_names)
        self.assertIn('Another Organization', org_names)
        self.assertIn('Inactive Organization', org_names)

    def test_non_admin_cannot_get_admin_list(self):
        """Non-admin user cannot access admin organization list."""
        self.client.force_authenticate(self.student)
        response = self.client.get(reverse('admin_organization_list'))
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_list_with_is_active_filter(self):
        """Admin can filter organizations by is_active status."""
        self.client.force_authenticate(self.admin)
        response = self.client.get(reverse('admin_organization_list'), {'is_active': 'false'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data['results']), 1)
        self.assertEqual(data['results'][0]['name'], 'Inactive Organization')


class AdminOrganizationDetailViewTests(OrganizationAPITestCase):
    """Tests for GET/PATCH/DELETE /organizations/admin/<id>/ (admin detail)."""

    def test_admin_get_organization_detail(self):
        """Admin can successfully get any organization detail."""
        self.client.force_authenticate(self.admin)
        response = self.client.get(reverse('admin_organization_detail', args=[self.organization.pk]))
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['id'], self.organization.pk)
        self.assertEqual(data['name'], 'Test Organization')

    def test_non_admin_cannot_get_admin_detail(self):
        """Non-admin user cannot access admin organization detail."""
        self.client.force_authenticate(self.student)
        response = self.client.get(reverse('admin_organization_detail', args=[self.organization.pk]))
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_get_nonexistent_organization(self):
        """Admin cannot get detail of non-existent organization."""
        self.client.force_authenticate(self.admin)
        response = self.client.get(reverse('admin_organization_detail', args=[99999]))
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_admin_patch_organization(self):
        """Admin can successfully update organization."""
        self.client.force_authenticate(self.admin)
        payload = {
            'name': 'Admin Updated Organization',
            'description': 'Updated by admin',
        }
        response = self.client.patch(
            reverse('admin_organization_detail', args=[self.organization.pk]),
            payload,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['name'], 'Admin Updated Organization')

    def test_non_admin_cannot_patch_organization(self):
        """Non-admin user cannot update organization via admin endpoint."""
        self.client.force_authenticate(self.org_owner)
        payload = {'name': 'Hacked Update'}
        response = self.client.patch(
            reverse('admin_organization_detail', args=[self.organization.pk]),
            payload,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_patch_with_invalid_owner(self):
        """Admin cannot update organization with invalid owner."""
        self.client.force_authenticate(self.admin)
        payload = {'owner_id': self.student.pk}  # Student, not organization role
        response = self.client.patch(
            reverse('admin_organization_detail', args=[self.organization.pk]),
            payload,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertIn('errors', data)
        self.assertIn('owner_id', data['errors'])

    def test_admin_delete_organization(self):
        """Admin can successfully deactivate organization."""
        self.client.force_authenticate(self.admin)
        response = self.client.delete(
            reverse('admin_organization_detail', args=[self.organization.pk])
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('deactivated', data['detail'].lower())
        
        self.organization.refresh_from_db()
        self.assertFalse(self.organization.is_active)

    def test_non_admin_cannot_delete_organization(self):
        """Non-admin user cannot deactivate organization."""
        self.client.force_authenticate(self.org_owner)
        response = self.client.delete(
            reverse('admin_organization_detail', args=[self.organization.pk])
        )
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        
        # Organization should still be active
        self.organization.refresh_from_db()
        self.assertTrue(self.organization.is_active)

    def test_admin_delete_nonexistent_organization(self):
        """Admin cannot delete non-existent organization."""
        self.client.force_authenticate(self.admin)
        response = self.client.delete(
            reverse('admin_organization_detail', args=[99999])
        )
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
