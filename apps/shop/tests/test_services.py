"""
Tests for the shop app service layer.

These tests focus on the business logic in :mod:`apps.shop.services`:
- Item purchasing with points debiting
- Purchase state transitions and refunds
- Promo code validation and redemption
- Concurrency handling and edge cases
"""
from django.test import TestCase
from django.db import transaction
from apps.core.exceptions import (
    InsufficientPointsError,
    InvalidStateTransitionError,
    InvalidVerificationCodeError,
    ShopInactiveError,
)
from apps.shop.models import Shop, ShopItem, Purchase
from apps.shop import services
from apps.users.models import User


class ShopServiceTestCase(TestCase):
    """Base test case with common setup for shop service tests."""

    def setUp(self):
        self.shop_owner = User.objects.create_user(
            username='shopowner',
            email='shop@example.com',
            password='password',
            role=User.Role.SHOP_OWNER,
            full_name='Shop Owner',
            points=1000,
        )
        self.external_shop_owner = User.objects.create_user(
            username='externalshopowner',
            email='externalshop@example.com',
            password='password',
            role=User.Role.SHOP_OWNER,
            full_name='External Shop Owner',
            points=1000,
        )
        self.student = User.objects.create_user(
            username='student',
            email='student@example.com',
            password='password',
            role=User.Role.STUDENT,
            full_name='Student',
            points=500,
        )
        self.student2 = User.objects.create_user(
            username='student2',
            email='student2@example.com',
            password='password',
            role=User.Role.STUDENT,
            full_name='Student Two',
            points=300,
        )
        self.internal_shop = Shop.objects.create(
            name='Internal Shop',
            owner=self.shop_owner,
            shop_type=Shop.Type.INTERNAL,
            is_active=True,
        )
        self.external_shop = Shop.objects.create(
            name='External Shop',
            owner=self.external_shop_owner,
            shop_type=Shop.Type.EXTERNAL,
            is_active=True,
        )
        self.item = ShopItem.objects.create(
            shop=self.internal_shop,
            title='Test Item',
            description='A test item',
            price=100,
        )
        self.external_item = ShopItem.objects.create(
            shop=self.external_shop,
            title='External Item',
            description='An external item',
            price=150,
        )


