from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.core.cache import (
    ORG_CACHE,
    PROJECT_CACHE,
    QUIZ_POOL_CACHE,
    SHOP_CACHE,
    invalidate_cache_families,
)
from apps.events.models import Task, TaskParticipation
from apps.organizations.models import Organization
from apps.projects.models import Project, ProjectCompletion
from apps.quizzes.models import Question
from apps.shop.models import Purchase, Shop, ShopItem
from apps.users.models import User


SEED_PASSWORD = 'password123'


@dataclass(frozen=True)
class SeedResult:
    users: int
    organizations: int
    tasks: int
    projects: int
    shops: int
    shop_items: int
    purchases: int
    quiz_questions: int


class Command(BaseCommand):
    help = 'Seed compact demo data for local manual testing.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--quiet',
            action='store_true',
            help='Suppress detailed seed output.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        users = self._seed_users()
        organizations = self._seed_organizations(users)
        tasks = self._seed_tasks(organizations)
        projects = self._seed_projects(organizations)
        shops = self._seed_shops(users)
        shop_items = self._seed_shop_items(shops)
        self._seed_task_participations(tasks, users)
        self._seed_project_completions(projects, users)
        purchases = self._seed_purchases(shop_items, users)
        quiz_questions = self._seed_quiz_questions(organizations)
        self._set_student_points(users)
        cache_warning = self._invalidate_caches()

        result = SeedResult(
            users=len(users),
            organizations=len(organizations),
            tasks=len(tasks),
            projects=len(projects),
            shops=len(shops),
            shop_items=len(shop_items),
            purchases=len(purchases),
            quiz_questions=len(quiz_questions),
        )
        if not options['quiet']:
            self._print_summary(result)
            if cache_warning:
                self.stdout.write(self.style.WARNING(cache_warning))

    def _invalidate_caches(self) -> str:
        try:
            invalidate_cache_families(
                ORG_CACHE,
                PROJECT_CACHE,
                SHOP_CACHE,
                QUIZ_POOL_CACHE,
            )
        except Exception as exc:  # noqa: BLE001 -- seed data should still commit.
            return f'Seeded data, but cache invalidation failed: {exc}'
        return ''

    def _upsert_user(
        self,
        *,
        email: str,
        username: str,
        role: str,
        full_name: str,
        points: int = 0,
        school: str | None = None,
        is_staff: bool = False,
        is_superuser: bool = False,
    ) -> User:
        user, _ = User.objects.update_or_create(
            email=email,
            defaults={
                'username': username,
                'role': role,
                'full_name': full_name,
                'student_id': username.upper() if role == User.Role.STUDENT else '',
                'school': school,
                'phone': '+77010000000',
                'points': points,
                'is_active': True,
                'is_staff': is_staff,
                'is_superuser': is_superuser,
            },
        )
        user.set_password(SEED_PASSWORD)
        user.save(update_fields=['password'])
        return user

    def _seed_users(self) -> dict[str, User]:
        schools = list(User.School.values)
        users = {
            'admin': self._upsert_user(
                email='admin@example.com',
                username='seed_admin',
                role=User.Role.ADMIN,
                full_name='Seed Admin',
                is_staff=True,
                is_superuser=True,
            ),
            'org1': self._upsert_user(
                email='org1@example.com',
                username='seed_org1',
                role=User.Role.ORGANIZATION,
                full_name='Green Campus Org Owner',
            ),
            'org2': self._upsert_user(
                email='org2@example.com',
                username='seed_org2',
                role=User.Role.ORGANIZATION,
                full_name='Eco Volunteers Org Owner',
            ),
            'org3': self._upsert_user(
                email='org3@example.com',
                username='seed_org3',
                role=User.Role.ORGANIZATION,
                full_name='Sustainability Lab Org Owner',
            ),
            'shop1': self._upsert_user(
                email='shop1@example.com',
                username='seed_shop1',
                role=User.Role.SHOP_OWNER,
                full_name='Internal Shop Owner',
            ),
            'shop2': self._upsert_user(
                email='shop2@example.com',
                username='seed_shop2',
                role=User.Role.SHOP_OWNER,
                full_name='External Shop Owner',
            ),
        }
        for index in range(1, 6):
            users[f'student{index}'] = self._upsert_user(
                email=f'student{index}@example.com',
                username=f'seed_student{index}',
                role=User.Role.STUDENT,
                full_name=f'Seed Student {index}',
                points=150 + (index * 25),
                school=schools[(index - 1) % len(schools)],
            )
        return users

    def _seed_organizations(self, users: dict[str, User]) -> dict[str, Organization]:
        specs = [
            (
                'green-campus',
                'Green Campus Initiative',
                'Student-led campus cleanup, recycling, and awareness events.',
                users['org1'],
            ),
            (
                'eco-volunteers',
                'Eco Volunteers Club',
                'Volunteer community focused on practical ESG action.',
                users['org2'],
            ),
            (
                'sustainability-lab',
                'Sustainability Lab',
                'Applied student projects for energy, waste, and climate impact.',
                users['org3'],
            ),
        ]
        organizations = {}
        for key, name, description, owner in specs:
            organization, _ = Organization.objects.update_or_create(
                name=name,
                defaults={
                    'description': description,
                    'owner': owner,
                    'is_active': True,
                },
            )
            organizations[key] = organization
        return organizations

    def _seed_tasks(self, organizations: dict[str, Organization]) -> list[Task]:
        now = timezone.now()
        specs = [
            ('Campus Cleanup Sprint', organizations['green-campus'], 40, 25, 'Main Quad', 2),
            ('Bottle Sorting Booth', organizations['green-campus'], 25, 12, 'Student Center', 4),
            ('Tree Planting Morning', organizations['eco-volunteers'], 60, 30, 'North Garden', 7),
            ('Energy Audit Walkthrough', organizations['sustainability-lab'], 35, 15, 'Engineering Block', 10),
            ('Zero Waste Workshop', organizations['sustainability-lab'], 30, 20, 'Room B204', 14),
        ]
        tasks = []
        for title, organization, points, max_participants, location, days in specs:
            task, _ = Task.objects.update_or_create(
                title=title,
                organization=organization,
                defaults={
                    'description': f'Demo event for {organization.name}.',
                    'points_reward': points,
                    'max_participants': max_participants,
                    'location': location,
                    'event_datetime': now + timedelta(days=days),
                    'is_active': True,
                },
            )
            tasks.append(task)
        return tasks

    def _seed_projects(self, organizations: dict[str, Organization]) -> list[Project]:
        specs = [
            ('Recycling Habit Survey', organizations['green-campus'], 45),
            ('Dorm Energy Tracker', organizations['sustainability-lab'], 80),
            ('Green Commute Research', organizations['eco-volunteers'], 55),
            ('Water Bottle Refill Map', organizations['green-campus'], 50),
        ]
        projects = []
        for title, organization, points in specs:
            project, _ = Project.objects.update_or_create(
                title=title,
                organization=organization,
                defaults={
                    'description': f'Demo project hosted by {organization.name}.',
                    'google_form_url': 'https://example.com/forms/esg-demo',
                    'points_reward': points,
                    'is_active': True,
                },
            )
            projects.append(project)
        return projects

    def _seed_shops(self, users: dict[str, User]) -> dict[str, Shop]:
        specs = [
            (
                'internal',
                'Campus Rewards Desk',
                'Internal desk for redeeming ESG points on campus.',
                'Student Center, 1st floor',
                Shop.Type.INTERNAL,
                users['shop1'],
            ),
            (
                'external',
                'Eco Partner Cafe',
                'External partner accepting promo codes from students.',
                'Green Street 12',
                Shop.Type.EXTERNAL,
                users['shop2'],
            ),
        ]
        shops = {}
        for key, name, description, address, shop_type, owner in specs:
            shop, _ = Shop.objects.update_or_create(
                name=name,
                defaults={
                    'description': description,
                    'address': address,
                    'shop_type': shop_type,
                    'owner': owner,
                    'is_active': True,
                },
            )
            shops[key] = shop
        return shops

    def _seed_shop_items(self, shops: dict[str, Shop]) -> list[ShopItem]:
        specs = [
            ('Reusable Bottle', shops['internal'], 80),
            ('Campus Hoodie Discount', shops['internal'], 120),
            ('Notebook Pack', shops['internal'], 45),
            ('Coffee Coupon', shops['external'], 60),
            ('Vegetarian Lunch Discount', shops['external'], 100),
            ('Eco Tote Bag', shops['external'], 90),
        ]
        items = []
        for title, shop, price in specs:
            item, _ = ShopItem.objects.update_or_create(
                title=title,
                shop=shop,
                defaults={
                    'description': f'Demo reward item from {shop.name}.',
                    'price': price,
                    'is_active': True,
                },
            )
            items.append(item)
        return items

    def _seed_task_participations(
        self,
        tasks: list[Task],
        users: dict[str, User],
    ) -> None:
        specs = [
            (tasks[0], users['student1'], TaskParticipation.Status.APPROVED),
            (tasks[0], users['student2'], TaskParticipation.Status.COMPLETED),
            (tasks[1], users['student3'], TaskParticipation.Status.PENDING),
            (tasks[2], users['student4'], TaskParticipation.Status.REJECTED),
            (tasks[3], users['student5'], TaskParticipation.Status.APPROVED),
        ]
        for task, student, participation_status in specs:
            TaskParticipation.objects.update_or_create(
                task=task,
                student=student,
                defaults={'status': participation_status},
            )

    def _seed_project_completions(
        self,
        projects: list[Project],
        users: dict[str, User],
    ) -> None:
        specs = [
            (projects[0], users['student1']),
            (projects[1], users['student2']),
            (projects[2], users['student3']),
        ]
        for project, student in specs:
            ProjectCompletion.objects.get_or_create(project=project, student=student)

    def _seed_purchases(
        self,
        items: list[ShopItem],
        users: dict[str, User],
    ) -> list[Purchase]:
        specs = [
            (items[0], users['student1'], Purchase.Status.PENDING),
            (items[1], users['student2'], Purchase.Status.COMPLETED),
            (items[3], users['student3'], Purchase.Status.READY),
            (items[4], users['student4'], Purchase.Status.COMPLETED),
            (items[2], users['student5'], Purchase.Status.REJECTED),
        ]
        purchases = []
        for item, student, status in specs:
            purchase, _ = Purchase.objects.update_or_create(
                item=item,
                student=student,
                defaults={
                    'points_spent': item.price,
                    'status': status,
                },
            )
            purchases.append(purchase)
        return purchases

    def _seed_quiz_questions(
        self,
        organizations: dict[str, Organization],
    ) -> list[Question]:
        specs = [
            ('Recycling plastic bottles usually reduces landfill waste.', True, organizations['green-campus']),
            ('Leaving classroom lights on overnight saves energy.', False, organizations['sustainability-lab']),
            ('Public transport can reduce individual carbon emissions.', True, organizations['eco-volunteers']),
            ('Single-use cups are always better than reusable cups.', False, organizations['green-campus']),
            ('Which action best reduces food waste?', ['Buying only what you need', 'Ignoring expiry dates', 'Throwing leftovers away', 'Using more packaging'], 0, organizations['eco-volunteers']),
            ('Which is a renewable energy source?', ['Coal', 'Solar', 'Diesel', 'Natural gas'], 1, organizations['sustainability-lab']),
            ('What does ESG include?', ['Energy, Soil, Gas', 'Environment, Social, Governance', 'Events, Students, Grades', 'Ecology, Sales, Growth'], 1, organizations['green-campus']),
            ('Which habit saves water?', ['Shorter showers', 'Running taps', 'Washing half-loads daily', 'Ignoring leaks'], 0, organizations['sustainability-lab']),
            ('Composting can help reduce organic waste.', True, organizations['eco-volunteers']),
            ('Bike commuting has no sustainability benefit.', False, organizations['green-campus']),
            ('Which item belongs in paper recycling?', ['Clean cardboard', 'Food scraps', 'Batteries', 'Plastic wrap'], 0, organizations['eco-volunteers']),
            ('Efficient appliances can lower electricity use.', True, organizations['sustainability-lab']),
        ]
        questions = []
        for spec in specs:
            if len(spec) == 3:
                text, answer, organization = spec
                defaults = {
                    'question_type': Question.QuestionType.TRUE_FALSE,
                    'answer': answer,
                    'options': None,
                    'correct_index': None,
                    'explanation': 'Seeded true/false ESG question.',
                    'created_by': organization,
                    'is_active': True,
                }
            else:
                text, options, correct_index, organization = spec
                defaults = {
                    'question_type': Question.QuestionType.MULTIPLE_CHOICE,
                    'answer': None,
                    'options': options,
                    'correct_index': correct_index,
                    'explanation': 'Seeded multiple-choice ESG question.',
                    'created_by': organization,
                    'is_active': True,
                }
            question, _ = Question.objects.update_or_create(
                text=text,
                defaults=defaults,
            )
            questions.append(question)
        return questions

    def _set_student_points(self, users: dict[str, User]) -> None:
        point_map = {
            'student1': 320,
            'student2': 275,
            'student3': 210,
            'student4': 185,
            'student5': 160,
        }
        for key, points in point_map.items():
            User.objects.filter(pk=users[key].pk).update(points=points)

    def _print_summary(self, result: SeedResult) -> None:
        self.stdout.write(self.style.SUCCESS('Seed data is ready.'))
        self.stdout.write(f'Users: {result.users}')
        self.stdout.write(f'Organizations: {result.organizations}')
        self.stdout.write(f'Tasks: {result.tasks}')
        self.stdout.write(f'Projects: {result.projects}')
        self.stdout.write(f'Shops: {result.shops}')
        self.stdout.write(f'Shop items: {result.shop_items}')
        self.stdout.write(f'Purchases: {result.purchases}')
        self.stdout.write(f'Quiz questions: {result.quiz_questions}')
        self.stdout.write('')
        self.stdout.write('Login emails:')
        self.stdout.write('  admin@example.com')
        self.stdout.write('  org1@example.com / org2@example.com / org3@example.com')
        self.stdout.write('  shop1@example.com / shop2@example.com')
        self.stdout.write('  student1@example.com ... student5@example.com')
        self.stdout.write(f'Password for all seeded users: {SEED_PASSWORD}')
