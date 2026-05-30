import secrets
import string

from django.conf import settings
from django.db import models


class Project(models.Model):
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='projects',
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    google_form_url = models.URLField(max_length=500)
    image = models.ImageField(upload_to='projects/', null=True, blank=True)
    points_reward = models.PositiveIntegerField(default=0)
    verification_code = models.CharField(
        max_length=8, unique=True, null=True, blank=True,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'projects'
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.verification_code:
            self.verification_code = self._generate_unique_code()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_unique_code():
        alphabet = string.ascii_uppercase + string.digits
        while True:
            code = ''.join(secrets.choice(alphabet) for _ in range(8))
            if not Project.objects.filter(verification_code=code).exists():
                return code


class ProjectCompletion(models.Model):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='completions',
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='project_completions',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'project_completions'
        constraints = [
            models.UniqueConstraint(
                fields=['project', 'student'],
                name='unique_project_student',
            ),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.student} → {self.project.title}"
