from django.core.cache import cache, caches
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.cache import (
    ORG_CACHE,
    PROJECT_CACHE,
    QUIZ_POOL_CACHE,
    SCHOOL_CACHE,
    SHOP_CACHE,
    invalidate_cache_families,
)
from apps.organizations.models import Organization
from apps.projects.models import Project, ProjectCompletion
from apps.quizzes.models import Question
from apps.shop.models import Purchase, Shop, ShopItem
from apps.users.models import User
from apps.events.models import Task, TaskParticipation


TEST_CACHE = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'test-cache',
    }
}


@override_settings(
    CACHES={
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'test-cache-throttling',
        }
    }
)
class ThrottlingTestCase(TestCase):
    def setUp(self):
        # Clear cache to guarantee isolated state for this test run
        cache.clear()

    def test_auth_throttle_limit(self):
        url = reverse('login')
        payload = {'email': 'test@example.com', 'password': 'wrong-password'}

        # First 5 requests should NOT be throttled (they'll fail with 400 Bad Request)
        # matching the 'auth': '5/minute' limit defined in project settings
        for _ in range(5):
            response = self.client.post(url, payload, content_type='application/json')
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertNotEqual(response.json().get('error_code'), 'THROTTLED')

        # The 6th request must exceed the limit (5/minute) and be throttled (429)
        response = self.client.post(url, payload, content_type='application/json')
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

        # Check response body format maps to the custom throttled envelope
        data = response.json()
        self.assertEqual(data.get('error_code'), 'THROTTLED')
        self.assertIn('error', data)
        self.assertIn('wait', data)
        self.assertGreater(data['wait'], 0)
        self.assertTrue(data['error'].startswith('Request was throttled.'))


