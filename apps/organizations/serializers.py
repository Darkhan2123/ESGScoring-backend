from rest_framework import serializers

from apps.users.models import User
from apps.users.serializers import UserSerializer
from .models import Organization


class OrganizationSerializer(serializers.ModelSerializer):
    """Full organization output with nested owner details."""

    owner = UserSerializer(read_only=True)

    class Meta:
        model = Organization
        fields = [
            'id', 'name', 'description', 'logo',
            'owner', 'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class OrganizationListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing organizations."""

    owner_name = serializers.CharField(source='owner.full_name', read_only=True)

    class Meta:
        model = Organization
        fields = ['id', 'name', 'description', 'logo', 'owner_name', 'created_at']


class CreateOrganizationSerializer(serializers.Serializer):
    """Admin creates a new organization and assigns an owner."""

    name = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, default='')
    owner_id = serializers.IntegerField()

    def validate_name(self, value):
        if Organization.objects.filter(name=value).exists():
            raise serializers.ValidationError(
                "An organization with this name already exists."
            )
        return value

    def validate_owner_id(self, value):
        try:
            user = User.objects.get(pk=value)
        except User.DoesNotExist:
            raise serializers.ValidationError("User not found.")
        if user.role != User.Role.ORGANIZATION:
            raise serializers.ValidationError(
                "Owner must have the 'organization' role."
            )
        if hasattr(user, 'organization'):
            raise serializers.ValidationError(
                "This user already owns an organization."
            )
        self._validated_owner = user
        return value

    def create(self, validated_data):
        return Organization.objects.create(
            name=validated_data['name'],
            description=validated_data.get('description', ''),
            owner=self._validated_owner,
        )


class UpdateOrganizationSerializer(serializers.ModelSerializer):
    """Organization owner updates their org profile."""

    class Meta:
        model = Organization
        fields = ['name', 'description', 'logo']

    def validate_name(self, value):
        if Organization.objects.filter(name=value).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError(
                "An organization with this name already exists."
            )
        return value


class AdminUpdateOrganizationSerializer(serializers.ModelSerializer):
    """Admin PATCH /admin/<id>/ — validates all admin-editable fields."""

    owner_id = serializers.IntegerField(required=False)

    class Meta:
        model = Organization
        fields = ['name', 'description', 'is_active', 'owner_id']

    def validate_name(self, value):
        if Organization.objects.filter(name=value).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError(
                "An organization with this name already exists."
            )
        return value

    def validate_owner_id(self, value):
        try:
            user = User.objects.get(pk=value)
        except User.DoesNotExist:
            raise serializers.ValidationError("User not found.")
        if user.role != User.Role.ORGANIZATION:
            raise serializers.ValidationError(
                "Owner must have the 'organization' role."
            )
        if (
            hasattr(user, 'organization')
            and user.organization.pk != self.instance.pk
        ):
            raise serializers.ValidationError(
                "This user already owns another organization."
            )
        return value

    def update(self, instance, validated_data):
        owner_id = validated_data.pop('owner_id', None)
        if owner_id is not None:
            instance.owner_id = owner_id
        return super().update(instance, validated_data)
