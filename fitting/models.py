from django.db import models
from django.core.validators import FileExtensionValidator


class UploadedImage(models.Model):
    image = models.ImageField(
        upload_to='uploads/%Y/%m',
        validators=[FileExtensionValidator(allowed_extensions=[
            'jpg', 'jpeg', 'png', 'webp', 'heic', 'heif'
        ])]
    )
    created_at = models.DateTimeField(auto_now_add=True)

# Create your models here.
