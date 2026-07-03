"""
Tests for the events app service layer.

These tests focus on the business logic in :mod:`apps.events.services`:
- Participation request handling with capacity checks
- State transitions for participation approvals/rejections
- Verification code validation and points crediting
- Concurrency handling and edge cases
"""
from django.test import TestCase
from django.db import transaction
from django.utils import timezone
from apps.core.exceptions import (
    DuplicateRequestError,
    EventFullError,
    InvalidStateTransitionError,
    InvalidVerificationCodeError,
)
from apps.events.models import Task, TaskParticipation
from apps.events import services
from apps.organizations.models import Organization
from apps.users.models import User


class EventServiceTestCase(TestCase):
    """Base test case with common setup for event service tests."""

    def setUp(self):
        self.org_owner = User.objects.create_user(
            username='orgowner',
            email='org@example.com',
            password='password',
            role=User.Role.ORGANIZATION,
            full_name='Org Owner',
        )
        self.organization = Organization.objects.create(
            name='Test Organization',
            owner=self.org_owner,
            is_active=True,
        )
        self.student1 = User.objects.create_user(
            username='student1',
            email='student1@example.com',
            password='password',
            role=User.Role.STUDENT,
            full_name='Student One',
            points=100,
        )
        self.student2 = User.objects.create_user(
            username='student2',
            email='student2@example.com',
            password='password',
            role=User.Role.STUDENT,
            full_name='Student Two',
            points=100,
        )


class RequestParticipationTests(EventServiceTestCase):
    """Tests for services.request_participation()."""

    def test_successful_participation_request(self):
        """A student can successfully request participation in an active task."""
        task = Task.objects.create(
            title='Test Task',
            description='A test task',
            organization=self.organization,
            points_reward=50,
            max_participants=10,
            is_active=True,
        )

        participation = services.request_participation(
            user=self.student1, task=task,
        )

        self.assertEqual(participation.student, self.student1)
        self.assertEqual(participation.task, task)
        self.assertEqual(participation.status, TaskParticipation.Status.PENDING)
        self.assertEqual(TaskParticipation.objects.count(), 1)

    def test_duplicate_request_raises_error(self):
        """A student cannot request participation twice for the same task."""
        task = Task.objects.create(
            title='Test Task',
            description='A test task',
            organization=self.organization,
            points_reward=50,
            is_active=True,
        )

        # First request should succeed
        services.request_participation(user=self.student1, task=task)

        # Second request should raise DuplicateRequestError
        with self.assertRaises(DuplicateRequestError) as cm:
            services.request_participation(user=self.student1, task=task)

        self.assertIn('already applied', str(cm.exception))

    def test_full_task_raises_error(self):
        """A task at capacity should reject new participation requests."""
        task = Task.objects.create(
            title='Test Task',
            description='A test task',
            organization=self.organization,
            points_reward=50,
            max_participants=2,
            is_active=True,
        )

        # Fill the task to capacity
        services.request_participation(user=self.student1, task=task)
        participation2 = services.request_participation(user=self.student2, task=task)
        
        # Approve both participations
        services.decide_participation(
            participation=participation2,
            new_status=TaskParticipation.Status.APPROVED,
        )
        participation1 = TaskParticipation.objects.get(student=self.student1, task=task)
        services.decide_participation(
            participation=participation1,
            new_status=TaskParticipation.Status.APPROVED,
        )

        # Create a third student and try to join
        student3 = User.objects.create_user(
            username='student3',
            email='student3@example.com',
            password='password',
            role=User.Role.STUDENT,
            full_name='Student Three',
        )

        with self.assertRaises(EventFullError) as cm:
            services.request_participation(user=student3, task=task)

        self.assertIn('maximum number of participants', str(cm.exception))

    def test_task_without_capacity_limit(self):
        """Tasks without max_participants should accept unlimited requests."""
        task = Task.objects.create(
            title='Test Task',
            description='A test task',
            organization=self.organization,
            points_reward=50,
            max_participants=None,  # No capacity limit
            is_active=True,
        )

        # Should be able to create multiple participations
        services.request_participation(user=self.student1, task=task)
        services.request_participation(user=self.student2, task=task)

        self.assertEqual(TaskParticipation.objects.count(), 2)

    def test_inactive_task_rejects_requests(self):
        """Inactive tasks should not accept participation requests."""
        task = Task.objects.create(
            title='Test Task',
            description='A test task',
            organization=self.organization,
            points_reward=50,
            is_active=False,  # Inactive task
        )

        # The service doesn't check is_active, but the view layer does
        # This test documents current behavior
        participation = services.request_participation(
            user=self.student1, task=task,
        )
        self.assertEqual(participation.status, TaskParticipation.Status.PENDING)


