"""
HTTP endpoints for the ``shop`` app.

The flow is intentionally split across three roles: students browse/buy;
shop owners manage their catalogue and confirm/redeem purchases; admins own
CRUD across the whole estate. Points-accounting and state-machine logic live
in :mod:`apps.shop.services` — these views only parse HTTP input, call a
service, and serialise the response.
"""
from __future__ import annotations
from django.conf import settings

from django.db.models import Count, Q
from rest_framework import status
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.cache import (
    SHOP_CACHE,
    cached_response,
    invalidate_cache_families,
)
from apps.core.filters import apply_bool_filter, apply_exact_filter, apply_search
from apps.core.pagination import paginate
from apps.users.permissions import IsAdmin, IsShopOwner, IsStudent

from . import services
from .models import Purchase, Shop, ShopItem
from .serializers import (
    AdminUpdateShopSerializer,
    ConfirmPurchaseSerializer,
    CreateShopItemSerializer,
    CreateShopSerializer,
    MyPurchaseSerializer,
    ShopItemListSerializer,
    ShopItemSerializer,
    ShopListSerializer,
    ShopPurchaseSerializer,
    ShopSerializer,
    UpdateShopItemSerializer,
    UpdateShopSerializer,
    VerifyPromoCodeSerializer,
)


# ─── Helpers ───────────────────────────────────────────────────────


def _user_shop(user):
    """Return ``user.shop`` or ``None`` when the owner has no shop yet."""
    try:
        return user.shop
    except Shop.DoesNotExist:
        return None


def _shop_required(user):
    """Return ``(shop, None)`` or ``(None, 404 response)`` for shop owners."""
    shop = _user_shop(user)
    if shop is None:
        return None, Response(
            {'error': 'You do not have a shop assigned.'},
            status=status.HTTP_404_NOT_FOUND,
        )
    return shop, None


# ─── Public endpoints (any authenticated user) ─────────────────────


class ShopListView(APIView):
    """Public catalogue of active shops with search + type filter."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        def build_response():
            shops = Shop.objects.filter(is_active=True).select_related('owner')
            shops = apply_search(shops, request, ['name'])
            shops = apply_exact_filter(shops, request, 'type', field='shop_type')
            shops = shops.annotate(
                _items_count=Count('items', filter=Q(items__is_active=True)),
            )
            return paginate(shops.order_by('-created_at'), request, ShopListSerializer)

        return cached_response(
            request, SHOP_CACHE, settings.CACHE_TTL_SHOP_LIST, build_response,
        )


class ShopDetailView(APIView):
    """Public read-only view of one active shop."""

    permission_classes = [IsAuthenticated]

    def get(self, request, shop_id):
        return cached_response(
            request,
            SHOP_CACHE,
            settings.CACHE_TTL_DETAIL,
            lambda: Response(ShopSerializer(get_object_or_404(
                Shop.objects.select_related('owner'), pk=shop_id, is_active=True,
            )).data),
        )


class ShopItemListView(APIView):
    """Public paginated list of active items for a given shop."""

    permission_classes = [IsAuthenticated]

    def get(self, request, shop_id):
        def build_response():
            get_object_or_404(Shop, pk=shop_id, is_active=True)
            items = ShopItem.objects.filter(
                shop_id=shop_id, is_active=True,
            ).select_related('shop')
            return paginate(items.order_by('-created_at'), request, ShopItemListSerializer)

        return cached_response(
            request, SHOP_CACHE, settings.CACHE_TTL_SHOP_ITEMS, build_response,
        )


# ─── Student endpoints ─────────────────────────────────────────


class BuyItemView(APIView):
    """Student purchases an item — the service layer owns the transaction."""

    permission_classes = [IsAuthenticated, IsStudent]
    throttle_scope = 'purchases'

    def post(self, request, item_id):
        item = get_object_or_404(
            ShopItem.objects.select_related('shop'),
            pk=item_id, is_active=True,
        )
        purchase = services.purchase_item(user=request.user, item=item)
        invalidate_cache_families(SHOP_CACHE)

        request.user.refresh_from_db(fields=['points'])
        data = MyPurchaseSerializer(purchase).data
        data['remaining_points'] = request.user.points
        return Response(data, status=status.HTTP_201_CREATED)


class MyPurchasesView(APIView):
    """Student's own purchase history, filterable by ``?status=``."""

    permission_classes = [IsAuthenticated, IsStudent]

    def get(self, request):
        purchases = Purchase.objects.filter(
            student=request.user,
        ).select_related('item', 'item__shop')
        purchases = apply_exact_filter(purchases, request, 'status')
        return paginate(purchases.order_by('-created_at'), request, MyPurchaseSerializer)


# ─── Shop owner endpoints ─────────────────────────────────────


class MyShopView(APIView):
    """Self-service read/patch for the authenticated shop owner."""

    permission_classes = [IsAuthenticated, IsShopOwner]

    def get(self, request):
        shop, error = _shop_required(request.user)
        if error is not None:
            return error
        return Response(ShopSerializer(shop).data)

    def patch(self, request):
        shop, error = _shop_required(request.user)
        if error is not None:
            return error
        serializer = UpdateShopSerializer(
            shop, data=request.data, partial=True,
        )
        serializer.is_valid(raise_exception=True)
        response = Response(ShopSerializer(serializer.save()).data)
        invalidate_cache_families(SHOP_CACHE)
        return response


