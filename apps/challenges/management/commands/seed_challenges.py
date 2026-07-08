from django.core.management.base import BaseCommand

from apps.challenges.models import Badge, Challenge, EcoLevel


class Command(BaseCommand):
    help = 'Seed Eco-Challenge levels, challenges and badges'

    def handle(self, *args, **options):
        self.seed_levels()
        self.seed_challenges()
        self.seed_badges()

        self.stdout.write(
            self.style.SUCCESS('Eco-Challenge seed data created successfully.')
        )

    def seed_levels(self):
        levels = [
            (1, 'Eco Starter', 0),
            (2, 'Green Beginner', 100),
            (3, 'Eco Explorer', 250),
            (4, 'Green Student', 500),
            (5, 'Eco Active', 900),
            (6, 'Green Member', 1400),
            (7, 'Eco Leader', 2000),
            (8, 'Green Hero', 2800),
            (9, 'Campus Champion', 3800),
            (10, 'Eco Legend', 5000),
        ]

        for level_number, title, required_xp in levels:
            EcoLevel.objects.update_or_create(
                level_number=level_number,
                defaults={
                    'title': title,
                    'required_xp': required_xp,
                },
            )

    def seed_challenges(self):
        daily_challenges = [
            {
                'title': 'Приехал в КБТУ на велосипеде',
                'description': 'Приехать на велосипеде и подтвердить фото у кампуса.',
                'category': Challenge.Category.TRANSPORT,
                'base_xp': 50,
                'verification_type': Challenge.VerificationType.CAMERA_PHOTO,
            },
            {
                'title': 'Приехал на самокате',
                'description': 'Приехать на самокате и подтвердить фото рядом с КБТУ.',
                'category': Challenge.Category.TRANSPORT,
                'base_xp': 35,
                'verification_type': Challenge.VerificationType.CAMERA_PHOTO,
            },
            {
                'title': 'Прошёл пешком больше 1 км',
                'description': 'Пройти пешком больше 1 км и загрузить скриншот шагомера.',
                'category': Challenge.Category.ACTIVITY,
                'base_xp': 40,
                'verification_type': Challenge.VerificationType.SCREENSHOT,
            },
            {
                'title': 'Выбросил пластиковые бутылки в специальный бак',
                'description': 'Сдать пластиковые бутылки в специальный бак для переработки.',
                'category': Challenge.Category.WASTE,
                'base_xp': 30,
                'verification_type': Challenge.VerificationType.CAMERA_PHOTO,
            },
            {
                'title': 'Принёс многоразовую бутылку с водой',
                'description': 'Использовать свою бутылку вместо одноразовой.',
                'category': Challenge.Category.WASTE,
                'base_xp': 25,
                'verification_type': Challenge.VerificationType.CAMERA_PHOTO,
            },
            {
                'title': 'Принёс свой контейнер для еды',
                'description': 'Использовать свой контейнер вместо одноразовой упаковки.',
                'category': Challenge.Category.WASTE,
                'base_xp': 25,
                'verification_type': Challenge.VerificationType.CAMERA_PHOTO,
            },
            {
                'title': 'Отказался от одноразовых приборов',
                'description': 'Использовать свои приборы или не брать одноразовые.',
                'category': Challenge.Category.WASTE,
                'base_xp': 20,
                'verification_type': Challenge.VerificationType.CAMERA_PHOTO,
            },
            {
                'title': 'Отказался от пластикового пакета, перейти на шоперы, рюкзаки',
                'description': 'Не использовать пластиковый пакет при покупке.',
                'category': Challenge.Category.WASTE,
                'base_xp': 15,
                'verification_type': Challenge.VerificationType.NONE,
            },
            {
                'title': 'Завести электронные конспекты вместо тетрадей',
                'description': 'Вести записи в электронном формате вместо бумажного конспекта.',
                'category': Challenge.Category.WASTE,
                'base_xp': 15,
                'verification_type': Challenge.VerificationType.SCREENSHOT,
            },
            {
                'title': 'Поднялся по лестнице вместо лифта',
                'description': 'Использовать лестницу вместо лифта.',
                'category': Challenge.Category.ACTIVITY,
                'base_xp': 10,
                'verification_type': Challenge.VerificationType.NONE,
            },
            {
                'title': 'Выключил свет уходя из аудитории',
                'description': 'Выключить свет, если аудитория пустая.',
                'category': Challenge.Category.ENERGY,
                'base_xp': 10,
                'verification_type': Challenge.VerificationType.NONE,
            },
            {
                'title': 'Отключил зарядку после полной зарядки',
                'description': 'Отключить зарядное устройство после использования.',
                'category': Challenge.Category.ENERGY,
                'base_xp': 5,
                'verification_type': Challenge.VerificationType.NONE,
            },
            {
                'title': 'Поднял мусор с территории кампуса',
                'description': 'Убрать небольшой мусор на территории кампуса.',
                'category': Challenge.Category.CAMPUS,
                'base_xp': 35,
                'verification_type': Challenge.VerificationType.CAMERA_PHOTO,
            },
        ]

        weekly_challenges = [
            {
                'title': 'Набрал 60 000 шагов за неделю',
                'description': 'Загрузить скриншот из приложения здоровья или трекера.',
                'category': Challenge.Category.ACTIVITY,
                'base_xp': 180,
                'verification_type': Challenge.VerificationType.SCREENSHOT,
            },
            {
                'title': 'Накатал 30+ км на велосипеде за неделю',
                'description': 'Загрузить скриншот из Strava, Garmin или другого трекера.',
                'category': Challenge.Category.ACTIVITY,
                'base_xp': 200,
                'verification_type': Challenge.VerificationType.SCREENSHOT,
            },
            {
                'title': 'Посетил лекцию или мероприятие по ESG',
                'description': 'Принять участие в ESG или экологическом мероприятии.',
                'category': Challenge.Category.CAMPUS,
                'base_xp': 150,
                'verification_type': Challenge.VerificationType.CAMERA_PHOTO,
            },
            {
                'title': 'Поучаствовал в волонтёрском мероприятии',
                'description': 'Принять участие в волонтёрской активности.',
                'category': Challenge.Category.CAMPUS,
                'base_xp': 200,
                'verification_type': Challenge.VerificationType.CAMERA_PHOTO,
            },
            {
                'title': 'Отсортировал мусор и сдал в пункт приёма',
                'description': 'Отсортировать батарейки, лампочки, электронику или пластик и сдать их.',
                'category': Challenge.Category.WASTE,
                'base_xp': 200,
                'verification_type': Challenge.VerificationType.CAMERA_PHOTO,
            },
            {
                'title': 'Поучаствовал в субботнике с группой',
                'description': 'Принять участие в уборке территории вместе с группой.',
                'category': Challenge.Category.CAMPUS,
                'base_xp': 250,
                'verification_type': Challenge.VerificationType.CAMERA_PHOTO,
            },
            {
                'title': 'Отремонтировал вещь вместо выброса',
                'description': 'Починить вещь и использовать её дальше.',
                'category': Challenge.Category.WASTE,
                'base_xp': 100,
                'verification_type': Challenge.VerificationType.CAMERA_PHOTO,
            },
        ]

        for data in daily_challenges:
            Challenge.objects.update_or_create(
                title=data['title'],
                frequency=Challenge.Frequency.DAILY,
                defaults={
                    **data,
                    'frequency': Challenge.Frequency.DAILY,
                    'is_active': True,
                },
            )

        for data in weekly_challenges:
            Challenge.objects.update_or_create(
                title=data['title'],
                frequency=Challenge.Frequency.WEEKLY,
                defaults={
                    **data,
                    'frequency': Challenge.Frequency.WEEKLY,
                    'is_active': True,
                },
            )

    def seed_badges(self):
        badges = [
            {
                'key': 'first_step',
                'name': 'Первый шаг',
                'description': 'Выполнить первое Eco-Challenge задание.',
                'icon': 'leaf',
                'condition_type': Badge.ConditionType.COMPLETIONS,
                'condition_value': 1,
            },
            {
                'key': 'daily_5',
                'name': 'Эко-привычка',
                'description': 'Выполнить 5 ежедневных заданий.',
                'icon': 'calendar',
                'condition_type': Badge.ConditionType.DAILY_COMPLETIONS,
                'condition_value': 5,
            },
            {
                'key': 'weekly_1',
                'name': 'Большое действие',
                'description': 'Выполнить первое еженедельное задание.',
                'icon': 'star',
                'condition_type': Badge.ConditionType.WEEKLY_COMPLETIONS,
                'condition_value': 1,
            },
            {
                'key': 'streak_3',
                'name': 'Серия 3 дня',
                'description': 'Поддерживать серию 3 дня.',
                'icon': 'fire',
                'condition_type': Badge.ConditionType.STREAK,
                'condition_value': 3,
            },
            {
                'key': 'streak_7',
                'name': 'Неделя активности',
                'description': 'Поддерживать серию 7 дней.',
                'icon': 'fire',
                'condition_type': Badge.ConditionType.STREAK,
                'condition_value': 7,
            },
            {
                'key': 'streak_14',
                'name': 'Сильная серия',
                'description': 'Поддерживать серию 14 дней.',
                'icon': 'fire',
                'condition_type': Badge.ConditionType.STREAK,
                'condition_value': 14,
            },
            {
                'key': 'xp_500',
                'name': '500 XP',
                'description': 'Набрать 500 XP в Eco-Challenge.',
                'icon': 'xp',
                'condition_type': Badge.ConditionType.TOTAL_XP,
                'condition_value': 500,
            },
            {
                'key': 'xp_1000',
                'name': '1000 XP',
                'description': 'Набрать 1000 XP в Eco-Challenge.',
                'icon': 'xp',
                'condition_type': Badge.ConditionType.TOTAL_XP,
                'condition_value': 1000,
            },
            {
                'key': 'level_5',
                'name': 'Eco Active',
                'description': 'Достичь 5 уровня.',
                'icon': 'level',
                'condition_type': Badge.ConditionType.LEVEL,
                'condition_value': 5,
            },
            {
                'key': 'big_action_200',
                'name': 'Серьёзный вклад',
                'description': 'Получить 200 XP или больше за одно задание.',
                'icon': 'trophy',
                'condition_type': Badge.ConditionType.SINGLE_ACTION_XP,
                'condition_value': 200,
            },
        ]

        for data in badges:
            Badge.objects.update_or_create(
                key=data['key'],
                defaults=data,
            )