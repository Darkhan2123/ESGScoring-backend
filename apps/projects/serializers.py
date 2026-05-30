from rest_framework import serializers

from apps.core.serializers import resolve_image

from .models import Project


class _OrganizationStub(serializers.Serializer):
    """Inline org info embedded inside ``ProjectSerializer`` payloads.

    ``logo`` is resolved to an absolute URL when ``request`` is in
    serializer context (which the views pass), and to a relative URL
    otherwise; ``None`` when the org has no uploaded image.
    """

    id = serializers.IntegerField()
    name = serializers.CharField()
    logo = serializers.SerializerMethodField()

    def get_logo(self, obj):
        if not getattr(obj, 'logo', None):
            return None
        request = self.context.get('request')
        url = obj.logo.url
        return request.build_absolute_uri(url) if request else url


class ProjectSerializer(serializers.ModelSerializer):
    """Full project output with nested organization (id + name + logo).

    Public/student projection — never exposes ``verification_code``.
    """

    organization = _OrganizationStub(read_only=True)
    image = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = [
            'id', 'title', 'description', 'google_form_url', 'image',
            'points_reward', 'organization', 'is_active',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_image(self, obj):
        return resolve_image(obj, self.context.get('request'))


class ProjectOwnerSerializer(ProjectSerializer):
    """Owner/admin projection — adds the verification code students must submit."""

    class Meta(ProjectSerializer.Meta):
        fields = ProjectSerializer.Meta.fields + ['verification_code']


class ProjectListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing projects -- now includes org logo."""

    organization = _OrganizationStub(read_only=True)
    image = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = [
            'id', 'title', 'description', 'google_form_url', 'image',
            'points_reward', 'organization', 'created_at',
        ]

    def get_image(self, obj):
        return resolve_image(obj, self.context.get('request'))


class CreateProjectSerializer(serializers.Serializer):
    """Organization owner creates a project under their own organization."""

    title = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True, default='')
    google_form_url = serializers.URLField(max_length=500)
    image = serializers.ImageField(required=False, allow_null=True, default=None)
    points_reward = serializers.IntegerField(min_value=1)

    def create(self, validated_data):
        return Project.objects.create(
            organization=self.context['organization'],
            title=validated_data['title'],
            description=validated_data.get('description', ''),
            google_form_url=validated_data['google_form_url'],
            image=validated_data.get('image'),
            points_reward=validated_data['points_reward'],
        )


class UpdateProjectSerializer(serializers.ModelSerializer):
    """Organization owner updates their project."""

    class Meta:
        model = Project
        fields = [
            'title', 'description', 'google_form_url', 'image',
            'points_reward', 'is_active',
        ]


class AdminUpdateProjectSerializer(serializers.ModelSerializer):
    """Admin PATCH /admin/projects/<id>/ — same fields as the owner update."""

    class Meta:
        model = Project
        fields = [
            'title', 'description', 'google_form_url', 'image',
            'points_reward', 'is_active',
        ]


class VerifyCodeSerializer(serializers.Serializer):
    """Student submits a verification code to claim a project's points."""

    code = serializers.CharField(max_length=8)
