"""
Tests for the quizzes app service layer.

These tests focus on the business logic in :mod:`apps.quizzes.services`:
- Question bulk creation and validation
- Daily quiz lifecycle (start, answer, forfeit)
- Points calculation and awarding
- Time limit enforcement
- Pool exhaustion handling
"""
from django.test import TestCase, override_settings
from django.utils import timezone
from datetime import date, datetime, timedelta
from apps.core.exceptions import (
    AlreadySubmittedError,
    InvalidQuizPayloadError,
    NoQuizScheduledError,
    PoolExhaustedError,
    TimeLimitExceededError,
)
from apps.quizzes.models import (
    Question,
    DailyQuiz,
    QuizAttempt,
    AttemptQuestion,
    QuizAnswer,
)
from apps.quizzes import services
from apps.organizations.models import Organization
from apps.users.models import User


class QuizServiceTestCase(TestCase):
    """Base test case with common setup for quiz service tests."""

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
        self.admin = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='password',
            role=User.Role.ADMIN,
            full_name='Admin',
            is_superuser=True,
        )
        self.student = User.objects.create_user(
            username='student',
            email='student@example.com',
            password='password',
            role=User.Role.STUDENT,
            full_name='Student',
            points=100,
        )


class BulkCreateQuestionsTests(QuizServiceTestCase):
    """Tests for services.bulk_create_questions()."""

    def test_create_true_false_questions(self):
        """Admin can create True/False questions in bulk."""
        items = [
            {
                'text': 'ESG stands for Environmental, Social, Governance',
                'answer': True,
                'explanation': 'ESG is indeed Environmental, Social, Governance',
            },
            {
                'text': 'Climate change is not a concern for businesses',
                'answer': False,
                'explanation': 'Climate change is a major business concern',
            },
        ]

        count, ids = services.bulk_create_questions(
            user=self.admin, items=items,
        )

        self.assertEqual(count, 2)
        self.assertEqual(len(ids), 2)
        self.assertEqual(Question.objects.count(), 2)

        q1 = Question.objects.get(pk=ids[0])
        self.assertEqual(q1.question_type, Question.QuestionType.TRUE_FALSE)
        self.assertTrue(q1.answer)
        self.assertIsNone(q1.options)
        self.assertIsNone(q1.correct_index)

    def test_create_multiple_choice_questions(self):
        """Admin can create multiple-choice questions in bulk."""
        items = [
            {
                'text': 'Which of these is an ESG factor?',
                'options': ['Environmental', 'Social', 'Governance', 'All of the above'],
                'correct_index': 3,
                'explanation': 'All three are ESG factors',
            },
        ]

        count, ids = services.bulk_create_questions(
            user=self.admin, items=items,
        )

        self.assertEqual(count, 1)
        self.assertEqual(Question.objects.count(), 1)

        q = Question.objects.first()
        self.assertEqual(q.question_type, Question.QuestionType.MULTIPLE_CHOICE)
        self.assertIsNone(q.answer)
        self.assertEqual(len(q.options), 4)
        self.assertEqual(q.correct_index, 3)

    def test_create_mixed_question_types(self):
        """Can create both True/False and MC questions in one request."""
        items = [
            {
                'text': 'True/False question',
                'answer': True,
            },
            {
                'text': 'Multiple choice question',
                'options': ['A', 'B', 'C', 'D'],
                'correct_index': 0,
            },
        ]

        count, ids = services.bulk_create_questions(
            user=self.admin, items=items,
        )

        self.assertEqual(count, 2)
        self.assertEqual(Question.objects.filter(
            question_type=Question.QuestionType.TRUE_FALSE
        ).count(), 1)
        self.assertEqual(Question.objects.filter(
            question_type=Question.QuestionType.MULTIPLE_CHOICE
        ).count(), 1)

    def test_org_user_creates_questions_for_their_org(self):
        """Organization users create questions scoped to their organization."""
        items = [
            {
                'text': 'Org-specific question',
                'answer': True,
            },
        ]

        count, ids = services.bulk_create_questions(
            user=self.org_owner, items=items,
        )

        self.assertEqual(count, 1)
        q = Question.objects.first()
        self.assertEqual(q.created_by, self.organization)

    def test_empty_items_list_raises_error(self):
        """Empty items list should raise InvalidQuizPayloadError."""
        with self.assertRaises(InvalidQuizPayloadError) as cm:
            services.bulk_create_questions(user=self.admin, items=[])

        self.assertIn('No questions provided', str(cm.exception))

    def test_non_list_items_raises_error(self):
        """Non-list items should raise InvalidQuizPayloadError."""
        with self.assertRaises(InvalidQuizPayloadError) as cm:
            services.bulk_create_questions(user=self.admin, items='not a list')

        self.assertIn('No questions provided', str(cm.exception))

    def test_exceeds_max_items_raises_error(self):
        """Request exceeding max items should raise InvalidQuizPayloadError."""
        # Create more than default max (200)
        items = [{'text': f'Question {i}', 'answer': True} for i in range(201)]

        with self.assertRaises(InvalidQuizPayloadError) as cm:
            services.bulk_create_questions(user=self.admin, items=items)

        self.assertIn('Cannot create more than', str(cm.exception))

    def test_invalid_question_shape_raises_error(self):
        """Questions with both answer and options should raise error."""
        items = [
            {
                'text': 'Invalid question',
                'answer': True,
                'options': ['A', 'B', 'C', 'D'],
                'correct_index': 0,
            },
        ]

        with self.assertRaises(InvalidQuizPayloadError) as cm:
            services.bulk_create_questions(user=self.admin, items=items)

        self.assertIn('failed validation', str(cm.exception))
        self.assertIsNotNone(cm.exception.errors)

    def test_missing_question_shape_raises_error(self):
        """Questions with neither answer nor options should raise error."""
        items = [
            {
                'text': 'Invalid question',
            },
        ]

        with self.assertRaises(InvalidQuizPayloadError) as cm:
            services.bulk_create_questions(user=self.admin, items=items)

        self.assertIn('failed validation', str(cm.exception))

    def test_invalid_answer_type_raises_error(self):
        """Non-boolean answer should raise validation error."""
        items = [
            {
                'text': 'Invalid question',
                'answer': 'not a boolean',
            },
        ]

        with self.assertRaises(InvalidQuizPayloadError) as cm:
            services.bulk_create_questions(user=self.admin, items=items)

        self.assertIn('failed validation', str(cm.exception))

    def test_invalid_options_format_raises_error(self):
        """Invalid options format should raise validation error."""
        items = [
            {
                'text': 'Invalid question',
                'options': ['A', 'B'],  # Only 2 options instead of 4
                'correct_index': 0,
            },
        ]

        with self.assertRaises(InvalidQuizPayloadError) as cm:
            services.bulk_create_questions(user=self.admin, items=items)

        self.assertIn('failed validation', str(cm.exception))

    def test_invalid_correct_index_raises_error(self):
        """Invalid correct_index should raise validation error."""
        items = [
            {
                'text': 'Invalid question',
                'options': ['A', 'B', 'C', 'D'],
                'correct_index': 5,  # Invalid index
            },
        ]

        with self.assertRaises(InvalidQuizPayloadError) as cm:
            services.bulk_create_questions(user=self.admin, items=items)

        self.assertIn('failed validation', str(cm.exception))

    def test_empty_option_string_raises_error(self):
        """Empty option strings should raise validation error."""
        items = [
            {
                'text': 'Invalid question',
                'options': ['A', '', 'C', 'D'],  # Empty string
                'correct_index': 0,
            },
        ]

        with self.assertRaises(InvalidQuizPayloadError) as cm:
            services.bulk_create_questions(user=self.admin, items=items)

        self.assertIn('failed validation', str(cm.exception))

    def test_org_user_without_org_raises_error(self):
        """Org user without organization should raise error."""
        org_user_no_org = User.objects.create_user(
            username='orguser2',
            email='orguser2@example.com',
            password='password',
            role=User.Role.ORGANIZATION,
            full_name='Org User No Org',
        )

        items = [{'text': 'Question', 'answer': True}]

        with self.assertRaises(InvalidQuizPayloadError) as cm:
            services.bulk_create_questions(user=org_user_no_org, items=items)

        self.assertIn('organization assigned', str(cm.exception))

    def test_validation_errors_are_aggregated(self):
        """Multiple validation errors should be reported together."""
        items = [
            {
                'text': '',  # Empty text
                'answer': True,
            },
            {
                'text': 'Valid question',
                'options': ['A', 'B'],  # Wrong number of options
                'correct_index': 0,
            },
        ]

        with self.assertRaises(InvalidQuizPayloadError) as cm:
            services.bulk_create_questions(user=self.admin, items=items)

        self.assertIn('failed validation', str(cm.exception))
        self.assertIsNotNone(cm.exception.errors)
        self.assertGreater(len(cm.exception.errors), 1)

    def test_no_questions_created_on_validation_error(self):
        """Validation errors should prevent any questions from being created."""
        initial_count = Question.objects.count()

        items = [
            {
                'text': 'Valid question',
                'answer': True,
            },
            {
                'text': '',  # Invalid
                'answer': True,
            },
        ]

        with self.assertRaises(InvalidQuizPayloadError):
            services.bulk_create_questions(user=self.admin, items=items)

        self.assertEqual(Question.objects.count(), initial_count)


