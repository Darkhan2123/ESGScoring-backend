"""
API endpoint tests for the quizzes app.

These tests follow the strategy: 1 good case + 2 bad cases per endpoint.
"""
from datetime import timedelta

from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.organizations.models import Organization
from apps.quizzes import services
from apps.quizzes.models import DailyQuiz, Question, QuizAttempt
from apps.users.models import User


TEST_CACHE = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'test-cache-quizzes',
    }
}

TEST_SETTINGS = {
    'CACHES': TEST_CACHE,
    'CACHE_TTL_QUIZ_POOL': 300,
}

NO_THROTTLE_SETTINGS = {
    'CACHES': TEST_CACHE,
    'CACHE_TTL_QUIZ_POOL': 300,
    'REST_FRAMEWORK': {
        'DEFAULT_AUTHENTICATION_CLASSES': (
            'rest_framework_simplejwt.authentication.JWTAuthentication',
        ),
        'DEFAULT_PERMISSION_CLASSES': (
            'rest_framework.permissions.IsAuthenticated',
        ),
        'DEFAULT_FILTER_BACKENDS': (
            'django_filters.rest_framework.DjangoFilterBackend',
            'rest_framework.filters.SearchFilter',
            'rest_framework.filters.OrderingFilter',
        ),
        'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
        'PAGE_SIZE': 20,
        'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
        'EXCEPTION_HANDLER': 'apps.core.exception_handler.custom_exception_handler',
        'DEFAULT_THROTTLE_CLASSES': [
            'rest_framework.throttling.AnonRateThrottle',
            'rest_framework.throttling.UserRateThrottle',
            'rest_framework.throttling.ScopedRateThrottle',
        ],
        'DEFAULT_THROTTLE_RATES': {
            'anon': None,
            'user': None,
            'auth': None,
            'quiz': None,
            'purchases': None,
        },
    },
}


@override_settings(**TEST_SETTINGS)
class QuizAPITestCase(APITestCase):
    """Base test case with common setup for quiz API tests."""

    def setUp(self):
        cache.clear()

        self.admin = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='password',
            role=User.Role.ADMIN,
            full_name='Admin User',
            is_superuser=True,
        )
        self.org_owner_1 = User.objects.create_user(
            username='orgowner1',
            email='org1@example.com',
            password='password',
            role=User.Role.ORGANIZATION,
            full_name='Org Owner One',
        )
        self.org_owner_2 = User.objects.create_user(
            username='orgowner2',
            email='org2@example.com',
            password='password',
            role=User.Role.ORGANIZATION,
            full_name='Org Owner Two',
        )
        self.org_without_org = User.objects.create_user(
            username='orgwithoutorg',
            email='orgwithoutorg@example.com',
            password='password',
            role=User.Role.ORGANIZATION,
            full_name='Org Owner Without Org',
        )
        self.student_1 = User.objects.create_user(
            username='student1',
            email='student1@example.com',
            password='password',
            role=User.Role.STUDENT,
            full_name='Student One',
            student_id='STU001',
            points=100,
        )
        self.student_2 = User.objects.create_user(
            username='student2',
            email='student2@example.com',
            password='password',
            role=User.Role.STUDENT,
            full_name='Student Two',
            student_id='STU002',
        )
        self.inactive_user = User.objects.create_user(
            username='inactive',
            email='inactive@example.com',
            password='password',
            role=User.Role.STUDENT,
            full_name='Inactive User',
            is_active=False,
        )

        self.organization_1 = Organization.objects.create(
            name='Test Organization',
            owner=self.org_owner_1,
            is_active=True,
        )
        self.organization_2 = Organization.objects.create(
            name='Other Organization',
            owner=self.org_owner_2,
            is_active=True,
        )

        self.org_question = Question.objects.create(
            text='Org 1 True/False question',
            question_type=Question.QuestionType.TRUE_FALSE,
            answer=True,
            explanation='Because ESG matters.',
            created_by=self.organization_1,
            is_active=True,
        )
        self.other_org_question = Question.objects.create(
            text='Org 2 True/False question',
            question_type=Question.QuestionType.TRUE_FALSE,
            answer=False,
            explanation='Other org question.',
            created_by=self.organization_2,
            is_active=True,
        )
        self.global_questions = []
        for i in range(4):
            self.global_questions.append(
                Question.objects.create(
                    text=f'Global pool question {i}',
                    question_type=Question.QuestionType.TRUE_FALSE,
                    answer=True,
                    is_active=True,
                )
            )

    def assertHasFieldError(self, response_data, field_name):
        """Helper to check for field errors in both custom and DRF error formats."""
        if 'errors' in response_data:
            self.assertIn(field_name, response_data['errors'])
        else:
            self.assertIn(field_name, response_data)

    def _start_quiz_for_student(self, student=None):
        """Start today's quiz via the service layer and return attempt + served."""
        student = student or self.student_1
        attempt, daily_quiz, served, _ = services.start_daily_quiz(user=student)
        return attempt, daily_quiz, served


