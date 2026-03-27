import secrets
import string

from django.conf import settings
from django.db import models


class Task(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='tasks',
    )
    points_reward = models.PositiveIntegerField()
    verification_code = models.CharField(max_length=8, unique=True)
    max_participants = models.PositiveIntegerField(null=True, blank=True)
    deadline = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tasks'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.organization.name})"

    def save(self, *args, **kwargs):
        if not self.verification_code:
            self.verification_code = self._generate_unique_code()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_unique_code():
        alphabet = string.ascii_uppercase + string.digits
        while True:
            code = ''.join(secrets.choice(alphabet) for _ in range(8))
            if not Task.objects.filter(verification_code=code).exists():
                return code

    @property
    def approved_count(self):
        return self.participations.filter(
            status__in=[
                TaskParticipation.Status.APPROVED,
                TaskParticipation.Status.COMPLETED,
            ],
        ).count()

    @property
    def is_full(self):
        if self.max_participants is None:
            return False
        return self.approved_count >= self.max_participants


class TaskParticipation(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'
        COMPLETED = 'completed', 'Completed'

    VALID_TRANSITIONS = {
        'pending': ['approved', 'rejected'],
        'approved': ['completed'],
    }

    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name='participations',
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='task_participations',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'task_participations'
        constraints = [
            models.UniqueConstraint(
                fields=['task', 'student'],
                name='unique_task_student',
            ),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.student} → {self.task.title} ({self.status})"

    def can_transition_to(self, new_status):
        allowed = self.VALID_TRANSITIONS.get(self.status, [])
        return new_status in allowed
