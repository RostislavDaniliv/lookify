from io import BytesIO
from PIL import Image, ImageOps
import pillow_heif
from django.core.files.uploadedfile import InMemoryUploadedFile
import logging
try:
    import magic as magic_lib  # python-magic
except Exception:  # optional
    magic_lib = None

# Optional HEIC/HEIF fallback via pyheif
try:
    import pyheif  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    pyheif = None

# Optional AVIF plugin (registers AVIF support for PIL if available)
try:
    import pillow_avif  # type: ignore  # noqa: F401
except Exception:
    try:
        # Some versions use different import path
        from pillow_avif import AvifImagePlugin  # type: ignore  # noqa: F401
    except Exception:
        pass

# External tools
import tempfile
import subprocess
import shutil
import os


def _resolve_executable(candidates):
    for name_or_path in candidates:
        path = shutil.which(name_or_path) if os.path.basename(name_or_path) == name_or_path else name_or_path
        if path and os.path.exists(path):
            return path
    return None


def _convert_heif_like_external(file_bytes, input_ext_hint: str, logger: logging.Logger):
    """Attempt to convert HEIC/HEIF/AVIF to PNG via external tools (heif-convert or ImageMagick).
    Returns a PIL.Image on success, else raises.
    """
    tmp_in = None
    tmp_out = None
    try:
        tmp_dir = tempfile.mkdtemp(prefix="heic_conv_")
        # Respect extension hint for better tool detection
        ext = input_ext_hint if input_ext_hint in (".heic", ".heif", ".avif") else ".heic"
        tmp_in = os.path.join(tmp_dir, f"input{ext}")
        tmp_out_png = os.path.join(tmp_dir, "output.png")
        with open(tmp_in, 'wb') as f:
            f.write(file_bytes)

        heif_convert = _resolve_executable(["heif-convert", "/usr/bin/heif-convert", "/usr/local/bin/heif-convert"])  # common locations
        magick = _resolve_executable(["magick", "convert", "/usr/bin/magick", "/usr/local/bin/magick", "/usr/bin/convert", "/usr/local/bin/convert"])  # ImageMagick

        if heif_convert:
            cmd = [heif_convert, tmp_in, tmp_out_png]
            logger.info(f"normalize_to_webp: trying external heif-convert: {cmd}")
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if proc.returncode != 0 or not os.path.exists(tmp_out_png):
                stderr = proc.stderr.decode(errors='ignore')
                raise RuntimeError(f"heif-convert failed (code={proc.returncode}): {stderr[:4000]}")
        elif magick:
            # ImageMagick path; convert to PNG
            cmd = [magick, tmp_in, tmp_out_png]
            logger.info(f"normalize_to_webp: trying external ImageMagick: {cmd}")
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if proc.returncode != 0 or not os.path.exists(tmp_out_png):
                stderr = proc.stderr.decode(errors='ignore')
                raise RuntimeError(f"ImageMagick failed (code={proc.returncode}): {stderr[:4000]}")
        else:
            raise RuntimeError("No external HEIC/AVIF converter found (need heif-convert or ImageMagick)")

        with Image.open(tmp_out_png) as im:
            im.load()
            return im.copy()
    finally:
        try:
            if tmp_in and os.path.exists(tmp_in):
                os.remove(tmp_in)
            if tmp_out and os.path.exists(tmp_out):
                os.remove(tmp_out)
            if 'tmp_dir' in locals() and os.path.isdir(tmp_dir):
                shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


def _has_alpha(img: Image.Image) -> bool:
    return img.mode in ("RGBA", "LA") or (img.mode == "P" and 'transparency' in img.info)


def normalize_to_webp(uploaded_file, max_px=2048, quality=82):
    """Normalize input image, supporting HEIC/HEIF/AVIF, and return JPEG as InMemoryUploadedFile.
    Note: Function name preserved for backward compatibility.
    """
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

    filename_lower = getattr(uploaded_file, 'name', '') or ''
    filename_lower = filename_lower.lower()

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
                # Try pyheif for HEIC/HEIF (pyheif doesn't handle AVIF)
                if pyheif is not None and ((detected_mime and ('heic' in detected_mime or 'heif' in detected_mime)) or filename_lower.endswith(('.heic', '.heif'))):
                    try:
                        heif = pyheif.read_heif(file_bytes)
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
                        logger.warning(f"normalize_to_webp: pyheif failed: {e_pyheif}")
                        # External converter fallback for HEIC/HEIF
                        try:
                            image = _convert_heif_like_external(file_bytes, ".heic", logger)
                            logger.info("normalize_to_webp: opened via external converter (heif)")
                        except Exception as e_ext:
                            logger.exception("normalize_to_webp: failed to open image via all fallbacks including external converter")
                            raise e_ext
                else:
                    # External converter fallback for HEIC/HEIF/AVIF
                    if (detected_mime and any(x in detected_mime for x in ("heic","heif","avif"))) or filename_lower.endswith(('.heic','.heif','.avif')):
                        try:
                            hint = '.avif' if filename_lower.endswith('.avif') or (detected_mime and 'avif' in detected_mime) else '.heic'
                            image = _convert_heif_like_external(file_bytes, hint, logger)
                            logger.info("normalize_to_webp: opened via external converter (heif/avif)")
                        except Exception as e_ext:
                            logger.exception("normalize_to_webp: failed to open image via all fallbacks including external converter (heif/avif)")
                            raise e_ext
                    else:
                        logger.exception("normalize_to_webp: failed to open image via PIL and pillow_heif fallbacks (non-heif/avif)")
                        raise

    try:
        image = ImageOps.exif_transpose(image)
    except Exception:
        pass

    # Ensure RGB for JPEG; if image has alpha, composite on white
    if _has_alpha(image):
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image, mask=image.split()[-1])
        image = background
        logger.info("normalize_to_webp: flattened alpha to RGB over white")
    elif image.mode != "RGB":
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
    image.save(output_io, format="JPEG", quality=quality, optimize=True, progressive=True)
    output_io.seek(0)
    logger.info(f"normalize_to_webp: saved to JPEG quality={quality} bytes={output_io.getbuffer().nbytes}")

    # Build filename with .jpg
    base_name = (uploaded_file.name.rsplit('.', 1)[0]) if hasattr(uploaded_file, 'name') and uploaded_file.name else "image"
    memfile = InMemoryUploadedFile(
        file=output_io,
        field_name=None,
        name=(base_name + '.jpg'),
        content_type='image/jpeg',
        size=output_io.getbuffer().nbytes,
        charset=None,
    )

    logger.info(f"normalize_to_webp: done name={memfile.name} size={memfile.size} content_type={memfile.content_type}")
    return memfile


