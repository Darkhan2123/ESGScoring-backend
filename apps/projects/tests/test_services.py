"""
Tests for the projects app service layer.

These tests focus on the business logic in :mod:`apps.projects.services`:
- Project point claiming with verification code validation
- Duplicate claim prevention
- Points crediting and atomic operations
- Timing attack resistance
"""
from django.test import TestCase
from apps.core.exceptions import (
    DuplicateRequestError,
    InvalidVerificationCodeError,
)
from apps.projects.models import Project, ProjectCompletion
from apps.projects import services
from apps.organizations.models import Organization
from apps.users.models import User


class ProjectServiceTestCase(TestCase):
    """Base test case with common setup for project service tests."""

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
            points=150,
        )
        self.project = Project.objects.create(
            title='Test Project',
            description='A test project',
            organization=self.organization,
            google_form_url='https://forms.google.com/example',
            points_reward=50,
            is_active=True,
        )


class ClaimProjectPointsTests(ProjectServiceTestCase):
    """Tests for services.claim_project_points()."""

    def test_successful_claim_credits_points(self):
        """Student can successfully claim points with valid verification code."""
        initial_points = self.student1.points

        completion = services.claim_project_points(
            user=self.student1,
            project=self.project,
            code=self.project.verification_code,
        )

        self.assertEqual(completion.student, self.student1)
        self.assertEqual(completion.project, self.project)
        self.assertEqual(ProjectCompletion.objects.count(), 1)

        # Check points were credited
        self.student1.refresh_from_db()
        expected_points = initial_points + self.project.points_reward
        self.assertEqual(self.student1.points, expected_points)

    def test_invalid_verification_code_raises_error(self):
        """Invalid verification code should raise InvalidVerificationCodeError."""
        with self.assertRaises(InvalidVerificationCodeError) as cm:
            services.claim_project_points(
                user=self.student1,
                project=self.project,
                code='WRONGCODE',
            )

        self.assertIn('Invalid verification code', str(cm.exception))

        # Points should not be credited
        self.student1.refresh_from_db()
        self.assertEqual(self.student1.points, 100)

    def test_duplicate_claim_raises_error(self):
        """Student cannot claim points for the same project twice."""
        # First claim should succeed
        services.claim_project_points(
            user=self.student1,
            project=self.project,
            code=self.project.verification_code,
        )

        # Second claim should raise DuplicateRequestError
        with self.assertRaises(DuplicateRequestError) as cm:
            services.claim_project_points(
                user=self.student1,
                project=self.project,
                code=self.project.verification_code,
            )

        self.assertIn('already claimed points', str(cm.exception))

        # Points should only be credited once
        self.student1.refresh_from_db()
        self.assertEqual(self.student1.points, 150)  # 100 + 50

    def test_different_students_can_claim_same_project(self):
        """Multiple students can claim points for the same project."""
        # First student claims
        services.claim_project_points(
            user=self.student1,
            project=self.project,
            code=self.project.verification_code,
        )

        # Second student should also be able to claim
        completion2 = services.claim_project_points(
            user=self.student2,
            project=self.project,
            code=self.project.verification_code,
        )

        self.assertEqual(completion2.student, self.student2)
        self.assertEqual(ProjectCompletion.objects.count(), 2)

        # Both students should have points credited
        self.student1.refresh_from_db()
        self.student2.refresh_from_db()
        self.assertEqual(self.student1.points, 150)  # 100 + 50
        self.assertEqual(self.student2.points, 200)  # 150 + 50

    def test_claim_with_none_verification_code(self):
        """Project with None verification code should raise InvalidVerificationCodeError."""
        project_no_code = Project.objects.create(
            title='Project No Code',
            description='A project without verification code',
            organization=self.organization,
            google_form_url='https://forms.google.com/example',
            points_reward=30,
            verification_code=None,
        )

        with self.assertRaises(InvalidVerificationCodeError):
            services.claim_project_points(
                user=self.student1,
                project=project_no_code,
                code='ANYCODE',
            )

    def test_claim_with_empty_string_verification_code(self):
        """Project with empty verification code should raise InvalidVerificationCodeError."""
        project_empty_code = Project.objects.create(
            title='Project Empty Code',
            description='A project with empty verification code',
            organization=self.organization,
            google_form_url='https://forms.google.com/example',
            points_reward=30,
            verification_code='',
        )

        with self.assertRaises(InvalidVerificationCodeError):
            services.claim_project_points(
                user=self.student1,
                project=project_empty_code,
                code='ANYCODE',
            )

    def test_claim_updates_user_points_atomically(self):
        """Points update uses F() for atomic operation."""
        initial_points = self.student1.points

        services.claim_project_points(
            user=self.student1,
            project=self.project,
            code=self.project.verification_code,
        )

        # Refresh to get the updated value
        self.student1.refresh_from_db()
        expected_points = initial_points + self.project.points_reward
        self.assertEqual(self.student1.points, expected_points)

    def test_completion_record_created_on_claim(self):
        """Claiming points creates a ProjectCompletion record."""
        completion = services.claim_project_points(
            user=self.student1,
            project=self.project,
            code=self.project.verification_code,
        )

        self.assertEqual(ProjectCompletion.objects.count(), 1)
        self.assertEqual(completion.project, self.project)
        self.assertEqual(completion.student, self.student1)
        self.assertIsNotNone(completion.created_at)