class StartDailyQuizTests(QuizServiceTestCase):
    """Tests for services.start_daily_quiz()."""

    def setUp(self):
        super().setUp()
        # Create active questions for the pool
        for i in range(5):
            Question.objects.create(
                text=f'Question {i}',
                question_type=Question.QuestionType.TRUE_FALSE,
                answer=True,
                is_active=True,
            )

    def test_start_quiz_creates_attempt(self):
        """Starting a quiz creates a new attempt for the student."""
        attempt, daily_quiz, served_questions, server_now = services.start_daily_quiz(
            user=self.student,
        )

        self.assertEqual(attempt.user, self.student)
        self.assertEqual(attempt.status, QuizAttempt.Status.IN_PROGRESS)
        self.assertEqual(attempt.daily_quiz, daily_quiz)
        self.assertEqual(len(served_questions), 3)  # QUESTIONS_PER_QUIZ
        self.assertEqual(attempt.points_awarded, services.SUBMIT_BASE_POINTS)

    def test_start_quiz_awards_base_points(self):
        """Starting a quiz immediately awards base points."""
        initial_points = self.student.points

        services.start_daily_quiz(user=self.student)

        self.student.refresh_from_db()
        expected_points = initial_points + services.SUBMIT_BASE_POINTS
        self.assertEqual(self.student.points, expected_points)

    def test_start_quiz_creates_daily_quiz_if_missing(self):
        """Starting quiz creates DailyQuiz row for today if it doesn't exist."""
        self.assertEqual(DailyQuiz.objects.count(), 0)

        services.start_daily_quiz(user=self.student)

        self.assertEqual(DailyQuiz.objects.count(), 1)
        daily_quiz = DailyQuiz.objects.first()
        self.assertEqual(daily_quiz.date, services.local_today())

    def test_start_quiz_uses_existing_daily_quiz(self):
        """Starting quiz uses existing DailyQuiz for today."""
        # Create daily quiz manually
        today = services.local_today()
        existing_quiz = DailyQuiz.objects.create(date=today)

        attempt, daily_quiz, _, _ = services.start_daily_quiz(user=self.student)

        self.assertEqual(daily_quiz.pk, existing_quiz.pk)

    def test_start_quiz_picks_random_questions(self):
        """Starting quiz picks random questions from the pool."""
        attempt1, _, served1, _ = services.start_daily_quiz(user=self.student)

        # Create another student
        student2 = User.objects.create_user(
            username='student2',
            email='student2@example.com',
            password='password',
            role=User.Role.STUDENT,
            full_name='Student 2',
        )

        attempt2, _, served2, _ = services.start_daily_quiz(user=student2)

        # Get the question IDs for each attempt
        ids1 = [sq.question_id for sq in served1]
        ids2 = [sq.question_id for sq in served2]

        # They might be the same by chance, but let's check they're valid
        self.assertEqual(len(ids1), 3)
        self.assertEqual(len(ids2), 3)
        self.assertTrue(all(Question.objects.filter(pk=id, is_active=True).exists() for id in ids1))
        self.assertTrue(all(Question.objects.filter(pk=id, is_active=True).exists() for id in ids2))

    def test_start_quiz_resumes_existing_attempt(self):
        """Starting quiz resumes existing in-progress attempt."""
        # First start
        attempt1, daily_quiz, served1, _ = services.start_daily_quiz(user=self.student)

        # Second start (should resume)
        attempt2, daily_quiz2, served2, _ = services.start_daily_quiz(user=self.student)

        self.assertEqual(attempt1.pk, attempt2.pk)
        self.assertEqual(daily_quiz.pk, daily_quiz2.pk)
        # Should not award points again
        self.assertEqual(attempt2.points_awarded, services.SUBMIT_BASE_POINTS)

    def test_start_quiz_already_submitted_raises_error(self):
        """Cannot start quiz if already submitted today."""
        attempt, _, _, _ = services.start_daily_quiz(user=self.student)
        attempt.status = QuizAttempt.Status.SUBMITTED
        attempt.submitted_at = timezone.now()
        attempt.save()

        with self.assertRaises(AlreadySubmittedError) as cm:
            services.start_daily_quiz(user=self.student)

        self.assertIn('already played today', str(cm.exception))

    def test_start_quiz_pool_exhausted_raises_error(self):
        """Cannot start quiz if pool has fewer than 3 questions."""
        # Deactivate all questions
        Question.objects.all().update(is_active=False)

        with self.assertRaises(PoolExhaustedError) as cm:
            services.start_daily_quiz(user=self.student)

        self.assertIn('Not enough questions', str(cm.exception))

    def test_start_quiz_expired_attempt_raises_error(self):
        """Cannot resume if attempt is expired."""
        attempt, _, _, _ = services.start_daily_quiz(user=self.student)
        
        # Manually expire the attempt
        attempt.deadline_at = timezone.now() - timedelta(seconds=1)
        attempt.save()

        with self.assertRaises(AlreadySubmittedError) as cm:
            services.start_daily_quiz(user=self.student)

        self.assertIn('already played today', str(cm.exception))

    def test_start_quiz_auto_expires_old_attempts(self):
        """Starting quiz auto-expires old in-progress attempts."""
        attempt, _, _, _ = services.start_daily_quiz(user=self.student)
        
        # Manually set deadline in the past
        attempt.deadline_at = timezone.now() - timedelta(seconds=1)
        attempt.save()

        with self.assertRaises(AlreadySubmittedError):
            services.start_daily_quiz(user=self.student)

        # Attempt should be marked as expired
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, QuizAttempt.Status.EXPIRED)


