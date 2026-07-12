from django.core.cache import cache, caches
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.test import APITestCase, APIRequestFactory

from apps.core.cache import (
    ORG_CACHE,
    PROJECT_CACHE,
    QUIZ_POOL_CACHE,
    SCHOOL_CACHE,
    SHOP_CACHE,
    cached_response,
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
class CachedResponseFilteringTests(TestCase):
    """cached_response() should only cache HTTP 200 responses."""

    def setUp(self):
        cache.clear()
        self.factory = APIRequestFactory()
        self.family = SCHOOL_CACHE
        self.ttl = 300

    def test_non_200_not_cached(self):
        """A builder that returns a non-200 should NOT be cached — builder runs again."""
        request = self.factory.get('/api/auth/schools/')

        call_count = 0

        def error_builder():
            nonlocal call_count
            call_count += 1
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)

        response1 = cached_response(request, self.family, self.ttl, error_builder)
        self.assertEqual(response1.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(call_count, 1, 'Builder should have run once on first call')

        # Second call — must NOT be served from cache
        response2 = cached_response(request, self.family, self.ttl, error_builder)
        self.assertEqual(response2.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(call_count, 2, 'Builder must run again — non-200 should not be cached')

    def test_200_is_cached(self):
        """A builder that returns 200 should be cached — second call skips builder."""
        request = self.factory.get('/api/auth/schools/')

        call_count = 0

        def success_builder():
            nonlocal call_count
            call_count += 1
            return Response({'data': 'hello'}, status=status.HTTP_200_OK)

        response1 = cached_response(request, self.family, self.ttl, success_builder)
        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        self.assertEqual(call_count, 1)

        # Second call — served from cache, builder should NOT run
        response2 = cached_response(request, self.family, self.ttl, success_builder)
        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        self.assertEqual(call_count, 1, 'Builder should NOT run again — served from cache')
        self.assertEqual(response2.data, {'data': 'hello'})

    def test_error_then_success_not_cross_contaminated(self):
        """An error response for one URL should not pollute a success for another."""
        error_request = self.factory.get('/api/shops/?page=1')
        success_request = self.factory.get('/api/shops/')

        call_count = 0

        def builder(url_type: str):
            nonlocal call_count
            call_count += 1
            if url_type == 'error':
                return Response({'error': 'fail'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            return Response({'data': 'ok'}, status=status.HTTP_200_OK)

        # Fire an error (not cached)
        cached_response(
            error_request, self.family, self.ttl,
            lambda: builder('error'),
        )
        self.assertEqual(call_count, 1)

        # Fire a success (should be cached)
        cached_response(
            success_request, self.family, self.ttl,
            lambda: builder('success'),
        )
        self.assertEqual(call_count, 2)

        # Same success again (cache hit — builder not called)
        cached_response(
            success_request, self.family, self.ttl,
            lambda: builder('success'),
        )
        self.assertEqual(call_count, 2, 'Success response should be cached')

        # Error again (builder must run — not cached)
        cached_response(
            error_request, self.family, self.ttl,
            lambda: builder('error'),
        )
        self.assertEqual(call_count, 3, 'Error response should NOT be cached')


@override_settings(CACHES=TEST_CACHE)
class CachedResponseVaryOnTests(TestCase):
    """vary_on parameter should scope cache keys so different scopes are isolated."""

    def setUp(self):
        cache.clear()
        self.factory = APIRequestFactory()
        self.family = QUIZ_POOL_CACHE
        self.ttl = 300

    def test_different_vary_on_produce_different_keys(self):
        """Different vary_on values should result in separate cache entries."""
        request = self.factory.get('/api/quizzes/questions/')

        call_count = 0

        def builder():
            nonlocal call_count
            call_count += 1
            return Response({'questions': []}, status=status.HTTP_200_OK)

        # First user (admin)
        cached_response(
            request, self.family, self.ttl, builder,
            vary_on='user:1:role:admin',
        )
        self.assertEqual(call_count, 1)

        # Second user (org) — different vary_on, should be a cache miss
        cached_response(
            request, self.family, self.ttl, builder,
            vary_on='user:2:role:org',
        )
        self.assertEqual(call_count, 2, 'Different vary_on must produce a cache miss')

        # First user again — should hit cache
        cached_response(
            request, self.family, self.ttl, builder,
            vary_on='user:1:role:admin',
        )
        self.assertEqual(call_count, 2, 'Same vary_on should be a cache hit')

    def test_no_vary_on_vs_vary_on_are_isolated(self):
        """A request without vary_on should not share cache with one that has it."""
        request = self.factory.get('/api/quizzes/questions/')

        call_count = 0

        def builder():
            nonlocal call_count
            call_count += 1
            return Response({'data': 'content'}, status=status.HTTP_200_OK)

        # Cache without vary_on
        cached_response(request, self.family, self.ttl, builder)
        self.assertEqual(call_count, 1)

        # Same request with vary_on — should be a different key
        cached_response(
            request, self.family, self.ttl, builder,
            vary_on='user:1:role:student',
        )
        self.assertEqual(call_count, 2, 'vary_on vs no vary_on must produce different keys')

        # Without vary_on again — should hit the original cache
        cached_response(request, self.family, self.ttl, builder)
        self.assertEqual(call_count, 2, 'No-vary-on request should reuse its own cache entry')

    def test_same_vary_on_different_paths_are_isolated(self):
        """Even with same vary_on, different URL paths produce different cache keys."""
        request_a = self.factory.get('/api/quizzes/questions/')
        request_b = self.factory.get('/api/quizzes/questions/?is_active=true')

        call_count = 0

        def builder():
            nonlocal call_count
            call_count += 1
            return Response({'ok': True}, status=status.HTTP_200_OK)

        cached_response(
            request_a, self.family, self.ttl, builder,
            vary_on='user:1:role:admin',
        )
        self.assertEqual(call_count, 1)

        # Different path + same vary_on — cache miss
        cached_response(
            request_b, self.family, self.ttl, builder,
            vary_on='user:1:role:admin',
        )
        self.assertEqual(call_count, 2, 'Different URL paths must produce separate cache entries')


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


    def test_organization_list_returns_all_active_organizations(self):
        self.client.force_authenticate(self.student)

        response = self.client.get(reverse('organization_list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIsInstance(data, list)
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
