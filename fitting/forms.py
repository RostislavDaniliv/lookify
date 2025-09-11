
from django import forms
from django.conf import settings
from PIL import Image, ExifTags
import os
import uuid
from datetime import date
import logging
import pillow_heif
from django.core.files.uploadedfile import InMemoryUploadedFile
from .utils.image_processing import normalize_to_webp

logger = logging.getLogger(__name__)

# Реєструємо HEIF/HEIC підтримку
pillow_heif.register_heif_opener()

class MultipleFileInput(forms.FileInput):
    def __init__(self, attrs=None):
        if attrs is None:
            attrs = {}
        attrs['multiple'] = 'multiple'
        attrs['accept'] = '.jpg,.jpeg,.png,.webp,.heic,.heif,.avif'
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

    def clean(self, data, initial=None):
        if data in (None, ''):
            return None
        files = data if isinstance(data, list) else [data]
        if len(files) > self.max_files:
            raise forms.ValidationError(f"Maximum {self.max_files} files allowed.")
        return files

class UploadForm(forms.Form):
    # ВАЖЛИВО: FileField замість ImageField, щоб не валідовувати HEIC через Pillow до нашої конвертації
    user_photo = forms.FileField(required=True, label="User Photo",
                                  help_text="JPEG, PNG, WebP, HEIC/HEIF/AVIF. Max. 10MB. Min. 256x256.")
    item_photo = MultipleImageField(required=True, label="Item Photos (up to 3)",
                                  help_text="JPEG, PNG, WebP, HEIC/HEIF/AVIF. Max. 10MB each. Min. 128x128.",
                                  max_files=3)
    prompt_text = forms.CharField(required=False, label="Additional Requests (optional)",
                                  help_text="Describe what you would like to try on, or any other details.",
                                  widget=forms.Textarea(attrs={'rows': 3}))

    def clean(self):
        cleaned_data = super().clean()
        user_photo = cleaned_data.get('user_photo')
        item_photo = cleaned_data.get('item_photo')

        if user_photo:
            # Перевірка дозволених розширень
            allowed_exts = {"jpg","jpeg","png","webp","heic","heif","avif"}
            name_lower = user_photo.name.lower()
            if '.' not in name_lower or name_lower.rsplit('.',1)[1] not in allowed_exts:
                self.add_error('user_photo', "Unsupported file extension. Allowed: jpg, jpeg, png, webp, heic, heif, avif.")
                return cleaned_data
            if user_photo.size > 10 * 1024 * 1024:
                self.add_error('user_photo', "File too large. Maximum size: 10MB.")
                return cleaned_data
            try:
                processed_user = normalize_to_webp(user_photo, max_px=2048, quality=82)
                cleaned_data['user_photo'] = processed_user
            except Exception as e:
                logger.exception(f"Error processing user_photo '{getattr(user_photo,'name',None)}': {e}")
                self.add_error('user_photo', f"Error processing user photo: {str(e)}")
                return cleaned_data

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
            processed_files = []
            
            for i, photo in enumerate(item_photos):
                try:
                    logger.info(f"Processing item photo {i+1}: {photo.name}")
                    # Перевірка дозволених розширень для айтемів
                    allowed_exts = {"jpg","jpeg","png","webp","heic","heif","avif"}
                    name_lower = photo.name.lower()
                    if '.' not in name_lower or name_lower.rsplit('.',1)[1] not in allowed_exts:
                        self.add_error('item_photo', f"Unsupported file extension for {photo.name}. Allowed: jpg, jpeg, png, webp, heic, heif, avif.")
                        continue

                    if photo.size > 10 * 1024 * 1024:
                        self.add_error('item_photo', f"File {photo.name} too large. Max 10MB.")
                        continue
                    processed_file = normalize_to_webp(photo, max_px=2048, quality=82)
                    processed_files.append(processed_file)
                    logger.info(f"Successfully processed item photo {i+1}: {getattr(processed_file, 'name', 'memfile')}\n")
                except Exception as e:
                    logger.exception(f"Error processing item photo {i+1} ('{getattr(photo,'name',None)}'): {e}")
                    self.add_error('item_photo', f"Error processing item photo {i+1}: {str(e)}")
            
            cleaned_data['item_photo'] = processed_files
            logger.info(f"Final processed files: {[f.name for f in processed_files]}")

        return cleaned_data

    def clean_user_photo(self):
        file = self.cleaned_data.get('user_photo')
        if file and hasattr(file, 'size') and file.size > 10 * 1024 * 1024:
            raise forms.ValidationError("File too large. Maximum size: 10MB.")
        return file

    # Старі внутрішні методи збереження/валідації замінено на normalize_to_webp


class ProcessForm(forms.Form):
    selection_mask = forms.CharField(required=False)
    additional_prompt = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3}))