class AnswerQuestionTests(QuizServiceTestCase):
    """Tests for services.answer_question()."""

    def setUp(self):
        super().setUp()
        # Create active questions - we'll customize per test

    def test_answer_true_false_correctly(self):
        """Student can answer True/False question correctly."""
        # Create TF questions
        Question.objects.all().delete()
        for i in range(5):
            Question.objects.create(
                text=f'TF Question {i}',
                question_type=Question.QuestionType.TRUE_FALSE,
                answer=True,
                is_active=True,
            )
        
        attempt, _, served, _ = services.start_daily_quiz(user=self.student)
        
        # Find a True/False question (they're all TF now)
        tf_served = served[0]
        
        result = services.answer_question(
            user=self.student,
            question_id=tf_served.question_id,
            selected_bool=tf_served.question.answer,
        )

        self.assertTrue(result['answer'].is_correct)
        self.assertEqual(result['answered_count'], 1)
        self.assertEqual(result['total_questions'], 3)
        self.assertFalse(result['is_complete'])

        # Check points were awarded
        self.student.refresh_from_db()
        self.assertEqual(
            self.student.points,
            100 + services.SUBMIT_BASE_POINTS + services.POINTS_PER_CORRECT,
        )

    def test_answer_true_false_incorrectly(self):
        """Student can answer True/False question incorrectly."""
        # Create TF questions
        Question.objects.all().delete()
        for i in range(5):
            Question.objects.create(
                text=f'TF Question {i}',
                question_type=Question.QuestionType.TRUE_FALSE,
                answer=True,
                is_active=True,
            )
        
        attempt, _, served, _ = services.start_daily_quiz(user=self.student)
        
        # Find a True/False question (they're all TF now)
        tf_served = served[0]

        result = services.answer_question(
            user=self.student,
            question_id=tf_served.question_id,
            selected_bool=not tf_served.question.answer,  # Wrong answer
        )

        self.assertFalse(result['answer'].is_correct)
        self.assertEqual(result['answered_count'], 1)

        # Points should not be awarded for incorrect answer
        self.student.refresh_from_db()
        self.assertEqual(
            self.student.points,
            100 + services.SUBMIT_BASE_POINTS,  # Only base points
        )

    def test_answer_multiple_choice_correctly(self):
        """Student can answer multiple choice question correctly."""
        # Create a pool with only MC questions to ensure we get MC questions
        Question.objects.all().delete()
        for i in range(5):
            Question.objects.create(
                text=f'MC Question {i}',
                question_type=Question.QuestionType.MULTIPLE_CHOICE,
                options=['A', 'B', 'C', 'D'],
                correct_index=i % 4,
                is_active=True,
            )
        
        attempt, _, served, _ = services.start_daily_quiz(user=self.student)
        
        # Find the MC question (they're all MC now)
        mc_served = served[0]
        
        result = services.answer_question(
            user=self.student,
            question_id=mc_served.question_id,
            selected_index=mc_served.question.correct_index,  # Correct index
        )

        self.assertTrue(result['answer'].is_correct)

    def test_answer_multiple_choice_incorrectly(self):
        """Student can answer multiple choice question incorrectly."""
        # Create a pool with only MC questions to ensure we get MC questions
        Question.objects.all().delete()
        for i in range(5):
            Question.objects.create(
                text=f'MC Question {i}',
                question_type=Question.QuestionType.MULTIPLE_CHOICE,
                options=['A', 'B', 'C', 'D'],
                correct_index=i % 4,
                is_active=True,
            )
        
        attempt, _, served, _ = services.start_daily_quiz(user=self.student)
        
        # Answer incorrectly
        mc_served = served[0]
        wrong_index = 0 if mc_served.question.correct_index != 0 else 1
        result = services.answer_question(
            user=self.student,
            question_id=mc_served.question_id,
            selected_index=wrong_index,  # Wrong index
        )
        self.assertFalse(result['answer'].is_correct)

    def test_answers_must_be_in_order(self):
        """Questions must be answered in served order."""
        # Create TF questions
        Question.objects.all().delete()
        for i in range(5):
            Question.objects.create(
                text=f'TF Question {i}',
                question_type=Question.QuestionType.TRUE_FALSE,
                answer=True,
                is_active=True,
            )
        
        attempt, _, served, _ = services.start_daily_quiz(user=self.student)
        
        # Try to answer second question first
        second_question = served[1]

        with self.assertRaises(InvalidQuizPayloadError) as cm:
            services.answer_question(
                user=self.student,
                question_id=second_question.question_id,
                selected_bool=True,
            )

        self.assertIn('in order', str(cm.exception))

    def test_completing_all_questions_submits_attempt(self):
        """Answering all questions auto-submits the attempt."""
        # Create TF questions
        Question.objects.all().delete()
        for i in range(5):
            Question.objects.create(
                text=f'TF Question {i}',
                question_type=Question.QuestionType.TRUE_FALSE,
                answer=True,
                is_active=True,
            )
        
        attempt, _, served, _ = services.start_daily_quiz(user=self.student)

        # Answer all questions
        for i, sq in enumerate(served):
            q = sq.question
            result = services.answer_question(
                user=self.student,
                question_id=q.pk,
                selected_bool=q.answer,
            )

            if i == len(served) - 1:  # Last question
                self.assertTrue(result['is_complete'])

        # Check attempt is submitted
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, QuizAttempt.Status.SUBMITTED)
        self.assertIsNotNone(attempt.submitted_at)

    def test_answer_without_starting_raises_error(self):
        """Cannot answer without starting the quiz."""
        with self.assertRaises(NoQuizScheduledError) as cm:
            services.answer_question(
                user=self.student,
                question_id=1,
                selected_bool=True,
            )

        self.assertIn('Start the quiz', str(cm.exception))

    def test_answer_already_submitted_raises_error(self):
        """Cannot answer after submission."""
        # Create TF questions
        Question.objects.all().delete()
        for i in range(5):
            Question.objects.create(
                text=f'TF Question {i}',
                question_type=Question.QuestionType.TRUE_FALSE,
                answer=True,
                is_active=True,
            )
        
        attempt, _, served, _ = services.start_daily_quiz(user=self.student)
        
        # Submit the attempt
        attempt.status = QuizAttempt.Status.SUBMITTED
        attempt.submitted_at = timezone.now()
        attempt.save()

        with self.assertRaises(AlreadySubmittedError) as cm:
            services.answer_question(
                user=self.student,
                question_id=served[0].question_id,
                selected_bool=True,
            )

        self.assertIn('already played today', str(cm.exception))

    def test_answer_time_limit_exceeded(self):
        """Cannot answer after time limit expires."""
        # Create TF questions
        Question.objects.all().delete()
        for i in range(5):
            Question.objects.create(
                text=f'TF Question {i}',
                question_type=Question.QuestionType.TRUE_FALSE,
                answer=True,
                is_active=True,
            )
        
        attempt, _, served, _ = services.start_daily_quiz(user=self.student)
        
        # Set deadline in the past
        attempt.deadline_at = timezone.now() - timedelta(seconds=1)
        attempt.save()

        with self.assertRaises(TimeLimitExceededError) as cm:
            services.answer_question(
                user=self.student,
                question_id=served[0].question_id,
                selected_bool=True,
            )

        self.assertIn('Time limit exceeded', str(cm.exception))

    def test_answer_auto_expires_on_timeout(self):
        """Answering after timeout auto-expires the attempt."""
        # Create TF questions
        Question.objects.all().delete()
        for i in range(5):
            Question.objects.create(
                text=f'TF Question {i}',
                question_type=Question.QuestionType.TRUE_FALSE,
                answer=True,
                is_active=True,
            )
        
        attempt, _, served, _ = services.start_daily_quiz(user=self.student)
        
        # Set deadline in the past
        attempt.deadline_at = timezone.now() - timedelta(seconds=1)
        attempt.save()

        with self.assertRaises(TimeLimitExceededError):
            services.answer_question(
                user=self.student,
                question_id=served[0].question_id,
                selected_bool=True,
            )

        # Attempt should be marked as expired
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, QuizAttempt.Status.EXPIRED)

    def test_answer_shape_mismatch_raises_error(self):
        """Answer shape must match question type."""
        # Create TF questions
        Question.objects.all().delete()
        for i in range(5):
            Question.objects.create(
                text=f'TF Question {i}',
                question_type=Question.QuestionType.TRUE_FALSE,
                answer=True,
                is_active=True,
            )
        
        attempt, _, served, _ = services.start_daily_quiz(user=self.student)
        
        # Find a True/False question (they're all TF now)
        tf_served = served[0]
        
        # Try to answer T/F question with selected_index
        with self.assertRaises(InvalidQuizPayloadError) as cm:
            services.answer_question(
                user=self.student,
                question_id=tf_served.question_id,
                selected_index=0,
            )

        self.assertIn('shape does not match', str(cm.exception))

    def test_points_kept_on_partial_completion(self):
        """Points are kept even if quiz is not completed."""
        # Create TF questions
        Question.objects.all().delete()
        for i in range(5):
            Question.objects.create(
                text=f'TF Question {i}',
                question_type=Question.QuestionType.TRUE_FALSE,
                answer=True,
                is_active=True,
            )
        
        attempt, _, served, _ = services.start_daily_quiz(user=self.student)
        
        # Points after starting should include base points
        self.student.refresh_from_db()
        points_after_start = self.student.points

        # Answer one question correctly
        first_question = served[0]
        services.answer_question(
            user=self.student,
            question_id=first_question.question_id,
            selected_bool=first_question.question.answer,
        )

        # Don't complete the quiz
        self.student.refresh_from_db()
        expected_points = points_after_start + services.POINTS_PER_CORRECT
        self.assertEqual(self.student.points, expected_points)


