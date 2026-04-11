from django.contrib import admin

from .models import Shop, ShopItem, Purchase


@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    list_display = ['name', 'shop_type', 'owner', 'is_active', 'created_at']
    list_filter = ['is_active', 'shop_type']
    search_fields = ['name', 'owner__full_name', 'owner__email']
    raw_id_fields = ['owner']


@admin.register(ShopItem)
class ShopItemAdmin(admin.ModelAdmin):
    list_display = ['title', 'shop', 'price', 'is_active', 'created_at']
    list_filter = ['is_active', 'shop']
    search_fields = ['title', 'shop__name']
    raw_id_fields = ['shop']


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ['student', 'item', 'points_spent', 'promo_code', 'status', 'created_at']
    list_filter = ['status', 'item__shop']
    search_fields = ['student__full_name', 'student__email', 'item__title', 'promo_code']
    raw_id_fields = ['student', 'item']
    readonly_fields = ['promo_code']
