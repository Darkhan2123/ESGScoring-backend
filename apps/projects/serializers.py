from rest_framework import serializers

from .models import Project


class _OrganizationStub(serializers.Serializer):
    """Inline org info embedded inside ``ProjectSerializer``."""

    id = serializers.IntegerField()
    name = serializers.CharField()


class ProjectSerializer(serializers.ModelSerializer):
    """Full project output with nested organization (id + name)."""

    organization = _OrganizationStub(read_only=True)

    class Meta:
        model = Project
        fields = [
            'id', 'title', 'description', 'google_form_url',
            'organization', 'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class ProjectListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing projects."""

    organization_name = serializers.CharField(
        source='organization.name', read_only=True,
    )

    class Meta:
        model = Project
        fields = [
            'id', 'title', 'description', 'google_form_url',
            'organization_name', 'created_at',
        ]


class CreateProjectSerializer(serializers.Serializer):
    """Organization owner creates a project under their own organization."""

    title = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True, default='')
    google_form_url = serializers.URLField(max_length=500)

    def create(self, validated_data):
        return Project.objects.create(
            organization=self.context['organization'],
            title=validated_data['title'],
            description=validated_data.get('description', ''),
            google_form_url=validated_data['google_form_url'],
        )


class UpdateProjectSerializer(serializers.ModelSerializer):
    """Organization owner updates their project."""

    class Meta:
        model = Project
        fields = ['title', 'description', 'google_form_url', 'is_active']


class AdminUpdateProjectSerializer(serializers.ModelSerializer):
    """Admin PATCH /admin/projects/<id>/ — same fields as the owner update."""

    class Meta:
        model = Project
        fields = ['title', 'description', 'google_form_url', 'is_active']
