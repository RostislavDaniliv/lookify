from rest_framework import serializers
from django.core.files.uploadedfile import UploadedFile
from PIL import Image, ExifTags
import os
import uuid
from datetime import date
import logging
import base64
from django.conf import settings
from drf_spectacular.utils import extend_schema_serializer, OpenApiExample

# Import pillow-heif for HEIC support
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIC_SUPPORT = True
    logging.info("HEIC support enabled via pillow-heif")
except ImportError:
    HEIC_SUPPORT = False
    logging.warning("pillow-heif not installed. HEIC support disabled.")
except Exception as e:
    HEIC_SUPPORT = False
    logging.error(f"Failed to initialize HEIC support: {e}")

logger = logging.getLogger(__name__)


class ImageUploadSerializer(serializers.Serializer):
    """Serializer для завантаження зображень з валідацією"""
    
    def __init__(self, *args, **kwargs):
        self.min_width = kwargs.pop('min_width', 128)
        self.min_height = kwargs.pop('min_height', 128)
        self.max_size = kwargs.pop('max_size', 8 * 1024 * 1024)  # 8 MB
        super().__init__(*args, **kwargs)
    
    def validate_image(self, file, field_name):
        """Валідація зображення з обробкою та збереженням"""
        allowed_mime_types = ['image/mpo', 'image/jpg', 'image/jpeg', 'image/png', 'image/webp', 'image/avif']
        
        # Add HEIC support if available
        if HEIC_SUPPORT:
            allowed_mime_types.extend(['image/heic', 'image/heif'])
            logger.info("HEIC support is enabled, allowing HEIC/HEIF files")
        else:
            logger.warning("HEIC support is disabled")

        # Check file extension for HEIC files
        file_extension = file.name.lower().split('.')[-1] if '.' in file.name else ''
        is_heic_file = file_extension in ['heic', 'heif']
        
        logger.info(f"Validating image: {file.name}, size: {file.size}, type: {file.content_type}, extension: {file_extension}, is_heic: {is_heic_file}")

        if file.size > self.max_size:
            raise serializers.ValidationError(f"File too large. Maximum size: {self.max_size / (1024 * 1024):.0f}MB.")
        
        print(file.content_type)
        if file.content_type not in allowed_mime_types:
            # Special handling for HEIC files
            if is_heic_file and HEIC_SUPPORT:
                logger.info(f"HEIC file detected by extension: {file.name}, attempting to process despite MIME type: {file.content_type}")
                # Continue processing - Pillow with pillow-heif should handle it
            elif is_heic_file and not HEIC_SUPPORT:
                raise serializers.ValidationError("HEIC files are not supported on this server. Please convert to JPEG or PNG.")
            else:
                error_msg = "Unsupported file format. Allowed: JPEG, PNG, WebP, AVIF"
                if HEIC_SUPPORT:
                    error_msg += ", HEIC"
                error_msg += "."
                raise serializers.ValidationError(error_msg)

        try:
            img = Image.open(file)
            img.verify()
            # Повторно відкриваємо зображення після verify(), так як воно закриває файл
            img = Image.open(file)
            logger.info(f"Successfully opened image: {file.name}, format: {img.format}, mode: {img.mode}")
        except Exception as e:
            logger.error(f"Error opening image {file.name}: {str(e)}")
            
            # Special handling for HEIC files
            if is_heic_file:
                if not HEIC_SUPPORT:
                    raise serializers.ValidationError("HEIC files are not supported on this server. Please convert to JPEG or PNG.")
                else:
                    # Try alternative HEIC processing
                    try:
                        logger.info(f"Attempting alternative HEIC processing for {file.name}")
                        # Reset file pointer
                        file.seek(0)
                        # Try to open with explicit HEIC support
                        img = self._try_heic_processing(file)
                        if img:
                            logger.info(f"Alternative HEIC processing successful for {file.name}")
                        else:
                            raise Exception("Alternative HEIC processing failed")
                    except Exception as heic_error:
                        logger.error(f"Alternative HEIC processing failed for {file.name}: {str(heic_error)}")
                        raise serializers.ValidationError(f"HEIC file processing failed. Please try converting to JPEG or PNG. Error: {str(e)}")
            else:
                raise serializers.ValidationError(f"File is not a valid image or is corrupted: {str(e)}")

        width, height = img.size
        if width < self.min_width or height < self.min_height:
            raise serializers.ValidationError(f"Minimum resolution: {self.min_width}x{self.min_height}px.")

        # Auto-orientation by EXIF
        try:
            for orientation in ExifTags.TAGS.keys():
                if ExifTags.TAGS[orientation] == 'Orientation':
                    break
            exif = dict(img._getexif().items())

            if exif[orientation] == 3:
                img = img.rotate(180, expand=True)
            elif exif[orientation] == 6:
                img = img.rotate(270, expand=True)
            elif exif[orientation] == 8:
                img = img.rotate(90, expand=True)
        except (AttributeError, KeyError, IndexError):
            # This happens if the image has no EXIF data or orientation.
            pass

        # Downscale if longer side > 3000px
        max_dimension = 3000
        if max(img.size) > max_dimension:
            ratio = max_dimension / max(img.size)
            new_size = tuple(int(x * ratio) for x in img.size)
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        # Remove EXIF/metadata before saving
        img.info = {}

        # Save the file and return the relative path
        relative_path = self._save_image(img, file.content_type, file.name)
        logger.info(f"Saved image {field_name} to: {relative_path}")
        return relative_path

    def _save_image(self, img, content_type, filename=None):
        """Збереження зображення на диск"""
        today = date.today()
        upload_dir = os.path.join(settings.MEDIA_ROOT, 'uploads', str(today.year), str(today.month))
        os.makedirs(upload_dir, exist_ok=True)

        ext = 'jpeg'
        if content_type == 'image/png':
            ext = 'png'
        elif content_type == 'image/webp':
            ext = 'webp'
        elif content_type == 'image/avif':
            ext = 'avif'
        elif content_type in ['image/heic', 'image/heif']:
            ext = 'jpeg'  # Convert HEIC to JPEG for storage
            logger.info(f"Converting HEIC file to JPEG for storage")
        elif filename and filename.lower().endswith(('.heic', '.heif')):
            ext = 'jpeg'  # Convert HEIC to JPEG for storage
            logger.info(f"Converting HEIC file to JPEG for storage: {filename}")
        
        # Preserve alpha for PNG/WebP/AVIF
        if (ext == 'png' or ext == 'webp' or ext == 'avif') and img.mode != 'RGBA':
            img = img.convert('RGBA')

        file_name = f"{uuid.uuid4()}.{ext}"
        full_path = os.path.join(upload_dir, file_name)

        if ext == 'jpeg':
            img.save(full_path, format='JPEG', quality=90)
        elif ext == 'avif':
            img.save(full_path, format='AVIF', quality=90)
        else:
            img.save(full_path, format=ext.upper())

        relative_path = os.path.relpath(full_path, settings.MEDIA_ROOT)
        logger.info(f"Saved file to: {full_path}, relative path: {relative_path}")
        return relative_path

    def _try_heic_processing(self, file):
        """Alternative method to process HEIC files"""
        try:
            if HEIC_SUPPORT:
                # Try to re-register HEIC opener
                from pillow_heif import register_heif_opener
                register_heif_opener()
                
                # Try to open the file again
                img = Image.open(file)
                img.verify()
                # Reopen after verify
                file.seek(0)
                img = Image.open(file)
                return img
            return None
        except Exception as e:
            logger.error(f"Alternative HEIC processing failed: {str(e)}")
            return None


