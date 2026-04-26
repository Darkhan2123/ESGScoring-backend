"""
HTTP endpoints for authentication and user management.

All views are thin DRF ``APIView`` subclasses: they parse input, delegate
business logic to the serializer or the model layer, and return a response.
Shared concerns (pagination, 404 handling) are delegated to helpers in
:mod:`apps.core` so the same envelope reaches the mobile client from every
endpoint.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.generics import RetrieveUpdateAPIView, get_object_or_404
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.core.filters import apply_exact_filter
from apps.core.pagination import paginate

from .models import User
from .permissions import IsAdmin
from .serializers import (
    AdminCreateUserSerializer,
    AdminUpdateUserSerializer,
    ChangePasswordSerializer,
    LoginSerializer,
    RegisterSerializer,
    UpdateProfileSerializer,
    UserSerializer,
)


def _tokens_for(user: User) -> dict[str, str]:
    """Return an access/refresh token pair for ``user``."""
    refresh = RefreshToken.for_user(user)
    return {'access': str(refresh.access_token), 'refresh': str(refresh)}


def _auth_payload(user: User) -> dict:
    """Build the response body for successful login/register."""
    tokens = _tokens_for(user)
    return {
        'token': tokens['access'],
        'refresh': tokens['refresh'],
        'user': UserSerializer(user).data,
    }


# ─── Public endpoints ──────────────────────────────────────────────


class RegisterView(APIView):
    """Self-service registration — always creates a ``STUDENT``."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(_auth_payload(user), status=status.HTTP_201_CREATED)


class LoginView(APIView):
    """Email + password authentication, returns a JWT token pair."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        return Response(_auth_payload(user))


class RefreshTokenView(APIView):
    """Exchange a valid refresh token for a new access/refresh pair."""

    permission_classes = [AllowAny]

    def post(self, request):
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            return Response(
                {'error': 'Refresh token is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            refresh = RefreshToken(refresh_token)
        except Exception:
            return Response(
                {'error': 'Invalid or expired refresh token.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        return Response({
            'token': str(refresh.access_token),
            'refresh': str(refresh),
        })


# ─── Authenticated user endpoints ──────────────────────────────────


class LogoutView(APIView):
    """Blacklist a refresh token so it can no longer be exchanged."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            return Response(
                {'error': 'Refresh token is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            RefreshToken(refresh_token).blacklist()
        except Exception:
            return Response(
                {'error': 'Invalid token.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({'detail': 'Successfully logged out.'})


class MeView(RetrieveUpdateAPIView):
    """Read or patch the authenticated user's own profile.

    ``UpdateProfileSerializer`` intentionally excludes ``student_id`` so
    only admins may change it.
    """

    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user

    def get_serializer_class(self):
        if self.request.method in ('PATCH', 'PUT'):
            return UpdateProfileSerializer
        return UserSerializer


class ChangePasswordView(APIView):
    """Authenticated user changes their own password."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data, context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data['new_password'])
        request.user.save(update_fields=['password'])
        return Response({'detail': 'Password updated successfully.'})


# ─── Admin endpoints ───────────────────────────────────────────────


class AdminCreateUserView(APIView):
    """Admin creates a user with an arbitrary role."""

    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request):
        serializer = AdminCreateUserSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            {'user': UserSerializer(user).data},
            status=status.HTTP_201_CREATED,
        )


class AdminListUsersView(APIView):
    """Admin-only paginated list of users with optional ``?role=`` filter."""

    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        users = User.objects.order_by('-created_at')
        users = apply_exact_filter(users, request, 'role')
        return paginate(users, request, UserSerializer)


class AdminUserDetailView(APIView):
    """Admin read/update/soft-delete of any user account."""

    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request, user_id):
        user = get_object_or_404(User, pk=user_id)
        return Response(UserSerializer(user).data)

    def patch(self, request, user_id):
        user = get_object_or_404(User, pk=user_id)
        serializer = AdminUpdateUserSerializer(
            user, data=request.data, partial=True,
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(UserSerializer(user).data)

    def delete(self, request, user_id):
        user = get_object_or_404(User, pk=user_id)
        user.is_active = False
        user.save(update_fields=['is_active'])
        return Response({'detail': 'User deactivated.'})