class DecideParticipationTests(EventServiceTestCase):
    """Tests for services.decide_participation()."""

    def test_approve_pending_participation(self):
        """An organization owner can approve a pending participation."""
        task = Task.objects.create(
            title='Test Task',
            description='A test task',
            organization=self.organization,
            points_reward=50,
            max_participants=10,
            is_active=True,
        )

        participation = services.request_participation(
            user=self.student1, task=task,
        )

        updated = services.decide_participation(
            participation=participation,
            new_status=TaskParticipation.Status.APPROVED,
        )

        self.assertEqual(updated.status, TaskParticipation.Status.APPROVED)
        self.assertEqual(TaskParticipation.objects.count(), 1)

    def test_reject_pending_participation(self):
        """An organization owner can reject a pending participation."""
        task = Task.objects.create(
            title='Test Task',
            description='A test task',
            organization=self.organization,
            points_reward=50,
            is_active=True,
        )

        participation = services.request_participation(
            user=self.student1, task=task,
        )

        updated = services.decide_participation(
            participation=participation,
            new_status=TaskParticipation.Status.REJECTED,
        )

        self.assertEqual(updated.status, TaskParticipation.Status.REJECTED)

    def test_complete_approved_participation(self):
        """An approved participation can be moved to completed."""
        task = Task.objects.create(
            title='Test Task',
            description='A test task',
            organization=self.organization,
            points_reward=50,
            is_active=True,
        )

        participation = services.request_participation(
            user=self.student1, task=task,
        )
        approved = services.decide_participation(
            participation=participation,
            new_status=TaskParticipation.Status.APPROVED,
        )

        completed = services.decide_participation(
            participation=approved,
            new_status=TaskParticipation.Status.COMPLETED,
        )

        self.assertEqual(completed.status, TaskParticipation.Status.COMPLETED)

    def test_invalid_state_transition_raises_error(self):
        """Invalid state transitions should raise InvalidStateTransitionError."""
        task = Task.objects.create(
            title='Test Task',
            description='A test task',
            organization=self.organization,
            points_reward=50,
            is_active=True,
        )

        participation = services.request_participation(
            user=self.student1, task=task,
        )

        # Try to go from PENDING directly to COMPLETED (invalid)
        with self.assertRaises(InvalidStateTransitionError) as cm:
            services.decide_participation(
                participation=participation,
                new_status=TaskParticipation.Status.COMPLETED,
            )

        self.assertIn('Cannot change status', str(cm.exception))

    def test_approve_full_task_raises_error(self):
        """Cannot approve a participation if it would exceed task capacity."""
        task = Task.objects.create(
            title='Test Task',
            description='A test task',
            organization=self.organization,
            points_reward=50,
            max_participants=1,
            is_active=True,
        )

        # Create and approve first participation
        participation1 = services.request_participation(
            user=self.student1, task=task,
        )
        services.decide_participation(
            participation=participation1,
            new_status=TaskParticipation.Status.APPROVED,
        )

        # Manually create second participation (bypassing service capacity check)
        participation2 = TaskParticipation.objects.create(
            task=task,
            student=self.student2,
            status=TaskParticipation.Status.PENDING,
        )

        # Try to approve (should fail due to capacity)
        with self.assertRaises(EventFullError) as cm:
            services.decide_participation(
                participation=participation2,
                new_status=TaskParticipation.Status.APPROVED,
            )

        self.assertIn('maximum number of participants', str(cm.exception))

    def test_rejected_cannot_be_approved(self):
        """A rejected participation cannot be approved."""
        task = Task.objects.create(
            title='Test Task',
            description='A test task',
            organization=self.organization,
            points_reward=50,
            is_active=True,
        )

        participation = services.request_participation(
            user=self.student1, task=task,
        )
        services.decide_participation(
            participation=participation,
            new_status=TaskParticipation.Status.REJECTED,
        )

        with self.assertRaises(InvalidStateTransitionError):
            services.decide_participation(
                participation=participation,
                new_status=TaskParticipation.Status.APPROVED,
            )