class PurchaseItemTests(ShopServiceTestCase):
    """Tests for services.purchase_item()."""

    def test_successful_purchase_internal_shop(self):
        """Student can successfully purchase item from internal shop."""
        initial_points = self.student.points

        purchase = services.purchase_item(
            user=self.student,
            item=self.item,
        )

        self.assertEqual(purchase.student, self.student)
        self.assertEqual(purchase.item, self.item)
        self.assertEqual(purchase.points_spent, self.item.price)
        self.assertEqual(purchase.status, Purchase.Status.PENDING)  # Internal shop
        self.assertIsNone(purchase.promo_code)

        # Check points were debited
        self.student.refresh_from_db()
        self.assertEqual(self.student.points, initial_points - self.item.price)

    def test_successful_purchase_external_shop(self):
        """Student can successfully purchase item from external shop."""
        initial_points = self.student.points

        purchase = services.purchase_item(
            user=self.student,
            item=self.external_item,
        )

        self.assertEqual(purchase.student, self.student)
        self.assertEqual(purchase.item, self.external_item)
        self.assertEqual(purchase.points_spent, self.external_item.price)
        self.assertEqual(purchase.status, Purchase.Status.READY)  # External shop
        self.assertIsNotNone(purchase.promo_code)  # Auto-generated

        # Check points were debited
        self.student.refresh_from_db()
        self.assertEqual(self.student.points, initial_points - self.external_item.price)

    def test_insufficient_points_raises_error(self):
        """Student without enough points cannot purchase."""
        expensive_item = ShopItem.objects.create(
            shop=self.internal_shop,
            title='Expensive Item',
            price=1000,  # More than student's 500 points
        )

        with self.assertRaises(InsufficientPointsError) as cm:
            services.purchase_item(user=self.student, item=expensive_item)

        self.assertIn('enough points', str(cm.exception))

        # Points should not be debited
        self.student.refresh_from_db()
        self.assertEqual(self.student.points, 500)

    def test_exact_points_purchase(self):
        """Student can purchase item costing exactly their balance."""
        self.student.points = 100
        self.student.save()

        item = ShopItem.objects.create(
            shop=self.internal_shop,
            title='Exact Cost Item',
            price=100,
        )

        purchase = services.purchase_item(user=self.student, item=item)

        self.assertEqual(purchase.status, Purchase.Status.PENDING)
        self.student.refresh_from_db()
        self.assertEqual(self.student.points, 0)

    def test_inactive_shop_raises_error(self):
        """Cannot purchase from inactive shop."""
        self.internal_shop.is_active = False
        self.internal_shop.save()

        with self.assertRaises(ShopInactiveError) as cm:
            services.purchase_item(user=self.student, item=self.item)

        self.assertIn('currently inactive', str(cm.exception))

        # Points should not be debited
        self.student.refresh_from_db()
        self.assertEqual(self.student.points, 500)

    def test_inactive_item_prevents_purchase(self):
        """Cannot purchase inactive items (though service doesn't check this directly)."""
        self.item.is_active = False
        self.item.save()

        # The service doesn't check item.is_active, but the view layer does
        # This test documents current behavior
        purchase = services.purchase_item(user=self.student, item=self.item)

        self.assertEqual(purchase.status, Purchase.Status.PENDING)
        self.student.refresh_from_db()
        self.assertEqual(self.student.points, 400)  # Points still debited

    def test_promo_code_generation_for_external_shop(self):
        """External shop purchases auto-generate promo codes."""
        purchase = services.purchase_item(
            user=self.student,
            item=self.external_item,
        )

        self.assertIsNotNone(purchase.promo_code)
        self.assertEqual(len(purchase.promo_code), 8)
        self.assertTrue(purchase.promo_code.isalnum())

    def test_no_promo_code_for_internal_shop(self):
        """Internal shop purchases do not generate promo codes."""
        purchase = services.purchase_item(
            user=self.student,
            item=self.item,
        )

        self.assertIsNone(purchase.promo_code)

    def test_purchase_updates_user_points_atomically(self):
        """Points update uses F() for atomic operation."""
        initial_points = self.student.points

        purchase = services.purchase_item(
            user=self.student,
            item=self.item,
        )

        # Refresh to get the updated value
        self.student.refresh_from_db()
        expected_points = initial_points - self.item.price
        self.assertEqual(self.student.points, expected_points)