class ForfeitDailyQuizTests(QuizServiceTestCase):
    """Tests for services.forfeit_daily_quiz()."""

    def setUp(self):
        super().setUp()
        # Create active questions
        for i in range(5):
            Question.objects.create(
                text=f'Question {i}',
                question_type=Question.QuestionType.TRUE_FALSE,
                answer=True,
                is_active=True,
            )

    def test_forfeit_in_progress_attempt(self):
        """Can forfeit an in-progress attempt."""
        attempt, _, _, _ = services.start_daily_quiz(user=self.student)

        forfeited = services.forfeit_daily_quiz(user=self.student)

        self.assertIsNotNone(forfeited)
        self.assertEqual(forfeited.status, QuizAttempt.Status.FORFEITED)
        self.assertEqual(forfeited.forfeit_reason, 'app_background')

    def test_forfeit_with_custom_reason(self):
        """Can forfeit with a custom reason."""
        attempt, _, _, _ = services.start_daily_quiz(user=self.student)

        forfeited = services.forfeit_daily_quiz(
            user=self.student,
            reason='user_logout',
        )

        self.assertEqual(forfeited.forfeit_reason, 'user_logout')

    def test_forfeit_already_submitted_returns_attempt(self):
        """Forfeiting already submitted attempt returns it unchanged."""
        attempt, _, _, _ = services.start_daily_quiz(user=self.student)
        attempt.status = QuizAttempt.Status.SUBMITTED
        attempt.submitted_at = timezone.now()
        attempt.save()

        forfeited = services.forfeit_daily_quiz(user=self.student)

        self.assertEqual(forfeited.status, QuizAttempt.Status.SUBMITTED)

    def test_forfeit_without_attempt_returns_none(self):
        """Forfeiting without an attempt returns None."""
        forfeited = services.forfeit_daily_quiz(user=self.student)

        self.assertIsNone(forfeited)

    def test_forfeit_is_idempotent(self):
        """Forfeiting multiple times is safe."""
        attempt, _, _, _ = services.start_daily_quiz(user=self.student)

        forfeited1 = services.forfeit_daily_quiz(user=self.student)
        forfeited2 = services.forfeit_daily_quiz(user=self.student)

        self.assertEqual(forfeited1.pk, forfeited2.pk)
        self.assertEqual(forfeited1.status, QuizAttempt.Status.FORFEITED)

    def test_forfeit_sets_submitted_at(self):
        """Forfeiting sets the submitted_at timestamp."""
        attempt, _, _, _ = services.start_daily_quiz(user=self.student)
        
        before = timezone.now()
        forfeited = services.forfeit_daily_quiz(user=self.student)
        
        self.assertIsNotNone(forfeited.submitted_at)
        self.assertGreaterEqual(forfeited.submitted_at, before)