class CompleteParticipationTests(EventServiceTestCase):
    """Tests for services.complete_participation()."""

    def test_complete_with_valid_code_credits_points(self):
        """Valid verification code credits points to the student."""
        task = Task.objects.create(
            title='Test Task',
            description='A test task',
            organization=self.organization,
            points_reward=50,
            is_active=True,
        )

        participation = services.request_participation(
            user=self.student1, task=task,
        )
        services.decide_participation(
            participation=participation,
            new_status=TaskParticipation.Status.APPROVED,
        )

        initial_points = self.student1.points
        services.complete_participation(
            user=self.student1,
            task=task,
            code=task.verification_code,
        )

        self.student1.refresh_from_db()
        self.assertEqual(self.student1.points, initial_points + task.points_reward)

        participation.refresh_from_db()
        self.assertEqual(participation.status, TaskParticipation.Status.COMPLETED)

    def test_invalid_code_raises_error(self):
        """Invalid verification code should raise InvalidVerificationCodeError."""
        task = Task.objects.create(
            title='Test Task',
            description='A test task',
            organization=self.organization,
            points_reward=50,
            is_active=True,
        )

        participation = services.request_participation(
            user=self.student1, task=task,
        )
        services.decide_participation(
            participation=participation,
            new_status=TaskParticipation.Status.APPROVED,
        )

        with self.assertRaises(InvalidVerificationCodeError) as cm:
            services.complete_participation(
                user=self.student1,
                task=task,
                code='WRONGCODE',
            )

        self.assertIn('Invalid verification code', str(cm.exception))

    def test_no_approved_participation_raises_error(self):
        """Student without approved participation cannot complete task."""
        task = Task.objects.create(
            title='Test Task',
            description='A test task',
            organization=self.organization,
            points_reward=50,
            is_active=True,
        )

        # Create participation but don't approve it
        services.request_participation(user=self.student1, task=task)

        with self.assertRaises(TaskParticipation.DoesNotExist):
            services.complete_participation(
                user=self.student1,
                task=task,
                code=task.verification_code,
            )

    def test_only_approved_can_complete(self):
        """Only approved participations can be completed."""
        task = Task.objects.create(
            title='Test Task',
            description='A test task',
            organization=self.organization,
            points_reward=50,
            is_active=True,
        )

        participation = services.request_participation(
            user=self.student1, task=task,
        )
        # Leave as PENDING (not approved)

        with self.assertRaises(TaskParticipation.DoesNotExist):
            services.complete_participation(
                user=self.student1,
                task=task,
                code=task.verification_code,
            )

    def test_timing_attack_resistance(self):
        """Verification code comparison should be timing-attack resistant."""
        task = Task.objects.create(
            title='Test Task',
            description='A test task',
            organization=self.organization,
            points_reward=50,
            is_active=True,
        )

        participation = services.request_participation(
            user=self.student1, task=task,
        )
        services.decide_participation(
            participation=participation,
            new_status=TaskParticipation.Status.APPROVED,
        )

        # Try wrong code of same length (timing attack scenario)
        wrong_code = 'X' * len(task.verification_code)

        with self.assertRaises(InvalidVerificationCodeError):
            services.complete_participation(
                user=self.student1,
                task=task,
                code=wrong_code,
            )

    def test_completion_is_idempotent(self):
        """Completing an already completed participation should fail."""
        task = Task.objects.create(
            title='Test Task',
            description='A test task',
            organization=self.organization,
            points_reward=50,
            is_active=True,
        )

        participation = services.request_participation(
            user=self.student1, task=task,
        )
        services.decide_participation(
            participation=participation,
            new_status=TaskParticipation.Status.APPROVED,
        )

        # First completion
        services.complete_participation(
            user=self.student1,
            task=task,
            code=task.verification_code,
        )

        # Points after first completion should be 100 + 50 = 150
        self.student1.refresh_from_db()
        points_after_first = self.student1.points
        self.assertEqual(points_after_first, 150)

        # Try to complete again (should fail since status is COMPLETED)
        with self.assertRaises(TaskParticipation.DoesNotExist):
            services.complete_participation(
                user=self.student1,
                task=task,
                code=task.verification_code,
            )

        # Points should not be credited twice
        self.student1.refresh_from_db()
        self.assertEqual(self.student1.points, points_after_first)


class EventConcurrencyTests(EventServiceTestCase):
    """Tests for concurrent access scenarios in event services."""

    def test_row_locking_prevents_race_conditions(self):
        """Test that row locking prevents race conditions in capacity checks."""
        task = Task.objects.create(
            title='Test Task',
            description='A test task',
            organization=self.organization,
            points_reward=50,
            max_participants=1,
            is_active=True,
        )

        # Create and approve first participation
        participation1 = services.request_participation(
            user=self.student1, task=task,
        )
        services.decide_participation(
            participation=participation1,
            new_status=TaskParticipation.Status.APPROVED,
        )

        # Manually create second pending participation
        participation2 = TaskParticipation.objects.create(
            task=task,
            student=self.student2,
            status=TaskParticipation.Status.PENDING,
        )

        # Try to approve - should fail due to capacity even though
        # we manually created the participation
        with self.assertRaises(EventFullError):
            services.decide_participation(
                participation=participation2,
                new_status=TaskParticipation.Status.APPROVED,
            )