class UserPhotoSerializer(ImageUploadSerializer):
    """Serializer для завантаження фото користувача"""
    user_photo = serializers.ImageField(required=True)
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, min_width=256, min_height=256, **kwargs)
    
    def validate_user_photo(self, value):
        return self.validate_image(value, "user_photo")


class ItemPhotoSerializer(ImageUploadSerializer):
    """Serializer для завантаження фото айтемів"""
    item_photos = serializers.ListField(
        child=serializers.ImageField(),
        required=True,
        max_length=3,
        min_length=1
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, min_width=128, min_height=128, **kwargs)
    
    def validate_item_photos(self, value):
        if len(value) > 3:
            raise serializers.ValidationError("Maximum 3 item photos allowed.")
        
        processed_paths = []
        for i, photo in enumerate(value):
            try:
                result_path = self.validate_image(photo, f"item_photo_{i}")
                if result_path:
                    processed_paths.append(result_path)
                    logger.info(f"Successfully processed item photo {i+1}: {result_path}")
                else:
                    logger.warning(f"Item photo {i+1} processing returned None")
            except Exception as e:
                logger.error(f"Error processing item photo {i+1}: {e}")
                raise serializers.ValidationError(f"Error processing item photo {i+1}: {str(e)}")
        
        return processed_paths


@extend_schema_serializer(
    examples=[
        OpenApiExample(
            'Upload Payload',
            summary='Приклад запиту на завантаження',
            description='Поля форми з файлами та опціональним текстом',
            value={
                'user_photo': 'user.jpg',
                'item_photos': ['item1.jpg', 'item2.jpg'],
                'prompt_text': 'Додаткові побажання користувача'
            },
            request_only=True
        )
    ]
)
class UploadSerializer(serializers.Serializer):
    """Основний serializer для завантаження фото користувача та айтемів"""
    user_photo = serializers.ImageField(
        required=True,
        help_text="Фото користувача для приміряння. Підтримує JPEG, PNG, WebP, AVIF, HEIC. Максимум 8MB, мінімум 256x256px."
    )
    item_photos = serializers.ListField(
        child=serializers.ImageField(),
        required=True,
        max_length=3,
        min_length=1,
        help_text="Фото айтемів для приміряння (1-3 штуки). Підтримує JPEG, PNG, WebP, AVIF, HEIC. Максимум 8MB кожне, мінімум 128x128px."
    )
    prompt_text = serializers.CharField(
        required=False, 
        allow_blank=True, 
        max_length=1000,
        help_text="Додаткові побажання користувача для обробки (опціонально, максимум 1000 символів)"
    )
    
    def validate(self, data):
        """Валідація всіх полів разом"""
        # Валідуємо user_photo
        user_photo = data.get('user_photo')
        if user_photo:
            user_serializer = UserPhotoSerializer(data={'user_photo': user_photo})
            if user_serializer.is_valid():
                data['user_photo'] = user_serializer.validated_data['user_photo']
            else:
                raise serializers.ValidationError({'user_photo': user_serializer.errors['user_photo']})
        
        # Валідуємо item_photos
        item_photos = data.get('item_photos')
        if item_photos:
            item_serializer = ItemPhotoSerializer(data={'item_photos': item_photos})
            if item_serializer.is_valid():
                data['item_photos'] = item_serializer.validated_data['item_photos']
            else:
                raise serializers.ValidationError({'item_photos': item_serializer.errors['item_photos']})
        
        return data