class GetTodayStatusForStudentTests(QuizServiceTestCase):
    """Tests for services.get_today_status_for_student()."""

    def setUp(self):
        super().setUp()
        # Create active questions
        for i in range(5):
            Question.objects.create(
                text=f'Question {i}',
                question_type=Question.QuestionType.TRUE_FALSE,
                answer=True,
                is_active=True,
            )

    def test_status_available_when_not_started(self):
        """Status shows available when quiz not started."""
        status = services.get_today_status_for_student(self.student)

        self.assertTrue(status['available'])
        self.assertIsNone(status['attempt'])
        self.assertEqual(status['attempt_status'], 'not_started')
        self.assertIsNone(status['reason'])

    def test_status_available_when_in_progress(self):
        """Status shows available when attempt is in progress."""
        attempt, _, _, _ = services.start_daily_quiz(user=self.student)

        status = services.get_today_status_for_student(self.student)

        self.assertTrue(status['available'])
        self.assertIsNotNone(status['attempt'])
        self.assertEqual(status['attempt_status'], QuizAttempt.Status.IN_PROGRESS)

    def test_status_not_available_when_submitted(self):
        """Status shows not available when attempt is submitted."""
        attempt, _, _, _ = services.start_daily_quiz(user=self.student)
        attempt.status = QuizAttempt.Status.SUBMITTED
        attempt.submitted_at = timezone.now()
        attempt.save()

        status = services.get_today_status_for_student(self.student)

        self.assertFalse(status['available'])
        self.assertEqual(status['reason'], 'already_played')
        self.assertEqual(status['attempt_status'], QuizAttempt.Status.SUBMITTED)

    def test_status_not_available_when_forfeited(self):
        """Status shows not available when attempt is forfeited."""
        attempt, _, _, _ = services.start_daily_quiz(user=self.student)
        services.forfeit_daily_quiz(user=self.student)

        status = services.get_today_status_for_student(self.student)

        self.assertFalse(status['available'])
        self.assertEqual(status['reason'], 'already_played')
        self.assertEqual(status['attempt_status'], QuizAttempt.Status.FORFEITED)

    def test_status_not_available_when_expired(self):
        """Status shows not available when attempt is expired."""
        attempt, _, _, _ = services.start_daily_quiz(user=self.student)
        attempt.deadline_at = timezone.now() - timedelta(seconds=1)
        attempt.save()

        status = services.get_today_status_for_student(self.student)

        self.assertFalse(status['available'])
        self.assertEqual(status['reason'], 'already_played')
        # Status endpoint detects expiration
        self.assertEqual(status['attempt_status'], QuizAttempt.Status.EXPIRED)

    def test_status_not_available_when_pool_exhausted(self):
        """Status shows not available when pool is exhausted."""
        # Deactivate all questions
        Question.objects.all().update(is_active=False)

        status = services.get_today_status_for_student(self.student)

        self.assertFalse(status['available'])
        self.assertEqual(status['reason'], 'pool_exhausted')
        self.assertEqual(status['attempt_status'], 'not_started')

    def test_status_effectively_expired_in_progress(self):
        """Status detects expired in-progress attempts."""
        attempt, _, _, _ = services.start_daily_quiz(user=self.student)
        attempt.deadline_at = timezone.now() - timedelta(seconds=1)
        attempt.save()

        status = services.get_today_status_for_student(self.student)

        self.assertFalse(status['available'])
        self.assertEqual(status['attempt_status'], QuizAttempt.Status.EXPIRED)


