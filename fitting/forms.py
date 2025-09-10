
from django import forms
from django.conf import settings
from PIL import Image, ExifTags
import os
import uuid
from datetime import date
import logging
import pillow_heif

logger = logging.getLogger(__name__)

# Реєструємо HEIF/HEIC підтримку
pillow_heif.register_heif_opener()

class MultipleFileInput(forms.FileInput):
    def __init__(self, attrs=None):
        if attrs is None:
            attrs = {}
        attrs['multiple'] = 'multiple'
        super().__init__(attrs)

class MultipleImageField(forms.FileField):
    def __init__(self, *args, **kwargs):
        self.max_files = kwargs.pop('max_files', 3)
        super().__init__(*args, **kwargs)
        self.widget.attrs.update({'multiple': 'multiple'})

    def to_python(self, data):
        logger.info(f"MultipleImageField.to_python called with data type: {type(data)}")
        if data in (None, ''):
            logger.info("MultipleImageField: data is None or empty")
            return None
        
        # Django передає кілька файлів як список
        if isinstance(data, list):
            logger.info(f"MultipleImageField: received list with {len(data)} items")
            for i, item in enumerate(data):
                logger.info(f"MultipleImageField: list[{i}] type: {type(item)}, name: {getattr(item, 'name', 'no name')}")
            return data
        
        # Якщо це не список, обгортаємо в список
        logger.info(f"MultipleImageField: received single item, wrapping in list")
        logger.info(f"MultipleImageField: single item type: {type(data)}, name: {getattr(data, 'name', 'no name')}")
        return [data] if data else []

    def value_from_datadict(self, data, files, name):
        logger.info(f"MultipleImageField.value_from_datadict called for {name}")
        logger.info(f"MultipleImageField: files type: {type(files)}")
        logger.info(f"MultipleImageField: files keys: {list(files.keys()) if hasattr(files, 'keys') else 'no keys'}")
        
        if hasattr(files, 'getlist'):
            # Django передає кілька файлів через getlist
            file_list = files.getlist(name)
            logger.info(f"MultipleImageField: getlist returned {len(file_list)} files")
            for i, file in enumerate(file_list):
                logger.info(f"MultipleImageField: file[{i}]: {file.name if hasattr(file, 'name') else 'no name'}")
            return file_list
        elif name in files:
            # Якщо getlist недоступний, перевіряємо чи це список
            file_data = files[name]
            logger.info(f"MultipleImageField: files[{name}] type: {type(file_data)}")
            if isinstance(file_data, list):
                logger.info(f"MultipleImageField: files[name] is list with {len(file_data)} items")
                return file_data
            else:
                logger.info(f"MultipleImageField: files[name] is single item")
                return [file_data]
        else:
            logger.info(f"MultipleImageField: {name} not found in files")
        return None

    def bound_data(self, data, initial):
        logger.info(f"MultipleImageField.bound_data called with data type: {type(data)}")
        if data in (None, ''):
            return initial
        return data

    def has_changed(self, initial, data):
        if data is None:
            return False
        if initial is None:
            return True
        return data != initial

    def bound_data(self, data, initial):
        if data in (None, ''):
            return initial
        return data

    def validate(self, value):
        super().validate(value)
        if value is None:
            return
        if len(value) > self.max_files:
            raise forms.ValidationError(f"Maximum {self.max_files} files allowed.")