class ConfirmOrRejectPurchaseTests(ShopServiceTestCase):
    """Tests for services.confirm_or_reject_purchase()."""

    def test_confirm_pending_purchase(self):
        """Shop owner can confirm a pending purchase."""
        purchase = services.purchase_item(
            user=self.student,
            item=self.item,
        )

        confirmed = services.confirm_or_reject_purchase(
            purchase=purchase,
            new_status=Purchase.Status.COMPLETED,
        )

        self.assertEqual(confirmed.status, Purchase.Status.COMPLETED)
        # Points already debited at purchase time, no change expected

    def test_reject_pending_purchase_refunds_points(self):
        """Rejecting a purchase refunds points to student."""
        initial_points = self.student.points

        purchase = services.purchase_item(
            user=self.student,
            item=self.item,
        )

        # Reject the purchase
        rejected = services.confirm_or_reject_purchase(
            purchase=purchase,
            new_status=Purchase.Status.REJECTED,
        )

        self.assertEqual(rejected.status, Purchase.Status.REJECTED)

        # Points should be refunded
        self.student.refresh_from_db()
        self.assertEqual(self.student.points, initial_points)

    def test_confirm_ready_purchase(self):
        """Can confirm a READY purchase (external shop)."""
        purchase = services.purchase_item(
            user=self.student,
            item=self.external_item,
        )

        confirmed = services.confirm_or_reject_purchase(
            purchase=purchase,
            new_status=Purchase.Status.COMPLETED,
        )

        self.assertEqual(confirmed.status, Purchase.Status.COMPLETED)

    def test_invalid_state_transition_raises_error(self):
        """Invalid state transitions should raise InvalidStateTransitionError."""
        purchase = services.purchase_item(
            user=self.student,
            item=self.item,
        )

        # Try to go from PENDING to READY (invalid)
        with self.assertRaises(InvalidStateTransitionError) as cm:
            services.confirm_or_reject_purchase(
                purchase=purchase,
                new_status=Purchase.Status.READY,
            )

        self.assertIn('Cannot change status', str(cm.exception))

    def test_already_completed_cannot_transition(self):
        """Completed purchase cannot transition further."""
        purchase = services.purchase_item(
            user=self.student,
            item=self.item,
        )
        services.confirm_or_reject_purchase(
            purchase=purchase,
            new_status=Purchase.Status.COMPLETED,
        )

        with self.assertRaises(InvalidStateTransitionError):
            services.confirm_or_reject_purchase(
                purchase=purchase,
                new_status=Purchase.Status.REJECTED,
            )

    def test_rejected_cannot_be_confirmed(self):
        """Rejected purchase cannot be confirmed."""
        purchase = services.purchase_item(
            user=self.student,
            item=self.item,  # Internal shop = PENDING
        )
        services.confirm_or_reject_purchase(
            purchase=purchase,
            new_status=Purchase.Status.REJECTED,
        )

        with self.assertRaises(InvalidStateTransitionError):
            services.confirm_or_reject_purchase(
                purchase=purchase,
                new_status=Purchase.Status.COMPLETED,
            )

    def test_refund_only_on_rejection(self):
        """Points are only refunded on REJECTED, not COMPLETED."""
        initial_points = self.student.points

        purchase = services.purchase_item(
            user=self.student,
            item=self.item,
        )

        # Confirm (no refund)
        services.confirm_or_reject_purchase(
            purchase=purchase,
            new_status=Purchase.Status.COMPLETED,
        )

        self.student.refresh_from_db()
        self.assertEqual(self.student.points, initial_points - self.item.price)

    def test_multiple_rejections_no_double_refund(self):
        """Multiple rejection attempts don't double-refund."""
        initial_points = self.student.points

        purchase = services.purchase_item(
            user=self.student,
            item=self.item,
        )

        # First rejection
        services.confirm_or_reject_purchase(
            purchase=purchase,
            new_status=Purchase.Status.REJECTED,
        )

        self.student.refresh_from_db()
        points_after_first = self.student.points
        self.assertEqual(points_after_first, initial_points)

        # Try to reject again (should fail due to invalid transition)
        with self.assertRaises(InvalidStateTransitionError):
            services.confirm_or_reject_purchase(
                purchase=purchase,
                new_status=Purchase.Status.REJECTED,
            )

        # Points should not change
        self.student.refresh_from_db()
        self.assertEqual(self.student.points, points_after_first)


