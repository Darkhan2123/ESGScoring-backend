"""
API endpoint tests for the shop app.

These tests follow the strategy: 1 good case + 2 bad cases per endpoint.
"""
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.shop.models import Purchase, Shop, ShopItem
from apps.users.models import User


TEST_CACHE = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'test-cache-shop',
    }
}

TEST_SETTINGS = {
    'CACHES': TEST_CACHE,
    'CACHE_TTL_SHOP_LIST': 120,
    'CACHE_TTL_SHOP_ITEMS': 120,
    'CACHE_TTL_SHOP_DETAIL': 300,
    'CACHE_TTL_DETAIL': 300,
}

NO_THROTTLE_SETTINGS = {
    'CACHES': TEST_CACHE,
    'CACHE_TTL_SHOP_LIST': 120,
    'CACHE_TTL_SHOP_ITEMS': 120,
    'CACHE_TTL_SHOP_DETAIL': 300,
    'CACHE_TTL_DETAIL': 300,
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
        'DEFAULT_PAGINATION_CLASS': (
            'rest_framework.pagination.PageNumberPagination',
        ),
        'PAGE_SIZE': 20,
        'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
        'EXCEPTION_HANDLER': (
            'apps.core.exception_handler.custom_exception_handler'
        ),
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
class ShopAPITestCase(APITestCase):
    """Base test case with common setup for shop API tests."""

    def setUp(self):
        cache.clear()

        # Users
        self.admin = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='password',
            role=User.Role.ADMIN,
            full_name='Admin',
            is_superuser=True,
        )
        self.shop_owner = User.objects.create_user(
            username='shopowner',
            email='shop@example.com',
            password='password',
            role=User.Role.SHOP_OWNER,
            full_name='Shop Owner',
        )
        self.external_shop_owner = User.objects.create_user(
            username='extshopowner',
            email='extshop@example.com',
            password='password',
            role=User.Role.SHOP_OWNER,
            full_name='External Shop Owner',
        )
        self.shop_owner_no_shop = User.objects.create_user(
            username='shopownernoshop',
            email='shopownernoshop@example.com',
            password='password',
            role=User.Role.SHOP_OWNER,
            full_name='Shop Owner Without Shop',
        )
        self.inactive_shop_owner = User.objects.create_user(
            username='inactiveshopowner',
            email='inactive@example.com',
            password='password',
            role=User.Role.SHOP_OWNER,
            full_name='Inactive Shop Owner',
        )
        self.student = User.objects.create_user(
            username='student',
            email='student@example.com',
            password='password',
            role=User.Role.STUDENT,
            full_name='Student',
            points=500,
        )
        self.student_low_points = User.objects.create_user(
            username='studentlow',
            email='studentlow@example.com',
            password='password',
            role=User.Role.STUDENT,
            full_name='Student Low Points',
            points=5,
        )
        self.organization = User.objects.create_user(
            username='orgowner',
            email='org@example.com',
            password='password',
            role=User.Role.ORGANIZATION,
            full_name='Org Owner',
        )

        # Shops
        self.internal_shop = Shop.objects.create(
            name='Internal Shop',
            description='An internal shop',
            address='Campus Building A',
            owner=self.shop_owner,
            shop_type=Shop.Type.INTERNAL,
            is_active=True,
        )
        self.external_shop = Shop.objects.create(
            name='External Shop',
            description='An external shop',
            address='Downtown Mall',
            owner=self.external_shop_owner,
            shop_type=Shop.Type.EXTERNAL,
            is_active=True,
        )
        self.inactive_shop = Shop.objects.create(
            name='Inactive Shop',
            description='An inactive shop',
            owner=self.inactive_shop_owner,
            shop_type=Shop.Type.INTERNAL,
            is_active=False,
        )

        # Shop Items
        self.item = ShopItem.objects.create(
            shop=self.internal_shop,
            title='Test Item',
            description='A test item',
            price=100,
            is_active=True,
        )
        self.external_item = ShopItem.objects.create(
            shop=self.external_shop,
            title='External Item',
            description='An external item',
            price=150,
            is_active=True,
        )
        self.expensive_item = ShopItem.objects.create(
            shop=self.internal_shop,
            title='Expensive Item',
            description='Too expensive for low-points student',
            price=1000,
            is_active=True,
        )
        self.inactive_item = ShopItem.objects.create(
            shop=self.internal_shop,
            title='Inactive Item',
            description='An inactive item',
            price=50,
            is_active=False,
        )

        # Purchases
        self.pending_purchase = Purchase.objects.create(
            student=self.student,
            item=self.item,
            points_spent=self.item.price,
            status=Purchase.Status.PENDING,
        )
        self.ready_purchase = Purchase.objects.create(
            student=self.student,
            item=self.external_item,
            points_spent=self.external_item.price,
            status=Purchase.Status.READY,
            promo_code='TESTCODE',
        )


