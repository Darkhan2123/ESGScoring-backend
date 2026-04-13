from rest_framework import serializers

from apps.users.models import User
from .models import Shop, ShopItem, Purchase


# ─── Shop serializers ────────────────────────────────────────────


class ShopListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing shops."""

    owner_name = serializers.CharField(
        source='owner.full_name', read_only=True,
    )
    items_count = serializers.SerializerMethodField()

    class Meta:
        model = Shop
        fields = [
            'id', 'name', 'description', 'address', 'logo', 'shop_type',
            'owner_name', 'items_count', 'created_at',
        ]

    def get_items_count(self, obj):
        if hasattr(obj, '_items_count'):
            return obj._items_count
        return obj.items.filter(is_active=True).count()


class ShopSerializer(serializers.ModelSerializer):
    """Full shop output with owner info."""

    owner_name = serializers.CharField(
        source='owner.full_name', read_only=True,
    )
    owner_id = serializers.IntegerField(
        source='owner.id', read_only=True,
    )

    class Meta:
        model = Shop
        fields = [
            'id', 'name', 'description', 'address', 'logo', 'shop_type',
            'owner_id', 'owner_name', 'is_active',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class CreateShopSerializer(serializers.Serializer):
    """Admin creates a new shop and assigns a shop_owner."""

    name = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, default='')
    address = serializers.CharField(max_length=255, required=False, default='')
    shop_type = serializers.ChoiceField(choices=Shop.Type.choices)
    owner_id = serializers.IntegerField()

    def validate_name(self, value):
        if Shop.objects.filter(name=value).exists():
            raise serializers.ValidationError(
                "A shop with this name already exists."
            )
        return value

    def validate_owner_id(self, value):
        try:
            user = User.objects.get(pk=value)
        except User.DoesNotExist:
            raise serializers.ValidationError("User not found.")
        if user.role != User.Role.SHOP_OWNER:
            raise serializers.ValidationError(
                "Owner must have the 'shop_owner' role."
            )
        if hasattr(user, 'shop'):
            raise serializers.ValidationError(
                "This user already owns a shop."
            )
        self._validated_owner = user
        return value

    def create(self, validated_data):
        return Shop.objects.create(
            name=validated_data['name'],
            description=validated_data.get('description', ''),
            address=validated_data.get('address', ''),
            shop_type=validated_data['shop_type'],
            owner=self._validated_owner,
        )


class UpdateShopSerializer(serializers.ModelSerializer):
    """Shop owner updates their own shop profile."""

    class Meta:
        model = Shop
        fields = ['name', 'description', 'address', 'logo']

    def validate_name(self, value):
        if Shop.objects.filter(name=value).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError(
                "A shop with this name already exists."
            )
        return value


class AdminUpdateShopSerializer(serializers.ModelSerializer):
    """Admin updates any shop."""

    owner_id = serializers.IntegerField(required=False)

    class Meta:
        model = Shop
        fields = ['name', 'description', 'address', 'is_active', 'owner_id']

    def validate_name(self, value):
        if Shop.objects.filter(name=value).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError(
                "A shop with this name already exists."
            )
        return value

    def validate_owner_id(self, value):
        try:
            user = User.objects.get(pk=value)
        except User.DoesNotExist:
            raise serializers.ValidationError("User not found.")
        if user.role != User.Role.SHOP_OWNER:
            raise serializers.ValidationError(
                "Owner must have the 'shop_owner' role."
            )
        if (
            hasattr(user, 'shop')
            and user.shop.pk != self.instance.pk
        ):
            raise serializers.ValidationError(
                "This user already owns another shop."
            )
        return value

    def update(self, instance, validated_data):
        owner_id = validated_data.pop('owner_id', None)
        if owner_id is not None:
            instance.owner_id = owner_id
        return super().update(instance, validated_data)


# ─── ShopItem serializers ────────────────────────────────────────


class ShopItemListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing items."""

    shop_name = serializers.CharField(
        source='shop.name', read_only=True,
    )

    class Meta:
        model = ShopItem
        fields = [
            'id', 'title', 'description', 'price', 'photo',
            'shop_name', 'created_at',
        ]


class ShopItemSerializer(serializers.ModelSerializer):
    """Full item output."""

    shop_name = serializers.CharField(
        source='shop.name', read_only=True,
    )
    shop_id = serializers.IntegerField(
        source='shop.id', read_only=True,
    )

    class Meta:
        model = ShopItem
        fields = [
            'id', 'title', 'description', 'price', 'photo',
            'shop_id', 'shop_name', 'is_active',
            'created_at', 'updated_at',
        ]


class CreateShopItemSerializer(serializers.Serializer):
    """Shop owner creates a new item."""

    title = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, default='')
    price = serializers.IntegerField(min_value=1)
    photo = serializers.ImageField(required=False, default=None)

    def create(self, validated_data):
        shop = self.context['shop']
        return ShopItem.objects.create(
            shop=shop,
            title=validated_data['title'],
            description=validated_data.get('description', ''),
            price=validated_data['price'],
            photo=validated_data.get('photo'),
        )


class UpdateShopItemSerializer(serializers.ModelSerializer):
    """Shop owner updates their item."""

    class Meta:
        model = ShopItem
        fields = ['title', 'description', 'price', 'photo', 'is_active']


# ─── Purchase serializers ────────────────────────────────────────


class MyPurchaseSerializer(serializers.ModelSerializer):
    """Student views their own purchases — shows item/shop info."""

    item_id = serializers.IntegerField(source='item.id', read_only=True)
    item_title = serializers.CharField(source='item.title', read_only=True)
    item_photo = serializers.ImageField(source='item.photo', read_only=True)
    shop_name = serializers.CharField(
        source='item.shop.name', read_only=True,
    )
    shop_type = serializers.CharField(
        source='item.shop.shop_type', read_only=True,
    )

    class Meta:
        model = Purchase
        fields = [
            'id', 'item_id', 'item_title', 'item_photo',
            'shop_name', 'shop_type', 'points_spent',
            'promo_code', 'status', 'created_at', 'updated_at',
        ]


class ShopPurchaseSerializer(serializers.ModelSerializer):
    """Shop owner views purchases — shows student info."""

    student_name = serializers.CharField(
        source='student.full_name', read_only=True,
    )
    student_email = serializers.CharField(
        source='student.email', read_only=True,
    )
    item_title = serializers.CharField(
        source='item.title', read_only=True,
    )
    item_id = serializers.IntegerField(
        source='item.id', read_only=True,
    )

    class Meta:
        model = Purchase
        fields = [
            'id', 'student_name', 'student_email',
            'item_id', 'item_title', 'points_spent',
            'status', 'created_at', 'updated_at',
        ]


class ConfirmPurchaseSerializer(serializers.Serializer):
    """Vendor confirms or rejects a pending purchase."""

    status = serializers.ChoiceField(
        choices=[
            Purchase.Status.COMPLETED,
            Purchase.Status.REJECTED,
        ],
    )


class VerifyPromoCodeSerializer(serializers.Serializer):
    """Vendor submits promo code to complete purchase."""

    code = serializers.CharField(max_length=8)