class QuestionPoolTests(QuizServiceTestCase):
    """Tests for question pool management."""

    def test_question_pool_for_manager_admin(self):
        """Admins see all questions in the pool."""
        # Create questions for different orgs
        org2 = Organization.objects.create(
            name='Org 2',
            owner=User.objects.create_user(
                username='org2owner',
                email='org2@example.com',
                password='password',
                role=User.Role.ORGANIZATION,
            ),
        )
        Question.objects.create(
            text='Admin question',
            question_type=Question.QuestionType.TRUE_FALSE,
            answer=True,
            is_active=True,
        )
        Question.objects.create(
            text='Org question',
            question_type=Question.QuestionType.TRUE_FALSE,
            answer=True,
            created_by=org2,
            is_active=True,
        )

        pool = services.question_pool_for_manager(self.admin)

        self.assertEqual(pool.count(), 2)

    def test_question_pool_for_manager_org_user(self):
        """Org users see only their organization's questions."""
        Question.objects.create(
            text='Org question',
            question_type=Question.QuestionType.TRUE_FALSE,
            answer=True,
            created_by=self.organization,
            is_active=True,
        )
        Question.objects.create(
            text='Other org question',
            question_type=Question.QuestionType.TRUE_FALSE,
            answer=True,
            is_active=True,
        )

        pool = services.question_pool_for_manager(self.org_owner)

        self.assertEqual(pool.count(), 1)
        self.assertEqual(pool.first().created_by, self.organization)

    def test_active_pool_ids_returns_active_questions(self):
        """Active pool IDs only includes active questions."""
        active_q = Question.objects.create(
            text='Active',
            question_type=Question.QuestionType.TRUE_FALSE,
            answer=True,
            is_active=True,
        )
        inactive_q = Question.objects.create(
            text='Inactive',
            question_type=Question.QuestionType.TRUE_FALSE,
            answer=True,
            is_active=False,
        )

        pool_ids = services._active_pool_ids()

        self.assertIn(active_q.pk, pool_ids)
        self.assertNotIn(inactive_q.pk, pool_ids)