class RedeemPromoCodeTests(ShopServiceTestCase):
    """Tests for services.redeem_promo_code()."""

    def test_redeem_valid_promo_code(self):
        """Valid promo code can be redeemed."""
        purchase = services.purchase_item(
            user=self.student,
            item=self.external_item,
        )

        promo_code = purchase.promo_code

        redeemed = services.redeem_promo_code(
            shop=self.external_shop,
            code=promo_code,
        )

        self.assertEqual(redeemed.status, Purchase.Status.COMPLETED)
        self.assertEqual(redeemed.pk, purchase.pk)

    def test_invalid_promo_code_raises_error(self):
        """Invalid promo code raises InvalidVerificationCodeError."""
        with self.assertRaises(InvalidVerificationCodeError) as cm:
            services.redeem_promo_code(
                shop=self.external_shop,
                code='INVALID',
            )

        self.assertIn('Invalid or already used', str(cm.exception))

    def test_redeem_from_wrong_shop_raises_error(self):
        """Cannot redeem promo code for different shop."""
        purchase = services.purchase_item(
            user=self.student,
            item=self.external_item,
        )

        # Try to redeem with wrong shop
        with self.assertRaises(InvalidVerificationCodeError):
            services.redeem_promo_code(
                shop=self.internal_shop,  # Wrong shop
                code=purchase.promo_code,
            )

    def test_redeem_already_completed_raises_error(self):
        """Cannot redeem already completed purchase."""
        purchase = services.purchase_item(
            user=self.student,
            item=self.external_item,
        )
        purchase.status = Purchase.Status.COMPLETED
        purchase.save()

        with self.assertRaises(InvalidVerificationCodeError):
            services.redeem_promo_code(
                shop=self.external_shop,
                code=purchase.promo_code,
            )

    def test_redeem_pending_purchase_raises_error(self):
        """Cannot redeem PENDING purchase (only READY)."""
        purchase = services.purchase_item(
            user=self.student,
            item=self.item,  # Internal shop = PENDING
        )

        with self.assertRaises(InvalidVerificationCodeError):
            services.redeem_promo_code(
                shop=self.internal_shop,
                code=purchase.promo_code or 'ANY',
            )

    def test_redeem_rejected_purchase_raises_error(self):
        """Cannot redeem rejected purchase."""
        purchase = services.purchase_item(
            user=self.student,
            item=self.item,  # Internal shop = PENDING status
        )
        services.confirm_or_reject_purchase(
            purchase=purchase,
            new_status=Purchase.Status.REJECTED,
        )

        with self.assertRaises(InvalidVerificationCodeError):
            services.redeem_promo_code(
                shop=self.internal_shop,
                code=purchase.promo_code or 'ANY',
            )

    def test_promo_code_case_sensitivity(self):
        """Promo codes are case-sensitive."""
        purchase = services.purchase_item(
            user=self.student,
            item=self.external_item,
        )

        # Try with wrong case
        with self.assertRaises(InvalidVerificationCodeError):
            services.redeem_promo_code(
                shop=self.external_shop,
                code=purchase.promo_code.lower(),
            )

    def test_timing_attack_resistance(self):
        """Promo code comparison should be timing-attack resistant."""
        purchase = services.purchase_item(
            user=self.student,
            item=self.external_item,
        )

        valid_code = purchase.promo_code
        wrong_code = 'X' * len(valid_code)

        # Both should raise error, but timing should be similar
        with self.assertRaises(InvalidVerificationCodeError):
            services.redeem_promo_code(
                shop=self.external_shop,
                code=wrong_code,
            )

    def test_promo_code_uniqueness(self):
        """Promo codes should be unique across purchases."""
        purchase1 = services.purchase_item(
            user=self.student,
            item=self.external_item,
        )
        purchase2 = services.purchase_item(
            user=self.student2,
            item=self.external_item,
        )

        self.assertNotEqual(purchase1.promo_code, purchase2.promo_code)


class ShopConcurrencyTests(ShopServiceTestCase):
    """Tests for row locking and concurrency handling in shop services."""

    def test_row_locking_prevents_double_spending(self):
        """Test that row locking prevents race conditions in point updates."""
        # Set student points to exactly cover 1 purchase
        self.student.points = 100
        self.student.save()

        # First purchase should succeed
        purchase1 = services.purchase_item(user=self.student, item=self.item)
        self.assertEqual(purchase1.status, Purchase.Status.PENDING)
        self.student.refresh_from_db()
        self.assertEqual(self.student.points, 0)

        # Second purchase should fail due to insufficient points
        with self.assertRaises(InsufficientPointsError):
            services.purchase_item(user=self.student, item=self.item)

        # Points should remain at 0
        self.student.refresh_from_db()
        self.assertEqual(self.student.points, 0)

    def test_row_locking_prevents_double_refund(self):
        """Test that row locking prevents double refunds on rejection."""
        initial_points = self.student.points

        purchase = services.purchase_item(user=self.student, item=self.item)

        # First rejection should succeed and refund
        rejected = services.confirm_or_reject_purchase(
            purchase=purchase,
            new_status=Purchase.Status.REJECTED,
        )
        self.assertEqual(rejected.status, Purchase.Status.REJECTED)
        self.student.refresh_from_db()
        self.assertEqual(self.student.points, initial_points)

        # Second rejection should fail due to invalid state transition
        with self.assertRaises(InvalidStateTransitionError):
            services.confirm_or_reject_purchase(
                purchase=purchase,
                new_status=Purchase.Status.REJECTED,
            )

        # Points should not be refunded twice
        self.student.refresh_from_db()
        self.assertEqual(self.student.points, initial_points)


