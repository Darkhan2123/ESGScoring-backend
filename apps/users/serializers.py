from rest_framework import serializers
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from .models import User


class UserSerializer(serializers.ModelSerializer):
    """Full user output — returned after login/register and on GET /me/."""

    class Meta:
        model = User
        fields = [
            'id', 'email', 'full_name', 'student_id',
            'role', 'phone', 'avatar', 'points', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class RegisterSerializer(serializers.Serializer):
    """Public registration — always creates a student."""

    email = serializers.EmailField()
    full_name = serializers.CharField()
    password = serializers.CharField(write_only=True, min_length=6)
    student_id = serializers.CharField()

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate_student_id(self, value):
        if User.objects.filter(student_id=value).exists():
            raise serializers.ValidationError("A user with this student ID already exists.")
        return value

    def create(self, validated_data):
        return User.objects.create_user(
            username=validated_data['email'],
            email=validated_data['email'],
            password=validated_data['password'],
            full_name=validated_data['full_name'],
            student_id=validated_data['student_id'],
            role=User.Role.STUDENT,
        )


class LoginSerializer(serializers.Serializer):
    """Email + password login."""

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        user = authenticate(username=data['email'], password=data['password'])
        if user is None:
            raise serializers.ValidationError("Invalid email or password.")
        if not user.is_active:
            raise serializers.ValidationError("User account is disabled.")
        data['user'] = user
        return data


class UpdateProfileSerializer(serializers.ModelSerializer):
    """PATCH /me/ — students can update their own profile."""

    class Meta:
        model = User
        fields = ['full_name', 'phone', 'avatar', 'student_id']


class ChangePasswordSerializer(serializers.Serializer):
    """Authenticated user changes their own password."""

    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=6)

    def validate_old_password(self, value):
        if not self.context['request'].user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate_new_password(self, value):
        validate_password(value, self.context['request'].user)
        return value


class AdminCreateUserSerializer(serializers.Serializer):
    """Super-admin creates a user with any role."""

    email = serializers.EmailField()
    full_name = serializers.CharField()
    password = serializers.CharField(write_only=True, min_length=6)
    role = serializers.ChoiceField(choices=User.Role.choices)
    student_id = serializers.CharField(required=False, default='')
    phone = serializers.CharField(required=False, default='')

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate_student_id(self, value):
        if value and User.objects.filter(student_id=value).exists():
            raise serializers.ValidationError("A user with this student ID already exists.")
        return value

    def create(self, validated_data):
        return User.objects.create_user(
            username=validated_data['email'],
            email=validated_data['email'],
            password=validated_data['password'],
            full_name=validated_data['full_name'],
            role=validated_data['role'],
            student_id=validated_data.get('student_id', ''),
            phone=validated_data.get('phone', ''),
        )
