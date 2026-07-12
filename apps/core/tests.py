from django.test import TestCase, override_settings
from django.urls import reverse
from django.core.cache import cache
from rest_framework import status

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
