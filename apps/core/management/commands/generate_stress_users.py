"""
Generate test users and pre-computed JWT tokens for k6 stress tests.

Creates *count* student users (default 15), generates a valid access
token for each, and writes the result as JSON to ``tests/stress/test_users.json``
so the k6 load script can pick them up without the register/login dance.

Usage::

    python manage.py generate_stress_users --count 15

The output file is structured as a JSON array::

    [
        {
            "email": "stress_user_0@esg-test.local",
            "password": "StressTest123!",
            "token": "eyJ...",
            "refresh": "eyJ..."
        },
        ...
    ]

Re-running the command will remove and re-create the users so tokens
stay fresh.
"""

from __future__ import annotations

import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from rest_framework_simplejwt.tokens import RefreshToken

from apps.users.models import User

STRESS_DIR = os.path.join(settings.BASE_DIR, 'tests', 'stress')
OUTPUT_FILE = os.path.join(STRESS_DIR, 'test_users.json')
DEFAULT_COUNT = 15
PASSWORD = 'StressTest123!'


class Command(BaseCommand):
    help = 'Create stress-test users and pre-generate JWT tokens.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--count',
            type=int,
            default=DEFAULT_COUNT,
            help=f'Number of test users to create (default: {DEFAULT_COUNT}).',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        count = options['count']

        # Remove any previous stress users so tokens stay fresh
        deleted, _ = User.objects.filter(
            email__startswith='stress_user_',
        ).delete()
        if deleted:
            self.stdout.write(f'Removed {deleted} previous stress user(s).')

        users = []
        for i in range(count):
            email = f'stress_user_{i}@esg-test.local'
            user = User.objects.create_user(
                username=email,
                email=email,
                password=PASSWORD,
                full_name=f'Stress User {i}',
                student_id=f'STRESS-{i:04d}',
                role=User.Role.STUDENT,
                school=User.School.IT_ENGINEERING,
            )
            refresh = RefreshToken.for_user(user)
            users.append({
                'email': email,
                'password': PASSWORD,
                'token': str(refresh.access_token),
                'refresh': str(refresh),
            })

        os.makedirs(STRESS_DIR, exist_ok=True)
        with open(OUTPUT_FILE, 'w') as f:
            json.dump(users, f, indent=2)

        self.stdout.write(self.style.SUCCESS(
            f'Created {count} stress user(s) and wrote tokens to '
            f'{OUTPUT_FILE}',
        ))
