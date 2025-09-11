from io import BytesIO
from PIL import Image, ImageOps
import pillow_heif
from django.core.files.uploadedfile import InMemoryUploadedFile


def normalize_to_webp(uploaded_file, max_px=2048, quality=82):
    pillow_heif.register_heif_opener()
    image = Image.open(uploaded_file)

    try:
        image = ImageOps.exif_transpose(image)
    except Exception:
        pass

    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGB")

    width, height = image.size
    long_edge = max(width, height)
    if long_edge > max_px:
        scale = max_px / float(long_edge)
        new_size = (int(width * scale), int(height * scale))
        image = image.resize(new_size, Image.Resampling.LANCZOS)

    output_io = BytesIO()
    image.save(output_io, format="WEBP", quality=quality, method=6)
    output_io.seek(0)

    memfile = InMemoryUploadedFile(
        file=output_io,
        field_name=None,
        name=(uploaded_file.name.rsplit('.', 1)[0] + '.webp'),
        content_type='image/webp',
        size=output_io.getbuffer().nbytes,
        charset=None,
    )

    return memfile