class UploadForm(forms.Form):
    user_photo = forms.ImageField(required=True, label="User Photo",
                                  help_text="JPEG, PNG, WebP, AVIF or HEIC. Max. 8MB. Min. resolution 256x256.")
    item_photo = MultipleImageField(required=True, label="Item Photos (up to 3)",
                                  help_text="JPEG, PNG, WebP, AVIF or HEIC. Max. 8MB each. Min. resolution 128x128.",
                                  max_files=3)
    prompt_text = forms.CharField(required=False, label="Additional Requests (optional)",
                                  help_text="Describe what you would like to try on, or any other details.",
                                  widget=forms.Textarea(attrs={'rows': 3}))

    def clean(self):
        cleaned_data = super().clean()
        user_photo = cleaned_data.get('user_photo')
        item_photo = cleaned_data.get('item_photo')

        if user_photo:
            result_path = self._validate_and_process_image(user_photo, "user_photo", 256, 256)
            if result_path:
                cleaned_data['user_photo'] = result_path
                logger.info(f"User photo saved to: {result_path}")
            else:
                logger.error("User photo processing failed")

        # Обробляємо кілька файлів item_photo
        if item_photo:
            # Отримуємо всі файли з request.FILES
            from django.core.files.uploadedfile import UploadedFile
            
            # Перевіряємо, чи це список файлів
            if isinstance(item_photo, list):
                item_photos = item_photo
            else:
                # Якщо це один файл, обгортаємо в список
                item_photos = [item_photo]
            
            logger.info(f"Processing {len(item_photos)} item photos")
            processed_paths = []
            
            for i, photo in enumerate(item_photos):
                try:
                    logger.info(f"Processing item photo {i+1}: {photo.name}")
                    result_path = self._validate_and_process_image(photo, f"item_photo_{i}", 128, 128)
                    if result_path:
                        processed_paths.append(result_path)
                        logger.info(f"Successfully processed item photo {i+1}: {result_path}")
                    else:
                        logger.warning(f"Item photo {i+1} processing returned None")
                except Exception as e:
                    logger.error(f"Error processing item photo {i+1}: {e}")
                    self.add_error('item_photo', f"Error processing item photo {i+1}: {str(e)}")
            
            cleaned_data['item_photo'] = processed_paths
            logger.info(f"Final processed paths: {processed_paths}")

        return cleaned_data

    def _validate_and_process_image(self, file, field_name, min_width, min_height):
        max_size = 8 * 1024 * 1024  # 8 MB
        allowed_mime_types = ['image/jpeg', 'image/png', 'image/webp', 'image/avif', 'image/heic', 'image/heif']

        logger.info(f"Validating image: {file.name}, size: {file.size}, type: {file.content_type}")

        if file.size > max_size:
            self.add_error(field_name, f"File too large. Maximum size: {max_size / (1024 * 1024):.0f}MB.")
            return None

        if file.content_type not in allowed_mime_types:
            self.add_error(field_name, "Unsupported file format. Allowed: JPEG, PNG, WebP, AVIF, HEIC.")
            return None # No sense in processing further if format is incorrect

        try:
            img = Image.open(file)
            img.verify()
            # Повторно відкриваємо зображення після verify(), так як воно закриває файл
            img = Image.open(file)
        except Exception:
            self.add_error(field_name, "File is not a valid image or is corrupted.")
            return None

        width, height = img.size
        if width < min_width or height < min_height:
            self.add_error(field_name, f"Minimum resolution: {min_width}x{min_height}px.")
            return None

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

        # Downscale if longer side > 3000px (для HEIC файлів використовуємо менший ліміт)
        max_dimension = 2500 if file.content_type in ['image/heic', 'image/heif'] else 3000
        if max(img.size) > max_dimension:
            ratio = max_dimension / max(img.size)
            new_size = tuple(int(x * ratio) for x in img.size)
            img = img.resize(new_size, Image.Resampling.LANCZOS)
            logger.info(f"Resized {file.content_type} image from {img.size} to {new_size}")

        # Remove EXIF/metadata before saving
        img.info = {}

        # Save the file and return the relative path
        relative_path = self._save_image(img, file.content_type)
        logger.info(f"Saved image {field_name} to: {relative_path}")
        return relative_path

    def _save_image(self, img, content_type):
        today = date.today()
        upload_dir = os.path.join(settings.MEDIA_ROOT, 'uploads', str(today.year), str(today.month))
        os.makedirs(upload_dir, exist_ok=True)

        # HEIC/HEIF файли завжди конвертуємо в JPEG для кращої сумісності
        if content_type in ['image/heic', 'image/heif']:
            ext = 'jpeg'
            # Конвертуємо в RGB для JPEG
            if img.mode != 'RGB':
                img = img.convert('RGB')
        else:
            ext = 'jpeg'
            if content_type == 'image/png':
                ext = 'png'
            elif content_type == 'image/webp':
                ext = 'webp'
            elif content_type == 'image/avif':
                ext = 'avif'
            
            # Preserve alpha for PNG/WebP/AVIF
            if (ext == 'png' or ext == 'webp' or ext == 'avif') and img.mode != 'RGBA':
                img = img.convert('RGBA')

        file_name = f"{uuid.uuid4()}.{ext}"
        full_path = os.path.join(upload_dir, file_name)

        # Зберігаємо з оптимізацією якості
        if ext == 'jpeg':
            # Для HEIC файлів використовуємо трохи нижчу якість для зменшення розміру
            quality = 85 if content_type in ['image/heic', 'image/heif'] else 90
            img.save(full_path, format='JPEG', quality=quality, optimize=True)
        elif ext == 'avif':
            img.save(full_path, format='AVIF', quality=90)
        else:
            img.save(full_path, format=ext.upper())

        relative_path = os.path.relpath(full_path, settings.MEDIA_ROOT)
        logger.info(f"Saved file to: {full_path}, relative path: {relative_path}")
        return relative_path


class ProcessForm(forms.Form):
    selection_mask = forms.CharField(required=False)
    additional_prompt = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3}))