@override_settings(CACHES=TEST_CACHE)
class CachedReadEndpointsTestCase(APITestCase):
    def setUp(self):
        cache.clear()
        self.student = User.objects.create_user(
            username='student',
            email='student@example.com',
            password='password',
            role=User.Role.STUDENT,
            full_name='Student',
        )
        self.admin = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='password',
            role=User.Role.ADMIN,
            full_name='Admin',
        )
        self.org_owner = User.objects.create_user(
            username='org-owner',
            email='org-owner@example.com',
            password='password',
            role=User.Role.ORGANIZATION,
            full_name='Org Owner',
        )
        self.shop_owner = User.objects.create_user(
            username='shop-owner',
            email='shop-owner@example.com',
            password='password',
            role=User.Role.SHOP_OWNER,
            full_name='Shop Owner',
        )
        self.organization = Organization.objects.create(
            name='Cached Org',
            owner=self.org_owner,
            is_active=True,
        )
        self.shop = Shop.objects.create(
            name='Cached Shop',
            owner=self.shop_owner,
            shop_type=Shop.Type.INTERNAL,
            is_active=True,
        )

    def _names_from_results(self, response):
        data = response.json()
        if isinstance(data, dict) and 'results' in data:
            return [
                item.get('name') or item.get('title') or item.get('text')
                for item in data['results']
            ]
        return [
            item.get('name') or item.get('title') or item.get('text')
            for item in data
        ]

    def test_schools_are_cached(self):
        response = self.client.get(reverse('schools'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreater(len(response.json()), 0)

        store = caches['default']._cache
        self.assertTrue(
            len(store) > 0,
            'Expected at least one cache entry after GET /schools/',
        )

        # A second request returns identical data (served from cache).
        response2 = self.client.get(reverse('schools'))
        self.assertEqual(response.json(), response2.json())


    def test_organization_list_cache_invalidates_by_family(self):
        self.client.force_authenticate(self.student)

        response = self.client.get(reverse('organization_list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._names_from_results(response), ['Cached Org'])

        Organization.objects.create(
            name='Fresh Org',
            owner=User.objects.create_user(
                username='fresh-org-owner',
                email='fresh-org-owner@example.com',
                password='password',
                role=User.Role.ORGANIZATION,
            ),
        )

        cached_response = self.client.get(reverse('organization_list'))
        self.assertEqual(self._names_from_results(cached_response), ['Cached Org'])

        invalidate_cache_families(ORG_CACHE)
        fresh_response = self.client.get(reverse('organization_list'))
        self.assertIn('Fresh Org', self._names_from_results(fresh_response))

    def test_project_list_cache_invalidates_by_family(self):
        self.client.force_authenticate(self.student)
        Project.objects.create(
            organization=self.organization,
            title='Cached Project',
            google_form_url='https://example.com/form',
            points_reward=10,
        )

        response = self.client.get(reverse('project_list'))
        self.assertEqual(self._names_from_results(response), ['Cached Project'])

        Project.objects.create(
            organization=self.organization,
            title='Fresh Project',
            google_form_url='https://example.com/fresh',
            points_reward=10,
        )

        cached_response = self.client.get(reverse('project_list'))
        self.assertEqual(self._names_from_results(cached_response), ['Cached Project'])

        invalidate_cache_families(PROJECT_CACHE)
        fresh_response = self.client.get(reverse('project_list'))
        self.assertIn('Fresh Project', self._names_from_results(fresh_response))

    def test_shop_item_list_cache_invalidates_by_family(self):
        self.client.force_authenticate(self.student)
        ShopItem.objects.create(
            shop=self.shop,
            title='Cached Item',
            price=10,
        )

        response = self.client.get(reverse('shop_item_list', args=[self.shop.pk]))
        self.assertEqual(self._names_from_results(response), ['Cached Item'])

        ShopItem.objects.create(
            shop=self.shop,
            title='Fresh Item',
            price=10,
        )

        cached_response = self.client.get(reverse('shop_item_list', args=[self.shop.pk]))
        self.assertEqual(self._names_from_results(cached_response), ['Cached Item'])

        invalidate_cache_families(SHOP_CACHE)
        fresh_response = self.client.get(reverse('shop_item_list', args=[self.shop.pk]))
        self.assertIn('Fresh Item', self._names_from_results(fresh_response))

    def test_quiz_pool_cache_is_user_scoped(self):
        self.client.force_authenticate(self.admin)
        Question.objects.create(
            text='Admin-visible question',
            question_type=Question.QuestionType.TRUE_FALSE,
            answer=True,
            created_by=self.organization,
        )

        admin_response = self.client.get(reverse('quiz_question_list'))
        self.assertEqual(admin_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            self._names_from_results(admin_response),
            ['Admin-visible question'],
        )

        self.client.force_authenticate(self.org_owner)
        org_response = self.client.get(reverse('quiz_question_list'))
        self.assertEqual(org_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            self._names_from_results(org_response),
            ['Admin-visible question'],
        )

        Question.objects.create(
            text='Fresh question',
            question_type=Question.QuestionType.TRUE_FALSE,
            answer=False,
            created_by=self.organization,
        )

        cached_response = self.client.get(reverse('quiz_question_list'))
        self.assertEqual(
            self._names_from_results(cached_response),
            ['Admin-visible question'],
        )

        invalidate_cache_families(QUIZ_POOL_CACHE)
        fresh_response = self.client.get(reverse('quiz_question_list'))
        self.assertIn('Fresh question', self._names_from_results(fresh_response))


@override_settings(CACHES=TEST_CACHE)
class SeedCommandTestCase(TestCase):
    def setUp(self):
        cache.clear()

    def _counts(self):
        return {
            'users': User.objects.count(),
            'organizations': Organization.objects.count(),
            'tasks': Task.objects.count(),
            'task_participations': TaskParticipation.objects.count(),
            'projects': Project.objects.count(),
            'project_completions': ProjectCompletion.objects.count(),
            'shops': Shop.objects.count(),
            'shop_items': ShopItem.objects.count(),
            'purchases': Purchase.objects.count(),
            'questions': Question.objects.count(),
        }

    def test_seed_command_creates_demo_data(self):
        call_command('seed', '--quiet')

        admin = User.objects.get(email='admin@example.com')
        student = User.objects.get(email='student1@example.com')

        self.assertTrue(admin.check_password('password123'))
        self.assertTrue(admin.is_superuser)
        self.assertEqual(admin.role, User.Role.ADMIN)
        self.assertTrue(student.check_password('password123'))
        self.assertEqual(student.role, User.Role.STUDENT)
        self.assertGreaterEqual(Organization.objects.filter(is_active=True).count(), 3)
        self.assertGreaterEqual(Task.objects.filter(is_active=True).count(), 5)
        self.assertGreaterEqual(Project.objects.filter(is_active=True).count(), 4)
        self.assertGreaterEqual(Shop.objects.filter(is_active=True).count(), 2)
        self.assertGreaterEqual(ShopItem.objects.filter(is_active=True).count(), 6)
        self.assertGreaterEqual(Question.objects.filter(is_active=True).count(), 12)

    def test_seed_command_is_idempotent(self):
        call_command('seed', '--quiet')
        first_counts = self._counts()

        call_command('seed', '--quiet')
        second_counts = self._counts()

        self.assertEqual(first_counts, second_counts)
