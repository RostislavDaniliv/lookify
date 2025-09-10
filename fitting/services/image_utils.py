
from PIL import Image, ImageDraw, ImageFont, ImageOps
import os
import uuid
from datetime import date
from django.conf import settings
import logging
import pillow_heif

# Реєструємо HEIF/HEIC підтримку
pillow_heif.register_heif_opener()

# Logger settings
logger = logging.getLogger(__name__)

def build_preview_placeholder(user_img_path: str, item_img_path: str, additional_prompt: str = '') -> str:
    """
    Locally generates a placeholder.
    Returns the relative path to the saved image.
    In the current context, this is simply a copy of the user's image.
    """
    try:
        full_user_path = os.path.abspath(os.path.join(settings.MEDIA_ROOT, user_img_path))
        if not full_user_path.startswith(os.path.abspath(settings.MEDIA_ROOT)):
            raise ValueError("Invalid image path: detected attempt at Path Traversal.")
    except Exception as e:
        logger.error(f"Error validating paths: {e}")
        raise ValueError("Invalid image file path.")

    try:
        with (Image.open(full_user_path) as user_img_orig):
            if user_img_orig.size == (0, 0):
                raise ValueError("User image has zero dimensions.")
            
            user_img = ImageOps.exif_transpose(user_img_orig)

            # Downscale if longer side > 3000px
            max_dimension = 3000
            user_img = _downscale_image(user_img, max_dimension)

            # Save result (simply the user's image)
            today = date.today()
            results_dir = os.path.join(settings.MEDIA_ROOT, 'results', f"{today.year:04d}-{today.month:02d}")
            os.makedirs(results_dir, exist_ok=True)

            file_name = f"placeholder_{uuid.uuid4()}.jpeg"
            full_path = os.path.join(results_dir, file_name)

            # Add additional_prompt text to the image if it exists
            if additional_prompt:
                draw = ImageDraw.Draw(user_img)
                try:
                    font = ImageFont.truetype("arial.ttf", 40)  # Try to use Arial font
                except IOError:
                    font = ImageFont.load_default()  # Use default font if Arial is not available
                text_color = (255, 255, 255)  # White text color
                text_position = (50, 50)  # Text position (x, y)
                draw.text(text_position, f"Your wishes: {additional_prompt}", font=font, fill=text_color)

            user_img.save(full_path, format='JPEG', quality=85, optimize=True)

            relative_path = os.path.relpath(full_path, settings.MEDIA_ROOT)
            logger.info(f"Created placeholder (copy of user image): {relative_path}")
            return relative_path

    except (FileNotFoundError, ValueError) as e:
        logger.error(f"Error processing image files for placeholder: {e}")
        raise ValueError(f"Placeholder file error: {e}")
    except Image.UnidentifiedImageError:
        logger.error("Could not identify user image for placeholder or file is corrupted.")
        raise ValueError("Provided file is not a valid image or is corrupted for placeholder.")
    except OSError as e:
        logger.error(f"File system error during image processing for placeholder: {e}")
        raise ValueError(f"Placeholder file access error: {e}")
    except Exception as e:
        logger.error(f"Unknown error during placeholder creation: {e}", exc_info=True)
        raise ValueError(f"Unknown error during placeholder creation: {e}")

def _downscale_image(img: Image.Image, max_dimension: int) -> Image.Image:
    if max(img.size) > max_dimension:
        ratio = max_dimension / max(img.size)
        new_size = tuple(int(x * ratio) for x in img.size)
        return img.resize(new_size, Image.Resampling.LANCZOS)
    return img

def combine_item_images(item_img_paths: list) -> str:
    """
    Combines multiple item images into a single collage image.
    Returns the relative path to the saved combined image.
    """
    try:
        if not item_img_paths:
            raise ValueError("No item images provided")
        
        # Load and process all item images
        item_images = []
        for item_path in item_img_paths:
            full_item_path = os.path.abspath(os.path.join(settings.MEDIA_ROOT, item_path))
            if not full_item_path.startswith(os.path.abspath(settings.MEDIA_ROOT)):
                raise ValueError("Invalid image path: detected attempt at Path Traversal.")
            
            with Image.open(full_item_path) as item_img_orig:
                if item_img_orig.size == (0, 0):
                    raise ValueError(f"Item image {item_path} has zero dimensions.")
                
                item_img = ImageOps.exif_transpose(item_img_orig)
                # Resize to a standard size for consistent collage
                item_img = _downscale_image(item_img, 800)
                item_images.append(item_img)
        
        # Calculate collage dimensions
        num_items = len(item_images)
        if num_items == 1:
            # Single image - just return it as is
            combined_img = item_images[0]
        else:
            # Multiple images - create a grid
            if num_items == 2:
                # 2 images side by side
                cols = 2
                rows = 1
            else:
                # 3+ images in a grid
                cols = 2
                rows = (num_items + 1) // 2
            
            # Calculate cell size based on the largest image
            max_width = max(img.width for img in item_images)
            max_height = max(img.height for img in item_images)
            cell_width = max_width
            cell_height = max_height
            
            # Create collage canvas
            collage_width = cols * cell_width + (cols - 1) * 20  # 20px spacing
            collage_height = rows * cell_height + (rows - 1) * 20  # 20px spacing
            combined_img = Image.new('RGB', (collage_width, collage_height), (255, 255, 255))
            
            # Place images in grid
            for i, img in enumerate(item_images):
                row = i // cols
                col = i % cols
                x = col * (cell_width + 20)
                y = row * (cell_height + 20)
                
                # Center the image in its cell
                img_x = x + (cell_width - img.width) // 2
                img_y = y + (cell_height - img.height) // 2
                combined_img.paste(img, (img_x, img_y))
        
        # Save combined image
        today = date.today()
        results_dir = os.path.join(settings.MEDIA_ROOT, 'results', f"{today.year:04d}-{today.month:02d}")
        os.makedirs(results_dir, exist_ok=True)
        
        file_name = f"combined_items_{uuid.uuid4()}.jpeg"
        full_path = os.path.join(results_dir, file_name)
        
        # Convert to RGB if the image has an alpha channel before saving as JPEG
        if combined_img.mode == 'RGBA':
            combined_img = combined_img.convert('RGB')

        combined_img.save(full_path, format='JPEG', quality=85, optimize=True)
        
        relative_path = os.path.relpath(full_path, settings.MEDIA_ROOT)
        logger.info(f"Created combined item collage: {relative_path}")
        return relative_path
        
    except Exception as e:
        logger.error(f"Error combining item images: {e}", exc_info=True)
        raise ValueError(f"Error combining item images: {e}")
