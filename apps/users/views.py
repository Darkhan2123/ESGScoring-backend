from rest_framework import status
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User
from .permissions import IsAdmin
from .serializers import (
    RegisterSerializer,
    LoginSerializer,
    UserSerializer,
    UpdateProfileSerializer,
    ChangePasswordSerializer,
    AdminCreateUserSerializer,
)


def get_tokens_for_user(user: User) -> dict:
    refresh = RefreshToken.for_user(user)
    return {
        'access': str(refresh.access_token),
        'refresh': str(refresh),
    }


# ── Public auth ──────────────────────────────────────────────

class RegisterView(APIView):
    """
    POST /api/auth/register/
    Request:  { email, full_name, password, student_id }
    Response: { token, refresh, user }
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        tokens = get_tokens_for_user(user)

        return Response(
            {
                'token': tokens['access'],
                'refresh': tokens['refresh'],
                'user': UserSerializer(user).data,
            },
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    """
    POST /api/auth/login/
    Request:  { email, password }
    Response: { token, refresh, user }
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        tokens = get_tokens_for_user(user)

        return Response({
            'token': tokens['access'],
            'refresh': tokens['refresh'],
            'user': UserSerializer(user).data,
        })


class RefreshTokenView(APIView):
    """
    POST /api/auth/token/refresh/
    Request:  { refresh }
    Response: { token, refresh }
    """
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
            return Response({
                'token': str(refresh.access_token),
                'refresh': str(refresh),
            })
        except Exception:
            return Response(
                {'error': 'Invalid or expired refresh token.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )


# ── Authenticated user ───────────────────────────────────────

class LogoutView(APIView):
    """
    POST /api/auth/logout/
    Request:  { refresh }
    Blacklists the refresh token so it can no longer be used.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            return Response(
                {'error': 'Refresh token is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response({'detail': 'Successfully logged out.'})
        except Exception:
            return Response(
                {'error': 'Invalid token.'},
                status=status.HTTP_400_BAD_REQUEST,
            )


class MeView(RetrieveUpdateAPIView):
    """
    GET   /api/auth/me/  → current user profile
    PATCH /api/auth/me/  → update profile
    """
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user

    def get_serializer_class(self):
        if self.request.method in ('PATCH', 'PUT'):
            return UpdateProfileSerializer
        return UserSerializer


class ChangePasswordView(APIView):
    """
    POST /api/auth/change-password/
    Request: { old_password, new_password }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data,
            context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data['new_password'])
        request.user.save()
        return Response({'detail': 'Password updated successfully.'})


# ── Admin-only ───────────────────────────────────────────────

class AdminCreateUserView(APIView):
    """
    POST /api/auth/admin/create-user/
    Super-admin creates users with any role (organization, shop_owner, etc.).
    Request: { email, full_name, password, role, student_id?, phone? }
    Response: { user }
    """
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
    """
    GET /api/auth/admin/users/
    Super-admin lists all users. Supports ?role=student filter.
    """
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        users = User.objects.all().order_by('-created_at')
        role = request.query_params.get('role')
        if role:
            users = users.filter(role=role)
        return Response(UserSerializer(users, many=True).data)


class AdminUserDetailView(APIView):
    """
    GET    /api/auth/admin/users/<id>/  → view user
    PATCH  /api/auth/admin/users/<id>/  → update role, is_active, stars, etc.
    DELETE /api/auth/admin/users/<id>/  → deactivate user
    """
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request, user_id):
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return Response({'error': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(UserSerializer(user).data)

    def patch(self, request, user_id):
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return Response({'error': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)

        allowed_fields = {'role', 'is_active', 'stars', 'full_name', 'phone', 'student_id'}
        for field, value in request.data.items():
            if field in allowed_fields:
                setattr(user, field, value)
        user.save()
        return Response(UserSerializer(user).data)

    def delete(self, request, user_id):
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return Response({'error': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)
        user.is_active = False
        user.save()
        return Response({'detail': 'User deactivated.'})
