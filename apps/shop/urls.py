from django.urls import path

from .views import (
    ShopListView,
    ShopDetailView,
    ShopItemListView,
    BuyItemView,
    MyPurchasesView,
    MyShopView,
    CreateShopItemView,
    ManageShopItemView,
    ShopPurchasesView,
    ConfirmPurchaseView,
    VerifyPromoCodeView,
    AdminCreateShopView,
    AdminShopListView,
    AdminShopDetailView,
)

urlpatterns = [
    # Public (any authenticated user)
    path('shops/', ShopListView.as_view(), name='shop_list'),
    path('shops/<int:shop_id>/', ShopDetailView.as_view(), name='shop_detail'),
    path('shops/<int:shop_id>/items/', ShopItemListView.as_view(), name='shop_item_list'),

    # Student only
    path('items/<int:item_id>/buy/', BuyItemView.as_view(), name='buy_item'),
    path('my-purchases/', MyPurchasesView.as_view(), name='my_purchases'),

    # Shop owner only
    path('my/', MyShopView.as_view(), name='my_shop'),
    path('my/items/', CreateShopItemView.as_view(), name='create_shop_item'),
    path('my/items/<int:item_id>/', ManageShopItemView.as_view(), name='manage_shop_item'),
    path('my/purchases/', ShopPurchasesView.as_view(), name='shop_purchases'),
    path('purchases/<int:purchase_id>/confirm/', ConfirmPurchaseView.as_view(), name='confirm_purchase'),
    path('my/verify-code/', VerifyPromoCodeView.as_view(), name='verify_promo_code'),

    # Admin only
    path('admin/shops/create/', AdminCreateShopView.as_view(), name='admin_create_shop'),
    path('admin/shops/', AdminShopListView.as_view(), name='admin_shop_list'),
    path('admin/shops/<int:shop_id>/', AdminShopDetailView.as_view(), name='admin_shop_detail'),
]
