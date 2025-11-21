from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.permissions import AllowAny
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from django.conf import settings
from django.utils import timezone
import os
import uuid
import base64
import logging
from datetime import date, timedelta
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample
from drf_spectacular.types import OpenApiTypes

from .serializers import (
    UploadSerializer, ProcessSerializer, PreviewResponseSerializer, 
    ResultResponseSerializer, ErrorResponseSerializer
)
from ..services.gemini_client import GeminiClient
from ..services.image_utils import build_preview_placeholder, combine_item_images

logger = logging.getLogger(__name__)


def build_prompt(user_prompt=None, additional_prompt=None, use_mask=False):
    """Побудова промпту для AI обробки одягу"""
    base = (
        "[TASK]\n"
        "Perform image editing: place the ITEM from the combined item image onto the PERSON in the person image as a natural try-on.\n"
        "The combined item image contains multiple items arranged in a grid - treat them as separate items to try on.\n\n"
        "[ASSETS]\n"
        "- PERSON: keep face, body, lighting, and background unchanged.\n"
        "- ITEMS: copy exactly from the item image, maintaining their individual characteristics and details.\n\n"
        "[PLACEMENT]\n"
        "Align each ITEM to the anatomically correct region; match scale, rotation, perspective; resolve occlusions.\n"
        "Choose the most suitable item from the combined image for the person's pose and body type.\n\n"
        "[CONSTRAINTS]\n"
        "Preserve ITEM identity: exact color, material, texture, logos, patterns, fasteners.\n"
        "Do not redesign or replace the ITEM. Do not alter PERSON identity or background. No extra accessories.\n\n"
        "[STYLE]\n"
        "Photorealistic blend; consistent shadows/highlights and noise.\n\n"
        "[OUTPUT]\n"
        "Return a single edited image where the chosen ITEM is clearly visible and naturally fitted on the PERSON.\n\n"
        "[FAIL IF]\n"
        "Never return an unchanged image. If uncertain, still place the most suitable ITEM as best as possible.\n\n"
        "[NEGATIVE]\n"
        "No fantasy variations, no color shifts, no new patterns, no brand swaps, no AI-art look.\n"
    )
    if user_prompt:
        base += f"\n[USER]\n{user_prompt}\n"
    if additional_prompt:
        base += f"\n[USER-SPECIFIC]\n{additional_prompt}\n"
    if use_mask:
        base += (
            "\n[MASK]\nUse the provided binary MASK over the item image. White=ITEM region of interest; use only this shape and texture.\n"
        )
    return base


def build_hair_prompt(user_prompt=None, additional_prompt=None):
    """Побудова промпту для AI обробки зачісок"""
    base = (
        "[TASK]\n"
        "Perform high-quality image editing: apply the HAIRSTYLE from the provided hairstyle image(s) onto the PERSON image as a natural, photorealistic hair try-on.\n\n"
        "[ASSETS]\n"
        "- PERSON: strictly preserve face identity, proportions, skin tone, lighting, and original background.\n"
        "- HAIRSTYLE: replicate exactly the length, texture, curl pattern, density, color, highlights, and hairline.\n\n"
        "[PLACEMENT]\n"
        "Precisely align the HAIRSTYLE to the PERSON's head. Adjust scale, rotation, and perspective. Ensure seamless integration around forehead, temples, and ears. Respect occlusions (e.g., earrings, glasses, hats).\n\n"
        "[BLENDING]\n"
        "Smoothly merge hair edges with scalp. Preserve natural transparency in flyaway hairs. Match global and local lighting conditions, shadows, and reflections. Avoid hard edges or cutout look.\n\n"
        "[CONSTRAINTS]\n"
        "Do not modify the PERSON's facial identity, head shape, skin, or background. Do not alter hairstyle identity unless explicitly requested (no recoloring, redesigning, or shortening/lengthening).\n\n"
        "[STYLE]\n"
        "Ultra-photorealistic output. Maintain natural texture, volume, depth, and strand-level detail. Ensure hair looks realistic under the given lighting.\n\n"
        "[OUTPUT]\n"
        "Return a single, final edited image with the chosen HAIRSTYLE naturally and convincingly fitted onto the PERSON.\n\n"
        "[NEGATIVE]\n"
        "No cartoonish style, no artificial glow, no extra accessories, no distortions, no unrealistic blending or duplicated strands.\n"
    )
    
    if user_prompt:
        base += f"\n[USER]\n{user_prompt}\n"
    if additional_prompt:
        base += f"\n[USER-SPECIFIC]\n{additional_prompt}\n"
    return base


