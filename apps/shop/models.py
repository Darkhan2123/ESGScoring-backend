import secrets
import string

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Shop(models.Model):
    class Type(models.TextChoices):
        INTERNAL = 'internal', 'Internal'
        EXTERNAL = 'external', 'External'

    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    address = models.CharField(max_length=255, blank=True, default='')
    logo = models.ImageField(upload_to='shops/', null=True, blank=True)
    shop_type = models.CharField(max_length=10, choices=Type.choices)
    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='shop',
        limit_choices_to={'role': 'shop_owner'},
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'shops'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.get_shop_type_display()})"

    def clean(self):
        super().clean()
        if self.owner_id and self.owner.role != 'shop_owner':
            raise ValidationError({
                'owner': "Owner must have the 'shop_owner' role.",
            })


class ShopItem(models.Model):
    shop = models.ForeignKey(
        Shop,
        on_delete=models.CASCADE,
        related_name='items',
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    price = models.PositiveIntegerField()
    photo = models.ImageField(upload_to='shop_items/', null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'shop_items'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} — {self.shop.name} ({self.price} pts)"


class Purchase(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        READY = 'ready', 'Ready'
        COMPLETED = 'completed', 'Completed'
        REJECTED = 'rejected', 'Rejected'

    VALID_TRANSITIONS = {
        'pending': ['completed', 'rejected'],
        'ready': ['completed'],
    }

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='purchases',
    )
    item = models.ForeignKey(
        ShopItem,
        on_delete=models.CASCADE,
        related_name='purchases',
    )
    points_spent = models.PositiveIntegerField()
    promo_code = models.CharField(
        max_length=8, unique=True, null=True, blank=True,
    )
    status = models.CharField(max_length=20, choices=Status.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'purchases'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.student} — {self.item.title} ({self.status})"

    def can_transition_to(self, new_status):
        allowed = self.VALID_TRANSITIONS.get(self.status, [])
        return new_status in allowed

    def save(self, *args, **kwargs):
        if not self.promo_code and self.item.shop.shop_type == Shop.Type.EXTERNAL:
            self.promo_code = self._generate_unique_code()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_unique_code():
        alphabet = string.ascii_uppercase + string.digits
        while True:
            code = ''.join(secrets.choice(alphabet) for _ in range(8))
            if not Purchase.objects.filter(promo_code=code).exists():
                return code