class QuizModelTests(QuizServiceTestCase):
    """Tests for quiz model methods and validation."""

    def setUp(self):
        super().setUp()
        # Create active questions for model tests that need them
        for i in range(5):
            Question.objects.create(
                text=f'Question {i}',
                question_type=Question.QuestionType.TRUE_FALSE,
                answer=True,
                is_active=True,
            )

    def test_question_validation_true_false(self):
        """Question.clean() validates True/False questions."""
        q = Question(
            text='Test',
            question_type=Question.QuestionType.TRUE_FALSE,
            answer=None,  # Missing answer
        )

        with self.assertRaises(Exception):  # ValidationError
            q.clean()

    def test_question_validation_multiple_choice(self):
        """Question.clean() validates multiple choice questions."""
        q = Question(
            text='Test',
            question_type=Question.QuestionType.MULTIPLE_CHOICE,
            options=['A', 'B'],  # Wrong number
            correct_index=0,
        )

        with self.assertRaises(Exception):  # ValidationError
            q.clean()

    def test_daily_quiz_unique_date(self):
        """DailyQuiz has unique constraint on date."""
        today = services.local_today()
        DailyQuiz.objects.create(date=today)

        with self.assertRaises(Exception):  # IntegrityError
            DailyQuiz.objects.create(date=today)

    def test_quiz_attempt_unique_user_daily_quiz(self):
        """QuizAttempt has unique constraint on (user, daily_quiz)."""
        attempt, daily_quiz, _, _ = services.start_daily_quiz(user=self.student)

        with self.assertRaises(Exception):  # IntegrityError
            QuizAttempt.objects.create(
                user=self.student,
                daily_quiz=daily_quiz,
                status=QuizAttempt.Status.IN_PROGRESS,
                deadline_at=timezone.now() + timedelta(minutes=5),
            )

    def test_attempt_question_unique_position(self):
        """AttemptQuestion has unique constraint on (attempt, position)."""
        attempt, daily_quiz, _, _ = services.start_daily_quiz(user=self.student)
        q = Question.objects.first()

        with self.assertRaises(Exception):  # IntegrityError
            AttemptQuestion.objects.create(
                attempt=attempt,
                question=q,
                position=1,  # Duplicate position
            )

    def test_quiz_answer_unique_attempt_question(self):
        """QuizAnswer has unique constraint on (attempt, question)."""
        attempt, daily_quiz, served, _ = services.start_daily_quiz(user=self.student)
        first_q = served[0].question

        # Create an answer
        QuizAnswer.objects.create(
            attempt=attempt,
            question=first_q,
            selected_bool=True,
            is_correct=True,
        )

        with self.assertRaises(Exception):  # IntegrityError
            QuizAnswer.objects.create(
                attempt=attempt,
                question=first_q,
                selected_bool=False,
                is_correct=False,
            )