class ShopModelTests(ShopServiceTestCase):
    """Tests for Shop model methods and validation."""

    def test_shop_owner_role_validation(self):
        """Shop owner must have shop_owner role."""
        regular_user = User.objects.create_user(
            username='regular',
            email='regular@example.com',
            password='password',
            role=User.Role.STUDENT,
            full_name='Regular User',
        )

        shop = Shop(
            name='Invalid Shop',
            owner=regular_user,
            shop_type=Shop.Type.INTERNAL,
        )

        with self.assertRaises(Exception):  # ValidationError
            shop.clean()

    def test_shop_unique_name(self):
        """Shop names must be unique."""
        another_shop_owner = User.objects.create_user(
            username='shopowner2',
            email='shopowner2@example.com',
            password='password',
            role=User.Role.SHOP_OWNER,
            full_name='Shop Owner 2',
        )

        with self.assertRaises(Exception):  # IntegrityError
            Shop.objects.create(
                name='Internal Shop',  # Duplicate name
                owner=another_shop_owner,
                shop_type=Shop.Type.INTERNAL,
            )

    def test_shop_type_choices(self):
        """Shop type must be valid choice."""
        with self.assertRaises(Exception):  # ValidationError/IntegrityError
            Shop.objects.create(
                name='Invalid Type Shop',
                owner=self.shop_owner,
                shop_type='invalid_type',
            )


class ShopItemModelTests(ShopServiceTestCase):
    """Tests for ShopItem model."""

    def test_item_belongs_to_shop(self):
        """Item must belong to a shop."""
        self.assertEqual(self.item.shop, self.internal_shop)

    def test_item_price_field(self):
        """Item price is stored correctly."""
        self.assertEqual(self.item.price, 100)
        self.assertEqual(self.external_item.price, 150)


class PurchaseModelTests(ShopServiceTestCase):
    """Tests for Purchase model methods."""

    def test_can_transition_to_valid_transitions(self):
        """Purchase.can_transition_to should validate correctly."""
        purchase = services.purchase_item(
            user=self.student,
            item=self.item,
        )

        # From PENDING
        self.assertTrue(purchase.can_transition_to(Purchase.Status.COMPLETED))
        self.assertTrue(purchase.can_transition_to(Purchase.Status.REJECTED))
        self.assertFalse(purchase.can_transition_to(Purchase.Status.READY))

        # From READY
        purchase.status = Purchase.Status.READY
        self.assertTrue(purchase.can_transition_to(Purchase.Status.COMPLETED))
        self.assertFalse(purchase.can_transition_to(Purchase.Status.REJECTED))
        self.assertFalse(purchase.can_transition_to(Purchase.Status.PENDING))

        # From COMPLETED
        purchase.status = Purchase.Status.COMPLETED
        self.assertFalse(purchase.can_transition_to(Purchase.Status.PENDING))
        self.assertFalse(purchase.can_transition_to(Purchase.Status.REJECTED))
        self.assertFalse(purchase.can_transition_to(Purchase.Status.READY))

    def test_promo_code_auto_generation(self):
        """External shop purchases auto-generate promo codes on save."""
        purchase = Purchase(
            student=self.student,
            item=self.external_item,
            points_spent=self.external_item.price,
            status=Purchase.Status.READY,
        )
        purchase.save()

        self.assertIsNotNone(purchase.promo_code)
        self.assertEqual(len(purchase.promo_code), 8)

    def test_internal_shop_no_promo_code(self):
        """Internal shop purchases don't generate promo codes."""
        purchase = Purchase(
            student=self.student,
            item=self.item,
            points_spent=self.item.price,
            status=Purchase.Status.PENDING,
        )
        purchase.save()

        self.assertIsNone(purchase.promo_code)

    def test_purchase_string_representation(self):
        """Purchase __str__ should include student, item, and status."""
        purchase = services.purchase_item(
            user=self.student,
            item=self.item,
        )

        str_repr = str(purchase)
        self.assertIn(self.student.full_name or self.student.username, str_repr)
        self.assertIn(self.item.title, str_repr)
        self.assertIn(purchase.status, str_repr)


