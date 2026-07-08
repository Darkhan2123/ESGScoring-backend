from django.urls import path

from .views import (
    AllBadgesView,
    ChallengeStatsView,
    CompleteChallengeView,
    DailyChallengesView,
    EcoLeaderboardView,
    EcoProfileView,
    MyBadgesView,
    MyCompletionsView,
    WeeklyChallengesView,
)

app_name = 'challenges'

urlpatterns = [
    path('daily/', DailyChallengesView.as_view(), name='daily'),
    path('weekly/', WeeklyChallengesView.as_view(), name='weekly'),
    path('<int:challenge_id>/complete/', CompleteChallengeView.as_view(), name='complete'),
    path('profile/', EcoProfileView.as_view(), name='profile'),
    path('completions/', MyCompletionsView.as_view(), name='completions'),
    path('badges/', MyBadgesView.as_view(), name='my-badges'),
    path('badges/all/', AllBadgesView.as_view(), name='all-badges'),
    path('leaderboard/', EcoLeaderboardView.as_view(), name='leaderboard'),
    path('stats/', ChallengeStatsView.as_view(), name='stats'),
]