from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.contrib.auth import login
from drf_spectacular.utils import extend_schema, OpenApiExample
from drf_spectacular.types import OpenApiTypes
import logging

logger = logging.getLogger(__name__)


@extend_schema(
    operation_id='auth_login',
    summary='Логін користувача',
    description='Аутентифікує користувача та повертає JWT токени (access та refresh). Також створює сесію для backward compatibility.',
    tags=['Authentication'],
    request={
        'application/json': {
            'type': 'object',
            'properties': {
                'username': {'type': 'string', 'description': 'Ім\'я користувача'},
                'password': {'type': 'string', 'description': 'Пароль користувача'}
            },
            'required': ['username', 'password']
        }
    },
    responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT, 401: OpenApiTypes.OBJECT, 500: OpenApiTypes.OBJECT},
    examples=[
        OpenApiExample(
            'Login Request',
            summary='Запит на логін',
            description='Приклад запиту на логін',
            value={
                'username': 'testuser',
                'password': 'testpassword123'
            },
            request_only=True
        ),
        OpenApiExample(
            'Successful Login',
            summary='Успішний логін',
            description='Приклад успішної відповіді логіну',
            value={
                'access': 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...',
                'refresh': 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...',
                'user': {
                    'id': 1,
                    'username': 'testuser',
                    'email': 'test@example.com',
                    'first_name': 'Test',
                    'last_name': 'User',
                    'is_active': True,
                    'date_joined': '2025-01-01T00:00:00Z'
                }
            },
            response_only=True
        )
    ]
)
@api_view(['POST'])
@permission_classes([AllowAny])
def login_view(request):
    """Логін користувача з поверненням JWT токенів"""
    username = request.data.get('username')
    password = request.data.get('password')
    
    if not username or not password:
        return Response({
            'detail': 'Username and password are required',
            'code': 'MISSING_CREDENTIALS'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    user = authenticate(username=username, password=password)
    
    if user is None:
        return Response({
            'detail': 'Invalid credentials',
            'code': 'INVALID_CREDENTIALS'
        }, status=status.HTTP_401_UNAUTHORIZED)
    
    if not user.is_active:
        return Response({
            'detail': 'User account is disabled',
            'code': 'ACCOUNT_DISABLED'
        }, status=status.HTTP_401_UNAUTHORIZED)
    
    try:
        # Створюємо JWT токени
        refresh = RefreshToken.for_user(user)
        access_token = refresh.access_token
        
        # Логінимо користувача в сесії (для backward compatibility)
        login(request, user)
        
        return Response({
            'access': str(access_token),
            'refresh': str(refresh),
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'is_active': user.is_active,
                'date_joined': user.date_joined
            }
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error creating JWT tokens: {e}", exc_info=True)
        return Response({
            'detail': 'Error creating authentication tokens',
            'code': 'TOKEN_ERROR'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema(
    operation_id='auth_refresh',
    summary='Оновлення JWT токенів',
    description='Оновлює access токен використовуючи refresh токен. Повертає новий access токен та оновлений refresh токен.',
    tags=['Authentication'],
    request={
        'application/json': {
            'type': 'object',
            'properties': {
                'refresh': {'type': 'string', 'description': 'Refresh токен для оновлення'}
            },
            'required': ['refresh']
        }
    },
    responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT, 401: OpenApiTypes.OBJECT},
    examples=[
        OpenApiExample(
            'Refresh Request',
            summary='Запит на оновлення токену',
            description='Приклад запиту на оновлення токену',
            value={
                'refresh': 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...'
            },
            request_only=True
        ),
        OpenApiExample(
            'Successful Refresh',
            summary='Успішне оновлення',
            description='Приклад успішної відповіді оновлення токену',
            value={
                'access': 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...',
                'refresh': 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...'
            },
            response_only=True
        )
    ]
)
@api_view(['POST'])
@permission_classes([AllowAny])
def refresh_token(request):
    """Оновлення JWT токенів"""
    refresh_token = request.data.get('refresh')
    
    if not refresh_token:
        return Response({
            'detail': 'Refresh token is required',
            'code': 'MISSING_REFRESH_TOKEN'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        refresh = RefreshToken(refresh_token)
        access_token = refresh.access_token
        
        return Response({
            'access': str(access_token),
            'refresh': str(refresh)
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error refreshing token: {e}", exc_info=True)
        return Response({
            'detail': 'Invalid or expired refresh token',
            'code': 'INVALID_REFRESH_TOKEN'
        }, status=status.HTTP_401_UNAUTHORIZED)


@extend_schema(
    operation_id='auth_me',
    summary='Інформація про поточного користувача',
    description='Повертає детальну інформацію про поточного аутентифікованого користувача.',
    tags=['Authentication'],
    responses={200: OpenApiTypes.OBJECT, 401: OpenApiTypes.OBJECT}
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def me_view(request):
    """Отримання інформації про поточного користувача"""
    user = request.user
    
    return Response({
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'is_active': user.is_active,
        'is_staff': user.is_staff,
        'is_superuser': user.is_superuser,
        'date_joined': user.date_joined,
        'last_login': user.last_login
    })


@extend_schema(
    operation_id='auth_logout',
    summary='Логаут користувача',
    description='Виконує логаут користувача, очищаючи сесію. Для JWT токенів необхідно видалити їх на клієнті.',
    tags=['Authentication'],
    responses={200: OpenApiTypes.OBJECT, 401: OpenApiTypes.OBJECT, 500: OpenApiTypes.OBJECT}
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout_view(request):
    """Логаут користувача"""
    try:
        # Для JWT токенів ми не можемо "відкликати" їх без додаткових налаштувань
        # Але можемо очистити сесію
        request.session.flush()
        
        return Response({
            'detail': 'Successfully logged out'
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error during logout: {e}", exc_info=True)
        return Response({
            'detail': 'Error during logout',
            'code': 'LOGOUT_ERROR'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