class CreateShopItemView(APIView):
    """Shop owner adds a new item to their own shop."""

    permission_classes = [IsAuthenticated, IsShopOwner]

    def post(self, request):
        shop, error = _shop_required(request.user)
        if error is not None:
            return error
        serializer = CreateShopItemSerializer(
            data=request.data, context={'shop': shop},
        )
        serializer.is_valid(raise_exception=True)
        item = serializer.save()
        invalidate_cache_families(SHOP_CACHE)
        return Response(
            ShopItemSerializer(item).data, status=status.HTTP_201_CREATED,
        )


class ManageShopItemView(APIView):
    """Shop owner updates or soft-deletes one of their own items."""

    permission_classes = [IsAuthenticated, IsShopOwner]

    def _get_item(self, user, item_id):
        """Return ``(item, None)`` or ``(None, 4xx response)``."""
        shop, error = _shop_required(user)
        if error is not None:
            return None, error
        item = get_object_or_404(
            ShopItem.objects.select_related('shop'), pk=item_id, shop=shop,
        )
        return item, None

    def patch(self, request, item_id):
        item, error = self._get_item(request.user, item_id)
        if error is not None:
            return error
        serializer = UpdateShopItemSerializer(
            item, data=request.data, partial=True,
        )
        serializer.is_valid(raise_exception=True)
        response = Response(ShopItemSerializer(serializer.save()).data)
        invalidate_cache_families(SHOP_CACHE)
        return response

    def delete(self, request, item_id):
        item, error = self._get_item(request.user, item_id)
        if error is not None:
            return error
        item.is_active = False
        item.save(update_fields=['is_active'])
        invalidate_cache_families(SHOP_CACHE)
        return Response({'detail': 'Item deactivated.'})


class ShopPurchasesView(APIView):
    """Shop owner browses purchases made at their shop."""

    permission_classes = [IsAuthenticated, IsShopOwner]

    def get(self, request):
        shop, error = _shop_required(request.user)
        if error is not None:
            return error
        purchases = Purchase.objects.filter(
            item__shop=shop,
        ).select_related('student', 'item')
        purchases = apply_exact_filter(purchases, request, 'status')
        return paginate(purchases.order_by('-created_at'), request, ShopPurchaseSerializer)


class ConfirmPurchaseView(APIView):
    """Internal-shop owner approves or rejects a pending purchase."""

    permission_classes = [IsAuthenticated, IsShopOwner]

    def patch(self, request, purchase_id):
        serializer = ConfirmPurchaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_status = serializer.validated_data['status']

        purchase = get_object_or_404(
            Purchase.objects.select_related('item', 'item__shop', 'student'),
            pk=purchase_id,
            item__shop__owner=request.user,
        )
        if purchase.item.shop.shop_type != Shop.Type.INTERNAL:
            return Response(
                {'error': 'This operation is only for internal shops. Use verify-code for external.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        services.confirm_or_reject_purchase(
            purchase=purchase, new_status=new_status,
        )
        # Only ``status``/``updated_at`` change — keep the select_related cache
        # intact so the serializer renders without extra queries.
        purchase.refresh_from_db(fields=['status', 'updated_at'])
        return Response(ShopPurchaseSerializer(purchase).data)


class VerifyPromoCodeView(APIView):
    """External-shop owner redeems a promo code to complete a purchase."""

    permission_classes = [IsAuthenticated, IsShopOwner]
    throttle_scope = 'purchases'

    def post(self, request):
        serializer = VerifyPromoCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        shop, error = _shop_required(request.user)
        if error is not None:
            return error
        if shop.shop_type != Shop.Type.EXTERNAL:
            return Response(
                {'error': 'This operation is only for external shops. Use confirm for internal.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        purchase = services.redeem_promo_code(
            shop=shop, code=serializer.validated_data['code'],
        )
        # Re-fetch with select_related for a clean, N+1-free response.
        purchase = Purchase.objects.select_related(
            'student', 'item',
        ).get(pk=purchase.pk)
        return Response(ShopPurchaseSerializer(purchase).data)


# ─── Admin endpoints ──────────────────────────────────────────


class AdminCreateShopView(APIView):
    """Admin creates a shop and assigns it to a ``shop_owner`` user."""

    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request):
        serializer = CreateShopSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        shop = serializer.save()
        invalidate_cache_families(SHOP_CACHE)
        return Response(
            ShopSerializer(shop).data, status=status.HTTP_201_CREATED,
        )


class AdminShopListView(APIView):
    """Admin-only paginated list with ``?is_active=``, ``?search=``, ``?type=``."""

    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        shops = Shop.objects.select_related('owner').all()
        shops = apply_bool_filter(shops, request, 'is_active')
        shops = apply_search(shops, request, ['name'])
        shops = apply_exact_filter(shops, request, 'type', field='shop_type')
        return paginate(shops.order_by('-created_at'), request, ShopSerializer)


class AdminShopDetailView(APIView):
    """Admin read/update/soft-delete of any shop."""

    permission_classes = [IsAuthenticated, IsAdmin]

    def _get(self, shop_id):
        return get_object_or_404(
            Shop.objects.select_related('owner'), pk=shop_id,
        )

    def get(self, request, shop_id):
        return Response(ShopSerializer(self._get(shop_id)).data)

    def patch(self, request, shop_id):
        shop = self._get(shop_id)
        serializer = AdminUpdateShopSerializer(
            shop, data=request.data, partial=True,
        )
        serializer.is_valid(raise_exception=True)
        response = Response(ShopSerializer(serializer.save()).data)
        invalidate_cache_families(SHOP_CACHE)
        return response

    def delete(self, request, shop_id):
        shop = self._get(shop_id)
        shop.is_active = False
        shop.save(update_fields=['is_active'])
        invalidate_cache_families(SHOP_CACHE)
        return Response({'detail': 'Shop deactivated.'})