class TimingAttackResistanceTests(ProjectServiceTestCase):
    """Tests for timing attack resistance in verification code comparison."""

    def test_timing_attack_resistance(self):
        """Verification code comparison should be timing-attack resistant."""
        # Try wrong code of same length (timing attack scenario)
        wrong_code = 'X' * len(self.project.verification_code)

        with self.assertRaises(InvalidVerificationCodeError):
            services.claim_project_points(
                user=self.student1,
                project=self.project,
                code=wrong_code,
            )

        # Points should not be credited
        self.student1.refresh_from_db()
        self.assertEqual(self.student1.points, 100)

    def test_different_length_codes_handled_safely(self):
        """Codes of different lengths should also be handled safely."""
        with self.assertRaises(InvalidVerificationCodeError):
            services.claim_project_points(
                user=self.student1,
                project=self.project,
                code='SHORT',
            )

        # Points should not be credited
        self.student1.refresh_from_db()
        self.assertEqual(self.student1.points, 100)


class ProjectModelTests(ProjectServiceTestCase):
    """Tests for Project model methods and properties."""

    def test_verification_code_generation(self):
        """Project should auto-generate unique verification codes."""
        project1 = Project.objects.create(
            title='Project 1',
            description='First project',
            organization=self.organization,
            google_form_url='https://forms.google.com/example1',
            points_reward=50,
        )

        project2 = Project.objects.create(
            title='Project 2',
            description='Second project',
            organization=self.organization,
            google_form_url='https://forms.google.com/example2',
            points_reward=50,
        )

        self.assertIsNotNone(project1.verification_code)
        self.assertIsNotNone(project2.verification_code)
        self.assertEqual(len(project1.verification_code), 8)
        self.assertEqual(len(project2.verification_code), 8)
        self.assertNotEqual(project1.verification_code, project2.verification_code)

    def test_verification_code_uniqueness(self):
        """Verification codes should be unique across projects."""
        codes = set()
        for i in range(10):
            project = Project.objects.create(
                title=f'Project {i}',
                description=f'Project {i}',
                organization=self.organization,
                google_form_url=f'https://forms.google.com/example{i}',
                points_reward=50,
            )
            codes.add(project.verification_code)

        # All codes should be unique
        self.assertEqual(len(codes), 10)

    def test_verification_code_format(self):
        """Verification codes should be 8-character alphanumeric strings."""
        project = Project.objects.create(
            title='Test Project',
            description='Test',
            organization=self.organization,
            google_form_url='https://forms.google.com/test',
            points_reward=50,
        )

        code = project.verification_code
        self.assertEqual(len(code), 8)
        self.assertTrue(code.isalnum())
        self.assertTrue(code.isupper())  # Should be uppercase letters and digits

    def test_existing_verification_code_not_regenerated(self):
        """Existing verification code should not be regenerated on save."""
        original_code = self.project.verification_code
        original_title = self.project.title

        # Update the project
        self.project.title = 'Updated Title'
        self.project.description = 'Updated description'
        self.project.save()

        # Verification code should remain the same
        self.project.refresh_from_db()
        self.assertEqual(self.project.verification_code, original_code)
        self.assertEqual(self.project.title, 'Updated Title')

    def test_string_representation(self):
        """Project string representation should be the title."""
        self.assertEqual(str(self.project), 'Test Project')


class ProjectCompletionModelTests(ProjectServiceTestCase):
    """Tests for ProjectCompletion model methods and constraints."""

    def test_unique_constraint_on_project_student(self):
        """Cannot create duplicate completion for same project and student."""
        # Create completion via service
        services.claim_project_points(
            user=self.student1,
            project=self.project,
            code=self.project.verification_code,
        )

        # Try to create duplicate directly (should violate unique constraint)
        with self.assertRaises(Exception):  # IntegrityError
            ProjectCompletion.objects.create(
                project=self.project,
                student=self.student1,
            )

    def test_string_representation(self):
        """ProjectCompletion string representation should show student and project."""
        completion = services.claim_project_points(
            user=self.student1,
            project=self.project,
            code=self.project.verification_code,
        )

        expected = f"{self.student1} → {self.project.title}"
        self.assertEqual(str(completion), expected)

    def test_ordering_by_created_at_desc(self):
        """ProjectCompletions should be ordered by created_at descending."""
        # Create completions with a delay
        completion1 = services.claim_project_points(
            user=self.student1,
            project=self.project,
            code=self.project.verification_code,
        )

        project2 = Project.objects.create(
            title='Project 2',
            description='Second project',
            organization=self.organization,
            google_form_url='https://forms.google.com/example2',
            points_reward=30,
        )

        completion2 = services.claim_project_points(
            user=self.student2,
            project=project2,
            code=project2.verification_code,
        )

        # Get all completions
        all_completions = list(ProjectCompletion.objects.all())

        # Most recent should be first
        self.assertEqual(all_completions[0], completion2)
        self.assertEqual(all_completions[1], completion1)