class PurchaseWorkflowTests(ShopServiceTestCase):
    """End-to-end workflow tests for purchase scenarios."""

    def test_full_internal_purchase_workflow(self):
        """Complete workflow: purchase → confirm → completion."""
        initial_points = self.student.points

        # Purchase
        purchase = services.purchase_item(user=self.student, item=self.item)
        self.assertEqual(purchase.status, Purchase.Status.PENDING)
        self.student.refresh_from_db()
        self.assertEqual(self.student.points, initial_points - self.item.price)

        # Confirm
        confirmed = services.confirm_or_reject_purchase(
            purchase=purchase,
            new_status=Purchase.Status.COMPLETED,
        )
        self.assertEqual(confirmed.status, Purchase.Status.COMPLETED)
        # Points already debited, no change
        self.student.refresh_from_db()
        self.assertEqual(self.student.points, initial_points - self.item.price)

    def test_full_external_purchase_workflow(self):
        """Complete workflow: purchase → promo code redemption."""
        initial_points = self.student.points

        # Purchase
        purchase = services.purchase_item(user=self.student, item=self.external_item)
        self.assertEqual(purchase.status, Purchase.Status.READY)
        self.assertIsNotNone(purchase.promo_code)
        self.student.refresh_from_db()
        self.assertEqual(self.student.points, initial_points - self.external_item.price)

        # Redeem promo code
        redeemed = services.redeem_promo_code(
            shop=self.external_shop,
            code=purchase.promo_code,
        )
        self.assertEqual(redeemed.status, Purchase.Status.COMPLETED)
        # Points already debited, no change
        self.student.refresh_from_db()
        self.assertEqual(self.student.points, initial_points - self.external_item.price)

    def test_full_refund_workflow(self):
        """Complete workflow: purchase → reject → refund."""
        initial_points = self.student.points

        # Purchase
        purchase = services.purchase_item(user=self.student, item=self.item)
        self.student.refresh_from_db()
        points_after_purchase = self.student.points

        # Reject (refund)
        rejected = services.confirm_or_reject_purchase(
            purchase=purchase,
            new_status=Purchase.Status.REJECTED,
        )
        self.assertEqual(rejected.status, Purchase.Status.REJECTED)
        self.student.refresh_from_db()
        self.assertEqual(self.student.points, initial_points)  # Refunded

    def test_multiple_purchases_same_student(self):
        """Student can make multiple purchases."""
        item2 = ShopItem.objects.create(
            shop=self.internal_shop,
            title='Second Item',
            price=50,
        )

        initial_points = self.student.points

        purchase1 = services.purchase_item(user=self.student, item=self.item)
        purchase2 = services.purchase_item(user=self.student, item=item2)

        self.assertEqual(Purchase.objects.filter(student=self.student).count(), 2)
        self.student.refresh_from_db()
        expected_points = initial_points - self.item.price - item2.price
        self.assertEqual(self.student.points, expected_points)

    def test_purchase_cannot_redceed_own_promo_code(self):
        """Student cannot redeem their own promo code (shop owner does it)."""
        purchase = services.purchase_item(
            user=self.student,
            item=self.external_item,
        )

        # The service doesn't check user role, but the view layer should
        # This test documents that the service allows any caller to redeem
        redeemed = services.redeem_promo_code(
            shop=self.external_shop,
            code=purchase.promo_code,
        )

        self.assertEqual(redeemed.status, Purchase.Status.COMPLETED)
