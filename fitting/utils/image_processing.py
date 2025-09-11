from io import BytesIO
from PIL import Image, ImageOps
import pillow_heif
from django.core.files.uploadedfile import InMemoryUploadedFile
import logging
try:
    import magic as magic_lib  # python-magic
except Exception:  # optional
    magic_lib = None

# Optional HEIC fallback via pyheif
try:
    import pyheif  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    pyheif = None


def normalize_to_webp(uploaded_file, max_px=2048, quality=82):
    logger = logging.getLogger('fitting.image_processing')
    pillow_heif.register_heif_opener()
    logger.info(f"normalize_to_webp: start name={getattr(uploaded_file,'name',None)} size={getattr(uploaded_file,'size',None)} type={getattr(uploaded_file,'content_type',None)}")

    # Read bytes and try to detect mime, also ensures we can seek
    uploaded_file.seek(0)
    file_bytes = uploaded_file.read()
    uploaded_file.seek(0)
    logger.info(f"normalize_to_webp: read bytes len={len(file_bytes)}")

    detected_mime = None
    if magic_lib is not None:
        try:
            detected_mime = magic_lib.from_buffer(file_bytes, mime=True)
            logger.info(f"normalize_to_webp: magic detected_mime={detected_mime}")
        except Exception:
            detected_mime = None

    image = None
    try:
        image = Image.open(BytesIO(file_bytes))
        logger.info(f"normalize_to_webp: PIL opened format={getattr(image,'format',None)} mode={image.mode} size={image.size}")
    except Exception:
        # Fallbacks for HEIC/HEIF when Pillow fails
        try:
            heif_img = pillow_heif.open_heif(BytesIO(file_bytes), convert_hdr_to_8bit=True)
            image = heif_img  # already PIL.Image.Image
            logger.info(f"normalize_to_webp: opened via pillow_heif/open_heif size={image.size} mode={image.mode}")
        except Exception as e_open:
            logger.warning(f"normalize_to_webp: open_heif failed: {e_open}")
            try:
                heif_frame = pillow_heif.read_heif(file_bytes, convert_hdr_to_8bit=True)
                image = Image.frombytes(
                    heif_frame.mode,
                    heif_frame.size,
                    heif_frame.data,
                    "raw",
                )
                logger.info(f"normalize_to_webp: opened via pillow_heif/read_heif size={image.size} mode={image.mode}")
            except Exception as e_pillow_heif_read:
                logger.warning(f"normalize_to_webp: pillow_heif/read_heif failed: {e_pillow_heif_read}")
                # Final fallback via pyheif, which sometimes handles tricky HEICs
                if pyheif is not None:
                    try:
                        heif = pyheif.read_heif(file_bytes)
                        # Some HEICs may contain auxiliary images; pyheif returns primary frame
                        image = Image.frombytes(
                            heif.mode,
                            heif.size,
                            heif.data,
                            "raw",
                            heif.mode,
                            heif.stride,
                        )
                        logger.info(f"normalize_to_webp: opened via pyheif size={image.size} mode={image.mode}")
                    except Exception as e_pyheif:
                        logger.exception("normalize_to_webp: failed to open image via PIL, pillow_heif and pyheif fallbacks")
                        raise e_pyheif
                else:
                    logger.exception("normalize_to_webp: failed to open image via PIL and pillow_heif fallbacks (pyheif not installed)")
                    raise

    try:
        image = ImageOps.exif_transpose(image)
    except Exception:
        pass

    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGB")
        logger.info(f"normalize_to_webp: converted mode to RGB")

    width, height = image.size
    long_edge = max(width, height)
    if long_edge > max_px:
        scale = max_px / float(long_edge)
        new_size = (int(width * scale), int(height * scale))
        logger.info(f"normalize_to_webp: resizing from {image.size} to {new_size}")
        image = image.resize(new_size, Image.Resampling.LANCZOS)

    output_io = BytesIO()
    image.save(output_io, format="WEBP", quality=quality, method=6)
    output_io.seek(0)
    logger.info(f"normalize_to_webp: saved to WEBP quality={quality} bytes={output_io.getbuffer().nbytes}")

    memfile = InMemoryUploadedFile(
        file=output_io,
        field_name=None,
        name=(uploaded_file.name.rsplit('.', 1)[0] + '.webp'),
        content_type='image/webp',
        size=output_io.getbuffer().nbytes,
        charset=None,
    )

    logger.info(f"normalize_to_webp: done name={memfile.name} size={memfile.size} content_type={memfile.content_type}")
    return memfile


