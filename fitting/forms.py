
from django import forms
from django.conf import settings
from PIL import Image, ExifTags
import os
import uuid
from datetime import date
import logging

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

def check_heic_support():
    """Check and log HEIC support status"""
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
        
        # Test with a simple HEIC file if possible
        logger.info("HEIC support check: pillow-heif imported and registered successfully")
        return True
    except ImportError as e:
        logger.error(f"HEIC support check failed - ImportError: {e}")
        return False
    except Exception as e:
        logger.error(f"HEIC support check failed - Exception: {e}")
        return False

# Log HEIC support status on module load
logger.info(f"HEIC support status: {HEIC_SUPPORT}")
if HEIC_SUPPORT:
    check_heic_support()

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
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Динамічно оновлюємо help_text залежно від підтримки HEIC
        heic_text = ", HEIC" if HEIC_SUPPORT else ""
        self.fields['user_photo'].help_text = f"JPEG, PNG, WebP, AVIF{heic_text}. Max. 8MB. Min. resolution 256x256."
        self.fields['item_photo'].help_text = f"JPEG, PNG, WebP, AVIF{heic_text}. Max. 8MB each. Min. resolution 128x128."
    
    user_photo = MultipleImageField(required=True, label="User Photo",
                                   help_text="JPEG, PNG, WebP, AVIF or HEIC. Max. 8MB. Min. resolution 256x256.",
                                   max_files=1)
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
            # user_photo тепер список з одного елементу
            if isinstance(user_photo, list) and len(user_photo) > 0:
                result_path = self._validate_and_process_image(user_photo[0], "user_photo", 256, 256)
            else:
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
        allowed_mime_types = ['image/jpeg', 'image/png', 'image/webp', 'image/avif']
        
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

        if file.size > max_size:
            self.add_error(field_name, f"File too large. Maximum size: {max_size / (1024 * 1024):.0f}MB.")
            return None

        if file.content_type not in allowed_mime_types:
            # Special handling for HEIC files
            if is_heic_file and HEIC_SUPPORT:
                logger.info(f"HEIC file detected by extension: {file.name}, attempting to process despite MIME type: {file.content_type}")
                # Continue processing - Pillow with pillow-heif should handle it
            elif is_heic_file and not HEIC_SUPPORT:
                self.add_error(field_name, "HEIC files are not supported on this server. Please convert to JPEG or PNG.")
                return None
            else:
                error_msg = "Unsupported file format. Allowed: JPEG, PNG, WebP, AVIF"
                if HEIC_SUPPORT:
                    error_msg += ", HEIC"
                error_msg += "."
                self.add_error(field_name, error_msg)
                return None

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
                    self.add_error(field_name, "HEIC files are not supported on this server. Please convert to JPEG or PNG.")
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
                        self.add_error(field_name, f"HEIC file processing failed. Please try converting to JPEG or PNG. Error: {str(e)}")
                return None
            else:
                self.add_error(field_name, f"File is not a valid image or is corrupted: {str(e)}")
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


class ProcessForm(forms.Form):
    selection_mask = forms.CharField(required=False)
    additional_prompt = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3}))