class QuestionListViewTests(QuizAPITestCase):
    """Tests for GET /api/quizzes/questions/."""

    def test_get_question_list_success(self):
        """Organization owner retrieves their scoped question list."""
        self.client.force_authenticate(self.org_owner_1)
        response = self.client.get(reverse('quiz_question_list'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('results', data)
        texts = [q['text'] for q in data['results']]
        self.assertIn('Org 1 True/False question', texts)
        self.assertNotIn('Org 2 True/False question', texts)

    def test_get_question_list_student_forbidden(self):
        """Student cannot retrieve the manager question list."""
        self.client.force_authenticate(self.student_1)
        response = self.client.get(reverse('quiz_question_list'))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_question_list_unauthenticated(self):
        """Unauthenticated user cannot retrieve the question list."""
        response = self.client.get(reverse('quiz_question_list'))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class QuestionBulkCreateViewTests(QuizAPITestCase):
    """Tests for POST /api/quizzes/questions/bulk/."""

    def test_bulk_create_questions_success(self):
        """Organization owner can bulk-create questions for their pool."""
        self.client.force_authenticate(self.org_owner_1)
        payload = {
            'questions': [
                {
                    'text': 'New bulk T/F question',
                    'answer': True,
                    'explanation': 'Explanation text',
                },
                {
                    'text': 'New bulk MC question',
                    'options': ['A', 'B', 'C', 'D'],
                    'correct_index': 2,
                },
            ],
        }
        response = self.client.post(
            reverse('quiz_question_bulk'), payload, format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data['created'], 2)
        self.assertEqual(len(data['ids']), 2)
        self.assertTrue(
            Question.objects.filter(text='New bulk T/F question').exists()
        )

    def test_bulk_create_questions_student_forbidden(self):
        """Student cannot bulk-create questions."""
        self.client.force_authenticate(self.student_1)
        payload = {'questions': [{'text': 'Hack question', 'answer': True}]}
        response = self.client.post(
            reverse('quiz_question_bulk'), payload, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_bulk_create_questions_invalid_payload(self):
        """Invalid bulk payload returns 400 Bad Request."""
        self.client.force_authenticate(self.org_owner_1)
        payload = {'questions': []}
        response = self.client.post(
            reverse('quiz_question_bulk'), payload, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertHasFieldError(response.json(), 'questions')


class QuestionDetailGetTests(QuizAPITestCase):
    """Tests for GET /api/quizzes/questions/<pk>/."""

    def test_get_question_detail_success(self):
        """Organization owner can retrieve a question they own."""
        self.client.force_authenticate(self.org_owner_1)
        response = self.client.get(
            reverse('quiz_question_detail', args=[self.org_question.pk]),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['id'], self.org_question.pk)
        self.assertEqual(data['text'], 'Org 1 True/False question')
        self.assertTrue(data['answer'])

    def test_get_question_detail_student_forbidden(self):
        """Student cannot retrieve manager question details."""
        self.client.force_authenticate(self.student_1)
        response = self.client.get(
            reverse('quiz_question_detail', args=[self.org_question.pk]),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_question_detail_other_org(self):
        """Organization owner cannot retrieve another org's question."""
        self.client.force_authenticate(self.org_owner_1)
        response = self.client.get(
            reverse('quiz_question_detail', args=[self.other_org_question.pk]),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class QuestionDetailPatchTests(QuizAPITestCase):
    """Tests for PATCH /api/quizzes/questions/<pk>/."""

    def test_patch_question_success(self):
        """Organization owner can patch their own question."""
        self.client.force_authenticate(self.org_owner_1)
        payload = {'explanation': 'Updated explanation'}
        response = self.client.patch(
            reverse('quiz_question_detail', args=[self.org_question.pk]),
            payload,
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['explanation'], 'Updated explanation')
        self.org_question.refresh_from_db()
        self.assertEqual(self.org_question.explanation, 'Updated explanation')

    def test_patch_question_student_forbidden(self):
        """Student cannot patch manager questions."""
        self.client.force_authenticate(self.student_1)
        payload = {'explanation': 'Hacked'}
        response = self.client.patch(
            reverse('quiz_question_detail', args=[self.org_question.pk]),
            payload,
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_patch_question_other_org(self):
        """Organization owner cannot patch another org's question."""
        self.client.force_authenticate(self.org_owner_1)
        payload = {'explanation': 'Hacked'}
        response = self.client.patch(
            reverse('quiz_question_detail', args=[self.other_org_question.pk]),
            payload,
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class QuestionDetailDeleteTests(QuizAPITestCase):
    """Tests for DELETE /api/quizzes/questions/<pk>/."""

    def test_delete_question_success(self):
        """Organization owner can soft-deactivate their own question."""
        self.client.force_authenticate(self.org_owner_1)
        response = self.client.delete(
            reverse('quiz_question_detail', args=[self.org_question.pk]),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.org_question.refresh_from_db()
        self.assertFalse(self.org_question.is_active)

    def test_delete_question_student_forbidden(self):
        """Student cannot deactivate manager questions."""
        self.client.force_authenticate(self.student_1)
        response = self.client.delete(
            reverse('quiz_question_detail', args=[self.org_question.pk]),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_question_other_org(self):
        """Organization owner cannot deactivate another org's question."""
        self.client.force_authenticate(self.org_owner_1)
        response = self.client.delete(
            reverse('quiz_question_detail', args=[self.other_org_question.pk]),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class DailyQuizListViewTests(QuizAPITestCase):
    """Tests for GET /api/quizzes/daily/."""

    def test_get_daily_quiz_list_success(self):
        """Organization owner can list past daily quiz days."""
        DailyQuiz.objects.create(date=services.local_today())
        self.client.force_authenticate(self.org_owner_1)
        response = self.client.get(reverse('daily_quiz_list'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('results', data)
        self.assertEqual(len(data['results']), 1)
        self.assertEqual(data['results'][0]['attempts_count'], 0)

    def test_get_daily_quiz_list_student_forbidden(self):
        """Student cannot retrieve the daily quiz analytics list."""
        self.client.force_authenticate(self.student_1)
        response = self.client.get(reverse('daily_quiz_list'))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_daily_quiz_list_unauthenticated(self):
        """Unauthenticated user cannot retrieve the daily quiz list."""
        response = self.client.get(reverse('daily_quiz_list'))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class DailyQuizAttemptsViewTests(QuizAPITestCase):
    """Tests for GET /api/quizzes/daily/<pk>/attempts/."""

    def test_get_daily_quiz_attempts_success(self):
        """Organization owner can list attempts for a daily quiz."""
        attempt, daily_quiz, _ = self._start_quiz_for_student()
        self.client.force_authenticate(self.org_owner_1)
        response = self.client.get(
            reverse('daily_quiz_attempts', args=[daily_quiz.pk]),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('results', data)
        self.assertEqual(len(data['results']), 1)
        self.assertEqual(data['results'][0]['id'], attempt.pk)
        self.assertEqual(data['results'][0]['user_email'], 'student1@example.com')

    def test_get_daily_quiz_attempts_student_forbidden(self):
        """Student cannot retrieve daily quiz attempt analytics."""
        daily_quiz = DailyQuiz.objects.create(date=services.local_today())
        self.client.force_authenticate(self.student_1)
        response = self.client.get(
            reverse('daily_quiz_attempts', args=[daily_quiz.pk]),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_daily_quiz_attempts_nonexistent(self):
        """Requesting attempts for a non-existent daily quiz returns 404."""
        self.client.force_authenticate(self.org_owner_1)
        response = self.client.get(reverse('daily_quiz_attempts', args=[99999]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class TodayStatusViewTests(QuizAPITestCase):
    """Tests for GET /api/quizzes/today/."""

    def test_get_today_status_success(self):
        """Student can retrieve today's quiz status."""
        self.client.force_authenticate(self.student_1)
        response = self.client.get(reverse('quiz_today_status'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data['available'])
        self.assertEqual(data['attempt_status'], 'not_started')
        self.assertIn('scoring', data)
        self.assertIn('time_limit_seconds', data)

    def test_get_today_status_org_forbidden(self):
        """Organization owner cannot retrieve student today status."""
        self.client.force_authenticate(self.org_owner_1)
        response = self.client.get(reverse('quiz_today_status'))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_today_status_unauthenticated(self):
        """Unauthenticated user cannot retrieve today status."""
        response = self.client.get(reverse('quiz_today_status'))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


@override_settings(**NO_THROTTLE_SETTINGS)
class TodayStartViewTests(QuizAPITestCase):
    """Tests for POST /api/quizzes/today/start/."""

    def test_start_today_quiz_success(self):
        """Student can start today's quiz and receive served questions."""
        self.client.force_authenticate(self.student_1)
        response = self.client.post(reverse('quiz_today_start'))

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertIn('daily_quiz_id', data)
        self.assertIn('attempt_id', data)
        self.assertEqual(len(data['questions']), 3)
        self.assertEqual(data['points_awarded'], services.SUBMIT_BASE_POINTS)

    def test_start_today_quiz_org_forbidden(self):
        """Organization owner cannot start a student quiz."""
        self.client.force_authenticate(self.org_owner_1)
        response = self.client.post(reverse('quiz_today_start'))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_start_today_quiz_pool_exhausted(self):
        """Starting quiz when the pool has too few questions returns 400."""
        Question.objects.all().update(is_active=False)
        self.client.force_authenticate(self.student_1)
        response = self.client.post(reverse('quiz_today_start'))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.json())
        self.assertEqual(response.json()['error_code'], 'PoolExhaustedError')


@override_settings(**NO_THROTTLE_SETTINGS)
class TodayAnswerViewTests(QuizAPITestCase):
    """Tests for POST /api/quizzes/today/answer/."""

    def test_answer_question_success(self):
        """Student can submit an answer for the first served question."""
        attempt, _, served = self._start_quiz_for_student()
        first = served[0]
        self.client.force_authenticate(self.student_1)
        payload = {
            'attempt_id': attempt.pk,
            'question_id': first.question_id,
            'selected_bool': first.question.answer,
        }
        response = self.client.post(
            reverse('quiz_today_answer'), payload, format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertTrue(data['is_correct'])
        self.assertEqual(data['answered_count'], 1)
        self.assertEqual(data['position'], 1)

    def test_answer_question_org_forbidden(self):
        """Organization owner cannot submit quiz answers."""
        self.client.force_authenticate(self.org_owner_1)
        payload = {
            'question_id': self.global_questions[0].pk,
            'selected_bool': True,
        }
        response = self.client.post(
            reverse('quiz_today_answer'), payload, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_answer_question_invalid_payload(self):
        """Payload missing both answer shapes returns 400 Bad Request."""
        attempt, _, served = self._start_quiz_for_student()
        self.client.force_authenticate(self.student_1)
        payload = {
            'attempt_id': attempt.pk,
            'question_id': served[0].question_id,
        }
        response = self.client.post(
            reverse('quiz_today_answer'), payload, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.json())


@override_settings(**NO_THROTTLE_SETTINGS)
class TodayForfeitViewTests(QuizAPITestCase):
    """Tests for POST /api/quizzes/today/forfeit/."""

    def test_forfeit_quiz_success(self):
        """Student can forfeit an in-progress attempt."""
        self._start_quiz_for_student()
        self.client.force_authenticate(self.student_1)
        response = self.client.post(reverse('quiz_today_forfeit'), {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        attempt = QuizAttempt.objects.get(user=self.student_1)
        self.assertEqual(attempt.status, QuizAttempt.Status.FORFEITED)

    def test_forfeit_quiz_org_forbidden(self):
        """Organization owner cannot forfeit a student quiz."""
        self.client.force_authenticate(self.org_owner_1)
        response = self.client.post(reverse('quiz_today_forfeit'), {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_forfeit_quiz_invalid_reason_length(self):
        """Forfeit reason longer than 32 characters returns 400."""
        self._start_quiz_for_student()
        self.client.force_authenticate(self.student_1)
        payload = {'reason': 'x' * 33}
        response = self.client.post(
            reverse('quiz_today_forfeit'), payload, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertHasFieldError(response.json(), 'reason')


class MyAttemptsViewTests(QuizAPITestCase):
    """Tests for GET /api/quizzes/my-attempts/."""

    def test_get_my_attempts_success(self):
        """Student can retrieve their own quiz attempt history."""
        attempt, daily_quiz, _ = self._start_quiz_for_student()
        self.client.force_authenticate(self.student_1)
        response = self.client.get(reverse('quiz_my_attempts'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('results', data)
        self.assertEqual(len(data['results']), 1)
        self.assertEqual(data['results'][0]['id'], attempt.pk)
        self.assertEqual(
            data['results'][0]['date'],
            daily_quiz.date.isoformat(),
        )

    def test_get_my_attempts_org_forbidden(self):
        """Organization owner cannot retrieve student attempt history."""
        self.client.force_authenticate(self.org_owner_1)
        response = self.client.get(reverse('quiz_my_attempts'))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_my_attempts_unauthenticated(self):
        """Unauthenticated user cannot retrieve attempt history."""
        response = self.client.get(reverse('quiz_my_attempts'))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