# ═══════════════════════════════════════════════════════════════════
# Public endpoints (any authenticated user)
# ═══════════════════════════════════════════════════════════════════


class ShopListViewTests(ShopAPITestCase):
    """Tests for GET /api/shop/shops/ (public list of active shops)."""

    def test_get_shop_list_authenticated(self):
        """Authenticated user can successfully get active shop list."""
        self.client.force_authenticate(self.student)
        response = self.client.get(reverse('shop_list'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('results', data)
        self.assertEqual(len(data['results']), 2)
        shop_names = [shop['name'] for shop in data['results']]
        self.assertIn('Internal Shop', shop_names)
        self.assertIn('External Shop', shop_names)

    def test_get_shop_list_unauthenticated(self):
        """Unauthenticated user gets 401."""
        response = self.client.get(reverse('shop_list'))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_shop_list_search_no_results(self):
        """Search with a non-matching query returns empty list."""
        self.client.force_authenticate(self.student)
        response = self.client.get(
            reverse('shop_list'), {'search': 'NonExistentShopName'},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('results', data)
        self.assertEqual(len(data['results']), 0)


class ShopDetailViewTests(ShopAPITestCase):
    """Tests for GET /api/shop/shops/<shop_id>/ (public shop detail)."""

    def test_get_shop_detail_active(self):
        """Authenticated user can get detail of an active shop."""
        self.client.force_authenticate(self.student)
        response = self.client.get(
            reverse('shop_detail', args=[self.internal_shop.pk]),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['name'], 'Internal Shop')
        self.assertEqual(data['shop_type'], Shop.Type.INTERNAL)

    def test_get_shop_detail_nonexistent(self):
        """Getting detail of non-existent shop returns 404."""
        self.client.force_authenticate(self.student)
        response = self.client.get(reverse('shop_detail', args=[99999]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_shop_detail_inactive(self):
        """Getting detail of inactive shop returns 404."""
        self.client.force_authenticate(self.student)
        response = self.client.get(
            reverse('shop_detail', args=[self.inactive_shop.pk]),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class ShopItemListViewTests(ShopAPITestCase):
    """Tests for GET /api/shop/shops/<shop_id>/items/ (public item list)."""

    def test_get_shop_item_list_active(self):
        """Authenticated user can get active items for a shop."""
        self.client.force_authenticate(self.student)
        response = self.client.get(
            reverse('shop_item_list', args=[self.internal_shop.pk]),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('results', data)
        self.assertEqual(len(data['results']), 2)
        item_titles = [item['title'] for item in data['results']]
        self.assertIn('Test Item', item_titles)
        self.assertIn('Expensive Item', item_titles)

    def test_get_shop_item_list_nonexistent_shop(self):
        """Getting items for non-existent shop returns 404."""
        self.client.force_authenticate(self.student)
        response = self.client.get(reverse('shop_item_list', args=[99999]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_shop_item_list_inactive_shop(self):
        """Getting items for inactive shop returns 404."""
        self.client.force_authenticate(self.student)
        response = self.client.get(
            reverse('shop_item_list', args=[self.inactive_shop.pk]),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

# ═══════════════════════════════════════════════════════════════════
# Student endpoints
# ═══════════════════════════════════════════════════════════════════


@override_settings(**NO_THROTTLE_SETTINGS)
class BuyItemViewTests(ShopAPITestCase):
    """Tests for POST /api/shop/items/<item_id>/buy/ (student purchase)."""

    def test_buy_item_success(self):
        """Student can successfully purchase an item with enough points."""
        self.client.force_authenticate(self.student)
        initial_points = self.student.points

        response = self.client.post(
            reverse('buy_item', args=[self.item.pk]),
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data['item_id'], self.item.pk)
        self.assertEqual(data['item_title'], 'Test Item')
        self.assertEqual(data['points_spent'], self.item.price)
        self.assertIn('remaining_points', data)
        expected_remaining = initial_points - self.item.price
        self.assertEqual(data['remaining_points'], expected_remaining)

        self.student.refresh_from_db()
        self.assertEqual(self.student.points, expected_remaining)

    def test_buy_item_non_student_forbidden(self):
        """Non-student (e.g., shop owner) cannot purchase items."""
        self.client.force_authenticate(self.shop_owner)
        response = self.client.post(
            reverse('buy_item', args=[self.item.pk]),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_buy_item_insufficient_points(self):
        """Student with insufficient points gets an error."""
        self.client.force_authenticate(self.student_low_points)
        response = self.client.post(
            reverse('buy_item', args=[self.expensive_item.pk]),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class MyPurchasesViewTests(ShopAPITestCase):
    """Tests for GET /api/shop/my-purchases/ (student purchase history)."""

    def test_get_my_purchases_success(self):
        """Student can get their own purchase history."""
        self.client.force_authenticate(self.student)
        response = self.client.get(reverse('my_purchases'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('results', data)
        self.assertEqual(len(data['results']), 2)

    def test_get_my_purchases_non_student_forbidden(self):
        """Non-student (e.g., organization) cannot access my-purchases."""
        self.client.force_authenticate(self.organization)
        response = self.client.get(reverse('my_purchases'))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_my_purchases_unauthenticated(self):
        """Unauthenticated user gets 401."""
        response = self.client.get(reverse('my_purchases'))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

# ═══════════════════════════════════════════════════════════════════
# Shop owner endpoints
# ═══════════════════════════════════════════════════════════════════


class MyShopViewGetTests(ShopAPITestCase):
    """Tests for GET /api/shop/my/ (shop owner reads own shop)."""

    def test_get_my_shop_success(self):
        """Shop owner can successfully retrieve their own shop."""
        self.client.force_authenticate(self.shop_owner)
        response = self.client.get(reverse('my_shop'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['name'], 'Internal Shop')
        self.assertEqual(data['owner_name'], 'Shop Owner')

    def test_get_my_shop_no_shop(self):
        """Shop owner without a shop gets 404."""
        self.client.force_authenticate(self.shop_owner_no_shop)
        response = self.client.get(reverse('my_shop'))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_my_shop_non_owner_forbidden(self):
        """Non-shop-owner cannot access my-shop."""
        self.client.force_authenticate(self.student)
        response = self.client.get(reverse('my_shop'))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class MyShopViewPatchTests(ShopAPITestCase):
    """Tests for PATCH /api/shop/my/ (shop owner updates own shop)."""

    def test_patch_my_shop_success(self):
        """Shop owner can successfully update their shop."""
        self.client.force_authenticate(self.shop_owner)
        payload = {
            'name': 'Updated Shop Name',
            'description': 'Updated description',
        }
        response = self.client.patch(
            reverse('my_shop'), payload, format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['name'], 'Updated Shop Name')
        self.assertEqual(data['description'], 'Updated description')

        self.internal_shop.refresh_from_db()
        self.assertEqual(self.internal_shop.name, 'Updated Shop Name')

    def test_patch_my_shop_no_shop(self):
        """Shop owner without a shop gets 404 on patch."""
        self.client.force_authenticate(self.shop_owner_no_shop)
        payload = {'name': 'New Shop'}
        response = self.client.patch(
            reverse('my_shop'), payload, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_patch_my_shop_duplicate_name(self):
        """Updating to a duplicate shop name returns 400."""
        self.client.force_authenticate(self.shop_owner)
        payload = {'name': 'External Shop'}
        response = self.client.patch(
            reverse('my_shop'), payload, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class CreateShopItemViewTests(ShopAPITestCase):
    """Tests for POST /api/shop/my/items/ (shop owner creates item)."""

    def test_create_shop_item_success(self):
        """Shop owner can successfully create an item for their shop."""
        self.client.force_authenticate(self.shop_owner)
        payload = {
            'title': 'New Item',
            'description': 'A brand new item',
            'price': 200,
        }
        response = self.client.post(
            reverse('create_shop_item'), payload, format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data['title'], 'New Item')
        self.assertEqual(data['price'], 200)
        self.assertEqual(data['shop_id'], self.internal_shop.pk)
        self.assertTrue(data['is_active'])

    def test_create_shop_item_non_owner_forbidden(self):
        """Non-shop-owner cannot create items."""
        self.client.force_authenticate(self.student)
        payload = {'title': 'Hacked Item', 'price': 100}
        response = self.client.post(
            reverse('create_shop_item'), payload, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_shop_item_invalid_price(self):
        """Creating item with invalid price (zero) returns 400."""
        self.client.force_authenticate(self.shop_owner)
        payload = {'title': 'Zero Price Item', 'price': 0}
        response = self.client.post(
            reverse('create_shop_item'), payload, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class ManageShopItemViewPatchTests(ShopAPITestCase):
    """Tests for PATCH /api/shop/my/items/<item_id>/ (update item)."""

    def test_patch_shop_item_success(self):
        """Shop owner can update their own item."""
        self.client.force_authenticate(self.shop_owner)
        payload = {'title': 'Updated Item Title', 'price': 250}
        response = self.client.patch(
            reverse('manage_shop_item', args=[self.item.pk]),
            payload,
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['title'], 'Updated Item Title')
        self.assertEqual(data['price'], 250)

    def test_patch_shop_item_non_owner_forbidden(self):
        """Non-shop-owner cannot update items."""
        self.client.force_authenticate(self.student)
        payload = {'title': 'Hacked'}
        response = self.client.patch(
            reverse('manage_shop_item', args=[self.item.pk]),
            payload,
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_patch_shop_item_other_shops_item(self):
        """Owner cannot update items from another shop (404)."""
        self.client.force_authenticate(self.shop_owner)
        payload = {'title': 'Hacked External Item'}
        response = self.client.patch(
            reverse('manage_shop_item', args=[self.external_item.pk]),
            payload,
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

class ManageShopItemViewDeleteTests(ShopAPITestCase):
    """Tests for DELETE /api/shop/my/items/<item_id>/ (soft-delete)."""

    def test_delete_shop_item_success(self):
        """Shop owner can soft-delete their own item."""
        self.client.force_authenticate(self.shop_owner)
        response = self.client.delete(
            reverse('manage_shop_item', args=[self.item.pk]),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('deactivated', data['detail'].lower())

        self.item.refresh_from_db()
        self.assertFalse(self.item.is_active)

    def test_delete_shop_item_non_owner_forbidden(self):
        """Non-shop-owner cannot delete items."""
        self.client.force_authenticate(self.student)
        response = self.client.delete(
            reverse('manage_shop_item', args=[self.item.pk]),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_shop_item_other_shops_item(self):
        """Owner cannot delete items from another shop (404)."""
        self.client.force_authenticate(self.shop_owner)
        response = self.client.delete(
            reverse('manage_shop_item', args=[self.external_item.pk]),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

class ShopPurchasesViewTests(ShopAPITestCase):
    """Tests for GET /api/shop/my/purchases/ (browse shop purchases)."""

    def test_get_shop_purchases_success(self):
        """Shop owner can browse purchases for their shop."""
        self.client.force_authenticate(self.shop_owner)
        response = self.client.get(reverse('shop_purchases'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('results', data)
        self.assertEqual(len(data['results']), 1)

    def test_get_shop_purchases_non_owner_forbidden(self):
        """Non-shop-owner cannot browse purchases."""
        self.client.force_authenticate(self.student)
        response = self.client.get(reverse('shop_purchases'))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_shop_purchases_no_shop(self):
        """Shop owner without a shop gets 404."""
        self.client.force_authenticate(self.shop_owner_no_shop)
        response = self.client.get(reverse('shop_purchases'))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

class ConfirmPurchaseViewTests(ShopAPITestCase):
    """Tests for PATCH /api/shop/purchases/<purchase_id>/confirm/."""

    def test_confirm_purchase_completed(self):
        """Shop owner can confirm a pending purchase (completed)."""
        self.client.force_authenticate(self.shop_owner)
        payload = {'status': Purchase.Status.COMPLETED}
        response = self.client.patch(
            reverse('confirm_purchase', args=[self.pending_purchase.pk]),
            payload,
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['status'], Purchase.Status.COMPLETED)

        self.pending_purchase.refresh_from_db()
        self.assertEqual(self.pending_purchase.status, Purchase.Status.COMPLETED)

    def test_confirm_purchase_rejected(self):
        """Shop owner can reject a pending purchase with points refunded."""
        initial_student_points = self.student.points
        self.client.force_authenticate(self.shop_owner)
        payload = {'status': Purchase.Status.REJECTED}
        response = self.client.patch(
            reverse('confirm_purchase', args=[self.pending_purchase.pk]),
            payload,
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['status'], Purchase.Status.REJECTED)

        self.student.refresh_from_db()
        self.assertEqual(self.student.points, initial_student_points + self.item.price)

    def test_confirm_purchase_wrong_shop_type(self):
        """Confirm fails for external shop purchases."""
        self.client.force_authenticate(self.external_shop_owner)
        payload = {'status': Purchase.Status.COMPLETED}
        ext_purchase = Purchase.objects.create(
            student=self.student,
            item=self.external_item,
            points_spent=self.external_item.price,
            status=Purchase.Status.PENDING,
        )
        response = self.client.patch(
            reverse('confirm_purchase', args=[ext_purchase.pk]),
            payload,
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

@override_settings(**NO_THROTTLE_SETTINGS)
class VerifyPromoCodeViewTests(ShopAPITestCase):
    """Tests for POST /api/shop/my/verify-code/ (external shop)."""

    def test_verify_promo_code_success(self):
        """External shop owner can redeem a valid promo code."""
        self.client.force_authenticate(self.external_shop_owner)
        payload = {'code': self.ready_purchase.promo_code}
        response = self.client.post(
            reverse('verify_promo_code'), payload, format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['status'], Purchase.Status.COMPLETED)

    def test_verify_promo_code_internal_shop_forbidden(self):
        """Internal shop owner cannot use verify-code endpoint."""
        self.client.force_authenticate(self.shop_owner)
        payload = {'code': 'SOMECODE'}
        response = self.client.post(
            reverse('verify_promo_code'), payload, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_verify_promo_code_invalid_code(self):
        """Invalid promo code returns an error."""
        self.client.force_authenticate(self.external_shop_owner)
        payload = {'code': 'INVALID1'}
        response = self.client.post(
            reverse('verify_promo_code'), payload, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

# ═══════════════════════════════════════════════════════════════════
# Admin endpoints
# ═══════════════════════════════════════════════════════════════════


class AdminCreateShopViewTests(ShopAPITestCase):
    """Tests for POST /api/shop/admin/shops/create/ (admin creates shop)."""

    def test_admin_create_shop_success(self):
        """Admin can successfully create a shop."""
        self.client.force_authenticate(self.admin)
        payload = {
            'name': 'New Admin Shop',
            'description': 'Created by admin',
            'shop_type': Shop.Type.INTERNAL,
            'owner_id': self.shop_owner_no_shop.pk,
        }
        response = self.client.post(
            reverse('admin_create_shop'), payload, format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data['name'], 'New Admin Shop')
        self.assertEqual(data['owner_id'], self.shop_owner_no_shop.pk)
        self.assertTrue(data['is_active'])

        self.assertTrue(Shop.objects.filter(name='New Admin Shop').exists())

    def test_admin_create_shop_non_admin_forbidden(self):
        """Non-admin user cannot create shops."""
        self.client.force_authenticate(self.shop_owner)
        payload = {
            'name': 'Unauthorized Shop',
            'shop_type': Shop.Type.INTERNAL,
            'owner_id': self.shop_owner.pk,
        }
        response = self.client.post(
            reverse('admin_create_shop'), payload, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_create_shop_duplicate_name(self):
        """Creating shop with a duplicate name returns 400."""
        self.client.force_authenticate(self.admin)
        payload = {
            'name': 'Internal Shop',
            'shop_type': Shop.Type.INTERNAL,
            'owner_id': self.shop_owner_no_shop.pk,
        }
        response = self.client.post(
            reverse('admin_create_shop'), payload, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class AdminShopListViewTests(ShopAPITestCase):
    """Tests for GET /api/shop/admin/shops/ (admin list all shops)."""

    def test_admin_get_shop_list_success(self):
        """Admin can list all shops including inactive ones."""
        self.client.force_authenticate(self.admin)
        response = self.client.get(reverse('admin_shop_list'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('results', data)
        self.assertEqual(len(data['results']), 3)

    def test_admin_get_shop_list_non_admin_forbidden(self):
        """Non-admin user cannot list shops via admin endpoint."""
        self.client.force_authenticate(self.shop_owner)
        response = self.client.get(reverse('admin_shop_list'))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_get_shop_list_filter_inactive(self):
        """Admin can filter by is_active flag."""
        self.client.force_authenticate(self.admin)
        response = self.client.get(
            reverse('admin_shop_list'), {'is_active': 'false'},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('results', data)
        self.assertEqual(len(data['results']), 1)
        self.assertEqual(data['results'][0]['name'], 'Inactive Shop')

class AdminShopDetailViewGetTests(ShopAPITestCase):
    """Tests for GET /api/shop/admin/shops/<shop_id>/ (admin read any shop)."""

    def test_admin_get_shop_detail_success(self):
        """Admin can get detail of any shop."""
        self.client.force_authenticate(self.admin)
        response = self.client.get(
            reverse('admin_shop_detail', args=[self.inactive_shop.pk]),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['name'], 'Inactive Shop')
        self.assertFalse(data['is_active'])

    def test_admin_get_shop_detail_non_admin_forbidden(self):
        """Non-admin user cannot access admin shop detail."""
        self.client.force_authenticate(self.student)
        response = self.client.get(
            reverse('admin_shop_detail', args=[self.internal_shop.pk]),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_get_shop_detail_nonexistent(self):
        """Admin gets 404 for non-existent shop."""
        self.client.force_authenticate(self.admin)
        response = self.client.get(reverse('admin_shop_detail', args=[99999]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class AdminShopDetailViewPatchTests(ShopAPITestCase):
    """Tests for PATCH /api/shop/admin/shops/<shop_id>/ (admin update shop)."""

    def test_admin_patch_shop_success(self):
        """Admin can successfully update any shop."""
        self.client.force_authenticate(self.admin)
        payload = {
            'name': 'Admin Updated Shop',
            'description': 'Updated by admin',
        }
        response = self.client.patch(
            reverse('admin_shop_detail', args=[self.internal_shop.pk]),
            payload,
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['name'], 'Admin Updated Shop')

    def test_admin_patch_shop_non_admin_forbidden(self):
        """Non-admin user cannot update shops via admin endpoint."""
        self.client.force_authenticate(self.shop_owner)
        payload = {'name': 'Hacked Shop'}
        response = self.client.patch(
            reverse('admin_shop_detail', args=[self.internal_shop.pk]),
            payload,
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_patch_shop_invalid_owner_id(self):
        """Admin cannot update shop with non-existent owner_id."""
        self.client.force_authenticate(self.admin)
        payload = {'owner_id': 99999}
        response = self.client.patch(
            reverse('admin_shop_detail', args=[self.internal_shop.pk]),
            payload,
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class AdminShopDetailViewDeleteTests(ShopAPITestCase):
    """Tests for DELETE /api/shop/admin/shops/<shop_id>/ (admin deactivate)."""

    def test_admin_delete_shop_success(self):
        """Admin can deactivate any shop."""
        self.client.force_authenticate(self.admin)
        response = self.client.delete(
            reverse('admin_shop_detail', args=[self.internal_shop.pk]),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('deactivated', data['detail'].lower())

        self.internal_shop.refresh_from_db()
        self.assertFalse(self.internal_shop.is_active)

    def test_admin_delete_shop_non_admin_forbidden(self):
        """Non-admin user cannot deactivate shops."""
        self.client.force_authenticate(self.shop_owner)
        response = self.client.delete(
            reverse('admin_shop_detail', args=[self.internal_shop.pk]),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.internal_shop.refresh_from_db()
        self.assertTrue(self.internal_shop.is_active)

    def test_admin_delete_shop_nonexistent(self):
        """Admin cannot deactivate non-existent shop (404)."""
        self.client.force_authenticate(self.admin)
        response = self.client.delete(
            reverse('admin_shop_detail', args=[99999]),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
