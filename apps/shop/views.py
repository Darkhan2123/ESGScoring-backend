from django.db import transaction
from django.db.models import Count, F, Q
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import (
    InsufficientPointsError,
    InvalidStateTransitionError,
    InvalidVerificationCodeError,
    ShopInactiveError,
)
from apps.users.models import User
from apps.users.permissions import IsAdmin, IsShopOwner, IsStudent
from .models import Shop, ShopItem, Purchase
from .serializers import (
    ShopListSerializer,
    ShopSerializer,
    CreateShopSerializer,
    UpdateShopSerializer,
    AdminUpdateShopSerializer,
    ShopItemListSerializer,
    ShopItemSerializer,
    CreateShopItemSerializer,
    UpdateShopItemSerializer,
    MyPurchaseSerializer,
    ShopPurchaseSerializer,
    ConfirmPurchaseSerializer,
    VerifyPromoCodeSerializer,
)


def _get_shop_or_404(user):
    """Get the shop owned by this user, or return None."""
    try:
        return user.shop
    except Shop.DoesNotExist:
        return None


# ─── Public endpoints (any authenticated user) ─────────────────


class ShopListView(APIView):
    """
    GET /api/shop/shops/
    List all active shops.
    Supports ?search=name and ?type=internal/external filters.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        shops = Shop.objects.filter(
            is_active=True,
        ).select_related('owner')

        search = request.query_params.get('search')
        if search:
            shops = shops.filter(name__icontains=search)

        shop_type = request.query_params.get('type')
        if shop_type:
            shops = shops.filter(shop_type=shop_type)

        shops = shops.annotate(
            _items_count=Count(
                'items', filter=Q(items__is_active=True),
            ),
        )

        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(shops, request)
        return paginator.get_paginated_response(
            ShopListSerializer(page, many=True).data,
        )


class ShopDetailView(APIView):
    """
    GET /api/shop/shops/<id>/
    View shop detail.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, shop_id):
        try:
            shop = Shop.objects.select_related('owner').get(
                pk=shop_id, is_active=True,
            )
        except Shop.DoesNotExist:
            return Response(
                {'error': 'Shop not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(ShopSerializer(shop).data)


class ShopItemListView(APIView):
    """
    GET /api/shop/shops/<id>/items/
    List active items for a shop.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, shop_id):
        try:
            Shop.objects.get(pk=shop_id, is_active=True)
        except Shop.DoesNotExist:
            return Response(
                {'error': 'Shop not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        items = ShopItem.objects.filter(
            shop_id=shop_id, is_active=True,
        ).select_related('shop')

        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(items, request)
        return paginator.get_paginated_response(
            ShopItemListSerializer(page, many=True).data,
        )


# ─── Student endpoints ─────────────────────────────────────────


class BuyItemView(APIView):
    """
    POST /api/shop/items/<id>/buy/
    Student buys an item — points deducted atomically.
    """
    permission_classes = [IsAuthenticated, IsStudent]

    def post(self, request, item_id):
        try:
            item = ShopItem.objects.select_related('shop').get(
                pk=item_id, is_active=True,
            )
        except ShopItem.DoesNotExist:
            return Response(
                {'error': 'Item not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not item.shop.is_active:
            raise ShopInactiveError('This shop is currently inactive.')

        with transaction.atomic():
            user = User.objects.select_for_update().get(
                pk=request.user.pk,
            )
            if user.points < item.price:
                raise InsufficientPointsError(
                    'You do not have enough points for this purchase.'
                )

            User.objects.filter(pk=user.pk).update(
                points=F('points') - item.price,
            )

            initial_status = (
                Purchase.Status.PENDING
                if item.shop.shop_type == Shop.Type.INTERNAL
                else Purchase.Status.READY
            )
            purchase = Purchase(
                student=user,
                item=item,
                points_spent=item.price,
                status=initial_status,
            )
            purchase.save()

        request.user.refresh_from_db()
        data = MyPurchaseSerializer(purchase).data
        data['remaining_points'] = request.user.points
        return Response(data, status=status.HTTP_201_CREATED)


class MyPurchasesView(APIView):
    """
    GET /api/shop/my-purchases/
    Student views their own purchases.
    Supports ?status= filter.
    """
    permission_classes = [IsAuthenticated, IsStudent]

    def get(self, request):
        purchases = Purchase.objects.filter(
            student=request.user,
        ).select_related('item', 'item__shop')

        purchase_status = request.query_params.get('status')
        if purchase_status:
            purchases = purchases.filter(status=purchase_status)

        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(purchases, request)
        return paginator.get_paginated_response(
            MyPurchaseSerializer(page, many=True).data,
        )


# ─── Shop owner endpoints ─────────────────────────────────────


class MyShopView(APIView):
    """
    GET  /api/shop/my/  → view own shop profile
    PATCH /api/shop/my/ → update own shop profile
    """
    permission_classes = [IsAuthenticated, IsShopOwner]

    def get(self, request):
        shop = _get_shop_or_404(request.user)
        if shop is None:
            return Response(
                {'error': 'You do not have a shop assigned.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(ShopSerializer(shop).data)

    def patch(self, request):
        shop = _get_shop_or_404(request.user)
        if shop is None:
            return Response(
                {'error': 'You do not have a shop assigned.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = UpdateShopSerializer(
            shop, data=request.data, partial=True,
        )
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()
        return Response(ShopSerializer(updated).data)


class CreateShopItemView(APIView):
    """
    POST /api/shop/my/items/
    Shop owner creates a new item.
    """
    permission_classes = [IsAuthenticated, IsShopOwner]

    def post(self, request):
        shop = _get_shop_or_404(request.user)
        if shop is None:
            return Response(
                {'error': 'You do not have a shop assigned.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = CreateShopItemSerializer(
            data=request.data, context={'shop': shop},
        )
        serializer.is_valid(raise_exception=True)
        item = serializer.save()
        return Response(
            ShopItemSerializer(item).data,
            status=status.HTTP_201_CREATED,
        )


class ManageShopItemView(APIView):
    """
    PATCH  /api/shop/my/items/<id>/ → update own item
    DELETE /api/shop/my/items/<id>/ → deactivate own item
    """
    permission_classes = [IsAuthenticated, IsShopOwner]

    def patch(self, request, item_id):
        shop = _get_shop_or_404(request.user)
        if shop is None:
            return Response(
                {'error': 'You do not have a shop assigned.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        try:
            item = ShopItem.objects.select_related('shop').get(
                pk=item_id, shop=shop,
            )
        except ShopItem.DoesNotExist:
            return Response(
                {'error': 'Item not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = UpdateShopItemSerializer(
            item, data=request.data, partial=True,
        )
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()
        return Response(ShopItemSerializer(updated).data)

    def delete(self, request, item_id):
        shop = _get_shop_or_404(request.user)
        if shop is None:
            return Response(
                {'error': 'You do not have a shop assigned.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        try:
            item = ShopItem.objects.get(pk=item_id, shop=shop)
        except ShopItem.DoesNotExist:
            return Response(
                {'error': 'Item not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        item.is_active = False
        item.save()
        return Response({'detail': 'Item deactivated.'})


class ShopPurchasesView(APIView):
    """
    GET /api/shop/my/purchases/
    Shop owner views purchases at their shop.
    Supports ?status= filter.
    """
    permission_classes = [IsAuthenticated, IsShopOwner]

    def get(self, request):
        shop = _get_shop_or_404(request.user)
        if shop is None:
            return Response(
                {'error': 'You do not have a shop assigned.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        purchases = Purchase.objects.filter(
            item__shop=shop,
        ).select_related('student', 'item')

        purchase_status = request.query_params.get('status')
        if purchase_status:
            purchases = purchases.filter(status=purchase_status)

        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(purchases, request)
        return paginator.get_paginated_response(
            ShopPurchaseSerializer(page, many=True).data,
        )


class ConfirmPurchaseView(APIView):
    """
    PATCH /api/shop/purchases/<id>/confirm/
    Internal shop owner confirms or rejects a pending purchase.
    Request: { "status": "completed" | "rejected" }
    Rejection refunds points atomically.
    """
    permission_classes = [IsAuthenticated, IsShopOwner]

    def patch(self, request, purchase_id):
        serializer = ConfirmPurchaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_status = serializer.validated_data['status']

        try:
            purchase = (
                Purchase.objects
                .select_related('item', 'item__shop', 'student')
                .get(
                    pk=purchase_id,
                    item__shop__owner=request.user,
                )
            )
        except Purchase.DoesNotExist:
            return Response(
                {'error': 'Purchase not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if purchase.item.shop.shop_type != Shop.Type.INTERNAL:
            return Response(
                {'error': 'This operation is only for internal shops. Use verify-code for external.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            locked = Purchase.objects.select_for_update().get(pk=purchase.pk)
            if not locked.can_transition_to(new_status):
                raise InvalidStateTransitionError(
                    f"Cannot change status from '{locked.status}' to '{new_status}'."
                )
            locked.status = new_status
            locked.save()
            if new_status == Purchase.Status.REJECTED:
                User.objects.filter(pk=locked.student_id).update(
                    points=F('points') + locked.points_spent,
                )

        # Refresh only the mutated fields on the original `purchase` instance so
        # the select_related cache (item, item__shop, student) stays intact and
        # the response is serialized without extra queries.
        purchase.refresh_from_db(fields=['status', 'updated_at'])
        return Response(ShopPurchaseSerializer(purchase).data)


class VerifyPromoCodeView(APIView):
    """
    POST /api/shop/my/verify-code/
    External shop owner enters promo code to complete a purchase.
    Request: { "code": "ABC12345" }
    """
    permission_classes = [IsAuthenticated, IsShopOwner]

    def post(self, request):
        serializer = VerifyPromoCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        code = serializer.validated_data['code']

        shop = _get_shop_or_404(request.user)
        if shop is None:
            return Response(
                {'error': 'You do not have a shop assigned.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if shop.shop_type != Shop.Type.EXTERNAL:
            return Response(
                {'error': 'This operation is only for external shops. Use confirm for internal.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            with transaction.atomic():
                purchase = (
                    Purchase.objects
                    .select_for_update()
                    .get(
                        promo_code=code,
                        item__shop=shop,
                        status=Purchase.Status.READY,
                    )
                )
                purchase.status = Purchase.Status.COMPLETED
                purchase.save()
        except Purchase.DoesNotExist:
            raise InvalidVerificationCodeError(
                'Invalid or already used promo code.'
            )

        # Re-fetch with select_related for a clean, N+1-free response.
        purchase = Purchase.objects.select_related(
            'student', 'item',
        ).get(pk=purchase.pk)
        return Response(ShopPurchaseSerializer(purchase).data)


# ─── Admin endpoints ──────────────────────────────────────────


class AdminCreateShopView(APIView):
    """
    POST /api/shop/admin/shops/create/
    Admin creates a shop and assigns it to a shop_owner user.
    """
    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request):
        serializer = CreateShopSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        shop = serializer.save()
        return Response(
            ShopSerializer(shop).data,
            status=status.HTTP_201_CREATED,
        )


class AdminShopListView(APIView):
    """
    GET /api/shop/admin/shops/
    Admin lists all shops (including inactive).
    Supports ?is_active=, ?search=, ?type= filters.
    """
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        shops = Shop.objects.select_related('owner').all()

        is_active = request.query_params.get('is_active')
        if is_active is not None:
            shops = shops.filter(is_active=is_active.lower() == 'true')

        search = request.query_params.get('search')
        if search:
            shops = shops.filter(name__icontains=search)

        shop_type = request.query_params.get('type')
        if shop_type:
            shops = shops.filter(shop_type=shop_type)

        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(shops, request)
        return paginator.get_paginated_response(
            ShopSerializer(page, many=True).data,
        )


class AdminShopDetailView(APIView):
    """
    GET    /api/shop/admin/shops/<id>/ → view any shop
    PATCH  /api/shop/admin/shops/<id>/ → update any shop
    DELETE /api/shop/admin/shops/<id>/ → deactivate any shop
    """
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request, shop_id):
        try:
            shop = Shop.objects.select_related('owner').get(pk=shop_id)
        except Shop.DoesNotExist:
            return Response(
                {'error': 'Shop not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(ShopSerializer(shop).data)

    def patch(self, request, shop_id):
        try:
            shop = Shop.objects.select_related('owner').get(pk=shop_id)
        except Shop.DoesNotExist:
            return Response(
                {'error': 'Shop not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = AdminUpdateShopSerializer(
            shop, data=request.data, partial=True,
        )
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()
        return Response(ShopSerializer(updated).data)

    def delete(self, request, shop_id):
        try:
            shop = Shop.objects.get(pk=shop_id)
        except Shop.DoesNotExist:
            return Response(
                {'error': 'Shop not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        shop.is_active = False
        shop.save()
        return Response({'detail': 'Shop deactivated.'})