@extend_schema_serializer(
    examples=[
        OpenApiExample(
            'Process Payload',
            summary='Приклад запиту на обробку',
            description='Опціональні параметри обробки',
            value={
                'additional_prompt': 'Make it look natural and stylish',
                'selection_mask': 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA...'
            },
            request_only=True
        )
    ]
)
class ProcessSerializer(serializers.Serializer):
    """Serializer для обробки зображень з додатковими параметрами"""
    selection_mask = serializers.CharField(
        required=False, 
        allow_blank=True,
        help_text="Маска вибору в форматі data URI (base64 encoded PNG). Опціонально для точного вибору області обробки."
    )
    additional_prompt = serializers.CharField(
        required=False, 
        allow_blank=True, 
        max_length=1000,
        help_text="Додаткові інструкції для AI обробки (опціонально, максимум 1000 символів)"
    )
    
    def validate_selection_mask(self, value):
        """Валідація маски вибору"""
        if not value:
            return value
        
        try:
            # Перевіряємо, чи це валідний base64
            if ',' in value:
                header, encoded = value.split(',', 1)
                if not header.startswith('data:image/'):
                    raise serializers.ValidationError("Invalid mask format. Expected data URI.")
                # Декодуємо base64
                decoded = base64.b64decode(encoded)
                # Перевіряємо, чи це валідне зображення
                from io import BytesIO
                img = Image.open(BytesIO(decoded))
                img.verify()
            else:
                raise serializers.ValidationError("Invalid mask format. Expected data URI.")
        except Exception as e:
            raise serializers.ValidationError(f"Invalid mask format: {str(e)}")
        
        return value


@extend_schema_serializer(
    examples=[
        OpenApiExample(
            'Preview Response',
            summary='Приклад відповіді прев’ю',
            value={
                'user_photo_url': 'http://localhost:8000/media/uploads/2025/9/user_photo.jpg',
                'item_photo_urls': [
                    'http://localhost:8000/media/uploads/2025/9/item_1.jpg',
                    'http://localhost:8000/media/uploads/2025/9/item_2.jpg'
                ]
            },
            response_only=True
        )
    ]
)
class PreviewResponseSerializer(serializers.Serializer):
    """Serializer для відповіді preview з URL-адресами завантажених фото"""
    user_photo_url = serializers.URLField(help_text="URL-адреса фото користувача")
    item_photo_urls = serializers.ListField(
        child=serializers.URLField(),
        help_text="Список URL-адрес фото айтемів"
    )


@extend_schema_serializer(
    examples=[
        OpenApiExample(
            'Result Response',
            summary='Приклад відповіді результатів',
            value={
                'result_urls': [
                    'http://localhost:8000/media/results/2025-09/ai_result_123.jpg',
                    'http://localhost:8000/media/results/2025-09/ai_result_456.jpg'
                ]
            },
            response_only=True
        )
    ]
)
class ResultResponseSerializer(serializers.Serializer):
    """Serializer для відповіді result з URL-адресами оброблених фото"""
    result_urls = serializers.ListField(
        child=serializers.URLField(),
        help_text="Список URL-адрес оброблених фото з результатами"
    )


@extend_schema_serializer(
    examples=[
        OpenApiExample(
            'Validation Error',
            summary='Помилки валідації',
            value={
                'detail': 'Validation failed',
                'field_errors': {
                    'user_photo': ['File too large. Maximum size: 8MB.'],
                    'item_photos': ['Maximum 3 item photos allowed.']
                }
            },
            response_only=True
        ),
        OpenApiExample(
            'Internal Error',
            summary='Внутрішня помилка',
            value={
                'detail': 'Internal server error during upload',
                'code': 'UPLOAD_ERROR'
            },
            response_only=True
        )
    ]
)
class ErrorResponseSerializer(serializers.Serializer):
    """Serializer для помилок з детальною інформацією"""
    detail = serializers.CharField(help_text="Детальний опис помилки")
    code = serializers.CharField(required=False, help_text="Код помилки для програмної обробки")
    field_errors = serializers.DictField(required=False, help_text="Помилки валідації по полях")

