from io import BytesIO
from PIL import Image, ImageOps
import pillow_heif
from django.core.files.uploadedfile import InMemoryUploadedFile
try:
    import magic as magic_lib  # python-magic
except Exception:  # optional
    magic_lib = None


def normalize_to_webp(uploaded_file, max_px=2048, quality=82):
    pillow_heif.register_heif_opener()

    # Read bytes and try to detect mime, also ensures we can seek
    uploaded_file.seek(0)
    file_bytes = uploaded_file.read()
    uploaded_file.seek(0)

    detected_mime = None
    if magic_lib is not None:
        try:
            detected_mime = magic_lib.from_buffer(file_bytes, mime=True)
        except Exception:
            detected_mime = None

    image = None
    try:
        image = Image.open(BytesIO(file_bytes))
    except Exception:
        # Fallback for HEIC/HEIF when Pillow fails
        try:
            heif_img = pillow_heif.open_heif(BytesIO(file_bytes))
            image = heif_img  # already PIL.Image.Image
        except Exception as _e:
            # Re-raise the original behavior
            raise

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