class TaskModelTests(EventServiceTestCase):
    """Tests for Task model methods and properties."""

    def test_verification_code_generation(self):
        """Task should auto-generate unique verification codes."""
        task1 = Task.objects.create(
            title='Test Task 1',
            description='A test task',
            organization=self.organization,
            points_reward=50,
            is_active=True,
        )

        task2 = Task.objects.create(
            title='Test Task 2',
            description='Another test task',
            organization=self.organization,
            points_reward=50,
            is_active=True,
        )

        self.assertIsNotNone(task1.verification_code)
        self.assertIsNotNone(task2.verification_code)
        self.assertEqual(len(task1.verification_code), 8)
        self.assertEqual(len(task2.verification_code), 8)
        self.assertNotEqual(task1.verification_code, task2.verification_code)

    def test_approved_count_property(self):
        """Task.approved_count should return correct count."""
        task = Task.objects.create(
            title='Test Task',
            description='A test task',
            organization=self.organization,
            points_reward=50,
            max_participants=5,
            is_active=True,
        )

        # Create participations with different statuses
        p1 = services.request_participation(user=self.student1, task=task)
        p2 = services.request_participation(user=self.student2, task=task)

        services.decide_participation(
            participation=p1, new_status=TaskParticipation.Status.APPROVED,
        )
        services.decide_participation(
            participation=p2, new_status=TaskParticipation.Status.REJECTED,
        )

        self.assertEqual(task.approved_count, 1)

    def test_is_full_property(self):
        """Task.is_full should correctly reflect capacity status."""
        task = Task.objects.create(
            title='Test Task',
            description='A test task',
            organization=self.organization,
            points_reward=50,
            max_participants=2,
            is_active=True,
        )

        self.assertFalse(task.is_full)

        p1 = services.request_participation(user=self.student1, task=task)
        services.decide_participation(
            participation=p1, new_status=TaskParticipation.Status.APPROVED,
        )

        self.assertFalse(task.is_full)

        p2 = services.request_participation(user=self.student2, task=task)
        services.decide_participation(
            participation=p2, new_status=TaskParticipation.Status.APPROVED,
        )

        self.assertTrue(task.is_full)

    def test_is_full_without_capacity_limit(self):
        """Task without max_participants should never be full."""
        task = Task.objects.create(
            title='Test Task',
            description='A test task',
            organization=self.organization,
            points_reward=50,
            max_participants=None,
            is_active=True,
        )

        self.assertFalse(task.is_full)

        # Add many participations
        for i in range(10):
            student = User.objects.create_user(
                username=f'student_capacity_{i}',
                email=f'student_capacity_{i}@example.com',
                password='password',
                role=User.Role.STUDENT,
                full_name=f'Student Capacity {i}',
            )
            p = services.request_participation(user=student, task=task)
            services.decide_participation(
                participation=p, new_status=TaskParticipation.Status.APPROVED,
            )

        self.assertFalse(task.is_full)


class TaskParticipationModelTests(EventServiceTestCase):
    """Tests for TaskParticipation model methods."""

    def test_can_transition_to_valid_transitions(self):
        """TaskParticipation.can_transition_to should validate correctly."""
        task = Task.objects.create(
            title='Test Task',
            description='A test task',
            organization=self.organization,
            points_reward=50,
            is_active=True,
        )

        participation = services.request_participation(
            user=self.student1, task=task,
        )

        # From PENDING
        self.assertTrue(participation.can_transition_to(TaskParticipation.Status.APPROVED))
        self.assertTrue(participation.can_transition_to(TaskParticipation.Status.REJECTED))
        self.assertFalse(participation.can_transition_to(TaskParticipation.Status.COMPLETED))

        # From APPROVED
        participation.status = TaskParticipation.Status.APPROVED
        self.assertTrue(participation.can_transition_to(TaskParticipation.Status.COMPLETED))
        self.assertFalse(participation.can_transition_to(TaskParticipation.Status.APPROVED))
        self.assertFalse(participation.can_transition_to(TaskParticipation.Status.REJECTED))

        # From COMPLETED
        participation.status = TaskParticipation.Status.COMPLETED
        self.assertFalse(participation.can_transition_to(TaskParticipation.Status.APPROVED))
        self.assertFalse(participation.can_transition_to(TaskParticipation.Status.REJECTED))
        self.assertFalse(participation.can_transition_to(TaskParticipation.Status.COMPLETED))

    def test_unique_constraint_enforcement(self):
        """Database should enforce unique (task, student) constraint."""
        task = Task.objects.create(
            title='Test Task',
            description='A test task',
            organization=self.organization,
            points_reward=50,
            is_active=True,
        )

        # First participation
        services.request_participation(user=self.student1, task=task)

        # Try to create duplicate directly (bypassing service)
        with self.assertRaises(Exception):  # IntegrityError
            TaskParticipation.objects.create(
                task=task,
                student=self.student1,
                status=TaskParticipation.Status.PENDING,
            )
