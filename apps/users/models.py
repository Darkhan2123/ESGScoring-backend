from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = 'admin', 'Admin'
        ORGANIZATION = 'organization', 'Organization'
        STUDENT = 'student', 'Student'
        SHOP_OWNER = 'shop_owner', 'Shop Owner'

    class School(models.TextChoices):
        ENERGY_PETROLEUM = 'energy_petroleum', 'School of Energy and Petroleum Industry'
        GEOLOGY = 'geology', 'School of Geology'
        IT_ENGINEERING = 'it_engineering', 'School of Information Technology and Engineering'
        BUSINESS = 'business', 'Business School'
        INTL_ECONOMICS = 'intl_economics', 'International School of Economics'
        MARITIME = 'maritime', 'Kazakhstan Maritime Academy'
        APPLIED_MATH = 'applied_math', 'School of Applied Mathematics'
        CHEM_ENGINEERING = 'chem_engineering', 'School of Chemical Engineering'
        SOCIAL_SCIENCES = 'social_sciences', 'School of Social Sciences'
        MATERIALS_GREEN = 'materials_green', 'School of Materials Science and Green Technologies'

    email = models.EmailField(unique=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT)
    student_id = models.CharField(max_length=50, blank=True)
    school = models.CharField(max_length=32, choices=School.choices, null=True, blank=True)
    full_name = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    avatar = models.ImageField(upload_to='avatars/', null=True, blank=True)
    points = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    class Meta:
        db_table = 'users'

    def __str__(self):
        return f"{self.full_name or self.username} ({self.role})"