@extend_schema(
    operation_id='api_home',
    summary='Головна сторінка API',
    description='Повертає інформацію про API та доступні ендпоінти',
    tags=['API Info'],
    responses={200: OpenApiTypes.OBJECT}
)
@api_view(['GET'])
@permission_classes([AllowAny])
def api_home(request):
    """Головна сторінка API"""
    return Response({
        'message': 'Lookify API v1.0',
        'description': 'API для сервісу віртуального приміряння одягу та зачісок',
        'endpoints': {
            'clothes': {
                'upload': '/api/v1/clothes/upload/',
                'preview': '/api/v1/clothes/preview/',
                'process': '/api/v1/clothes/process/',
                'result': '/api/v1/clothes/result/'
            },
            'hair': {
                'upload': '/api/v1/hair/upload/',
                'preview': '/api/v1/hair/preview/',
                'process': '/api/v1/hair/process/',
                'result': '/api/v1/hair/result/'
            },
            'auth': {
                'login': '/api/v1/auth/login/',
                'refresh': '/api/v1/auth/refresh/',
                'me': '/api/v1/auth/me/'
            }
        }
    })


@extend_schema(
    operation_id='clothes_try_on',
    summary='Віртуальне приміряння одягу',
    description='Завантажує фото користувача та айтемів, обробляє через AI та повертає результат віртуального приміряння одягу. Підтримує JPEG, PNG, WebP, AVIF, HEIC формати.',
    tags=['Clothes Try-On'],
    request=UploadSerializer,
    responses={200: ResultResponseSerializer, 400: ErrorResponseSerializer, 500: ErrorResponseSerializer},
    examples=[
        OpenApiExample(
            'Try On Request',
            summary='Запит на приміряння',
            description='Приклад запиту з фото користувача та айтемів',
            value={
                'user_photo': 'user.jpg',
                'item_photos': ['item1.jpg', 'item2.jpg'],
                'prompt_text': 'Make it look natural and stylish'
            },
            request_only=True
        ),
        OpenApiExample(
            'Try On Result',
            summary='Результат приміряння',
            description='Приклад результату з URL-адресами оброблених фото',
            value={
                'result_urls': [
                    'http://localhost:8000/media/results/2025-09/ai_result_123.jpg'
                ]
            },
            response_only=True
        )
    ]
)
@api_view(['POST'])
@permission_classes([AllowAny])
@parser_classes([MultiPartParser, FormParser])
def clothes_try_on(request):
    """Віртуальне приміряння одягу - завантаження, обробка та результат в одному запиті"""
    serializer = UploadSerializer(data=request.data)
    
    if not serializer.is_valid():
        return Response(
            ErrorResponseSerializer({
                'detail': 'Validation failed',
                'field_errors': serializer.errors
            }).data,
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        # Отримуємо дані з валідованого serializer
        user_img_path = serializer.validated_data['user_photo']
        item_img_paths = serializer.validated_data['item_photos']
        user_prompt = serializer.validated_data.get('prompt_text', '')
        
        logger.info(f"Processing clothes try-on - User image: {user_img_path}")
        logger.info(f"Processing clothes try-on - Item images count: {len(item_img_paths)}")
        
        # Об'єднуємо всі фото айтемів в одне зображення
        try:
            combined_items_path = combine_item_images(item_img_paths)
            logger.info(f"Successfully combined {len(item_img_paths)} items into: {combined_items_path}")
        except Exception as e:
            logger.error(f"Failed to combine item images: {e}", exc_info=True)
            return Response(
                ErrorResponseSerializer({
                    'detail': 'Failed to process item images. Please try again.',
                    'code': 'COMBINE_ERROR'
                }).data,
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        prompt = build_prompt(user_prompt, '', False)
        all_result_paths = []
        
        if settings.USE_GEMINI:
            gemini_client = GeminiClient()
            try:
                result_path = gemini_client.try_on_item(user_img_path, combined_items_path, prompt, None)
                all_result_paths = [result_path]
                logger.info("Image successfully processed with Gemini!")
            except Exception as e:
                logger.warning(f"Error calling Gemini API ({e}). Using placeholder.", exc_info=True)
                # Fallback to placeholder in case of AI error
                try:
                    result_path = build_preview_placeholder(user_img_path, combined_items_path, user_prompt)
                    if result_path:
                        all_result_paths = [result_path]
                except Exception as placeholder_e:
                    logger.error(f"Failed to create placeholder: {placeholder_e}", exc_info=True)
        else:
            logger.info("AI integration is disabled or unavailable. Showing temporary preview.")
            try:
                result_path = build_preview_placeholder(user_img_path, combined_items_path, user_prompt)
                if result_path:
                    all_result_paths = [result_path]
            except Exception as placeholder_e:
                logger.error(f"Failed to create placeholder: {placeholder_e}", exc_info=True)
        
        if all_result_paths:
            result_urls = [os.path.join(settings.MEDIA_URL, path) for path in all_result_paths]
            serializer = ResultResponseSerializer({
                'result_urls': [request.build_absolute_uri(url) for url in result_urls]
            })
            return Response(serializer.data)
        else:
            return Response(
                ErrorResponseSerializer({
                    'detail': 'Failed to generate any result. Please try again.',
                    'code': 'PROCESS_ERROR'
                }).data,
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
            
    except Exception as e:
        logger.error(f"Error in clothes_try_on: {e}", exc_info=True)
        return Response(
            ErrorResponseSerializer({
                'detail': 'Internal server error during processing',
                'code': 'PROCESS_ERROR'
            }).data,
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )




# Hair try-on flow
@extend_schema(
    operation_id='hair_try_on',
    summary='Віртуальне приміряння зачісок',
    description='Завантажує фото користувача та зачісок, обробляє через AI та повертає результат віртуального приміряння зачісок. Підтримує JPEG, PNG, WebP, AVIF, HEIC формати.',
    tags=['Hair Try-On'],
    request=UploadSerializer,
    responses={200: ResultResponseSerializer, 400: ErrorResponseSerializer, 500: ErrorResponseSerializer},
    examples=[
        OpenApiExample(
            'Hair Try On Request',
            summary='Запит на приміряння зачісок',
            description='Приклад запиту з фото користувача та зачісок',
            value={
                'user_photo': 'user.jpg',
                'item_photos': ['hairstyle1.jpg', 'hairstyle2.jpg'],
                'prompt_text': 'Make it look natural and elegant'
            },
            request_only=True
        ),
        OpenApiExample(
            'Hair Try On Result',
            summary='Результат приміряння зачісок',
            description='Приклад результату з URL-адресами оброблених фото',
            value={
                'result_urls': [
                    'http://localhost:8000/media/results/2025-09/ai_result_123.jpg'
                ]
            },
            response_only=True
        )
    ]
)
@api_view(['POST'])
@permission_classes([AllowAny])
@parser_classes([MultiPartParser, FormParser])
def hair_try_on(request):
    """Віртуальне приміряння зачісок - завантаження, обробка та результат в одному запиті"""
    serializer = UploadSerializer(data=request.data)
    
    if not serializer.is_valid():
        return Response(
            ErrorResponseSerializer({
                'detail': 'Validation failed',
                'field_errors': serializer.errors
            }).data,
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        # Отримуємо дані з валідованого serializer
        user_img_path = serializer.validated_data['user_photo']
        item_img_paths = serializer.validated_data['item_photos']
        user_prompt = serializer.validated_data.get('prompt_text', '')
        
        logger.info(f"Processing hair try-on - User image: {user_img_path}")
        logger.info(f"Processing hair try-on - Item images count: {len(item_img_paths)}")
        
        # Об'єднуємо фото зачісок в одну сітку (для вибору найкращої)
        try:
            combined_items_path = combine_item_images(item_img_paths)
        except Exception as e:
            logger.error(f"Failed to combine hairstyle images: {e}", exc_info=True)
            return Response(
                ErrorResponseSerializer({
                    'detail': 'Не вдалося обробити фото зачісок. Спробуйте ще раз.',
                    'code': 'COMBINE_ERROR'
                }).data,
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        # Для зачісок не використовуємо маску за замовчуванням
        prompt = build_hair_prompt(user_prompt, '')
        all_result_paths = []
        
        if settings.USE_GEMINI:
            gemini_client = GeminiClient()
            try:
                result_path = gemini_client.try_on_item(user_img_path, combined_items_path, prompt, None)
                all_result_paths = [result_path]
                logger.info("Зображення успішно оброблено за допомогою Gemini!")
            except Exception as e:
                logger.warning(f"Error calling Gemini API for hair ({e}). Using placeholder.", exc_info=True)
                try:
                    result_path = build_preview_placeholder(user_img_path, combined_items_path, user_prompt)
                    if result_path:
                        all_result_paths = [result_path]
                except Exception as placeholder_e:
                    logger.error(f"Failed to create hair placeholder: {placeholder_e}", exc_info=True)
        else:
            logger.info("AI відключено. Показуємо тимчасовий прев'ю.")
            try:
                result_path = build_preview_placeholder(user_img_path, combined_items_path, user_prompt)
                if result_path:
                    all_result_paths = [result_path]
            except Exception as placeholder_e:
                logger.error(f"Failed to create hair placeholder: {placeholder_e}", exc_info=True)
        
        if all_result_paths:
            result_urls = [os.path.join(settings.MEDIA_URL, path) for path in all_result_paths]
            serializer = ResultResponseSerializer({
                'result_urls': [request.build_absolute_uri(url) for url in result_urls]
            })
            return Response(serializer.data)
        else:
            return Response(
                ErrorResponseSerializer({
                    'detail': 'Не вдалося згенерувати результат.',
                    'code': 'PROCESS_ERROR'
                }).data,
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
            
    except Exception as e:
        logger.error(f"Error in hair_try_on: {e}", exc_info=True)
        return Response(
            ErrorResponseSerializer({
                'detail': 'Internal server error during processing',
                'code': 'PROCESS_ERROR'
            }).data,
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    operation_id='google_api_key_retrieve',
    summary='Отримати GOOGLE_API_KEY для iOS клієнта',
    description=(
        'Повертає сконфігурований Google API key лише для авторизованих користувачів '
        'iOS-додатку. Потрібно передати заголовок `X-Key`'
    ),
    tags=['Config'],
    responses={
        200: OpenApiTypes.OBJECT,
        403: ErrorResponseSerializer,
        404: ErrorResponseSerializer,
        503: ErrorResponseSerializer,
    }
)
class GoogleApiKeyView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'google_api_key'

    def get(self, request):
        configured_key = settings.GOOGLE_API_KEY
        if not configured_key:
            logger.error("GOOGLE_API_KEY is not configured for the environment")
            return Response(
                ErrorResponseSerializer({
                    'detail': 'GOOGLE_API_KEY не налаштовано на сервері.',
                    'code': 'MISSING_CONFIGURATION'
                }).data,
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

        expected_client_id = "5~H3f@!k%>OnFHgqos5l1!z:EY3HQt"
        received_client_id = request.headers.get('X-Key')
        if expected_client_id and received_client_id != expected_client_id:
            logger.warning(
                "Rejected Google API key request due to invalid client id",
                extra={'user_id': getattr(request.user, 'id', None)}
            )
            return Response(
                ErrorResponseSerializer({
                    'detail': 'Недійсний клієнтський ідентифікатор.',
                    'code': 'INVALID_CLIENT'
                }).data,
                status=status.HTTP_403_FORBIDDEN
            )
            
        logger.info(
            "GOOGLE_API_KEY issued to authenticated client",
            extra={
                'user_id': getattr(request.user, 'id', None),
                'client_id': received_client_id or 'unknown'
            }
        )

        return Response({
            'google_api_key': configured_key
        })




