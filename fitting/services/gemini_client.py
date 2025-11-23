
from django.conf import settings
import os
import uuid
from datetime import date
import logging
import google.generativeai as genai
from PIL import Image
from io import BytesIO

logger = logging.getLogger(__name__)

class GeminiClient:
    def __init__(self):
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self.model = genai.GenerativeModel(settings.GEMINI_MODEL)
        if not settings.GEMINI_API_KEY and settings.USE_GEMINI:
            logger.warning("GEMINI_API_KEY is not configured, but USE_GEMINI=True. GeminiClient will not function properly.")

    def try_on_item(self, user_img_path: str, item_img_path: str, prompt: str, mask_img_path: str = None) -> str:
        """
        Performs an external call to the Gemini model for a single item.
        Returns the relative path to the saved AI image.
        """
        logger.info(f"Attempting to call Gemini API. Prompt: {prompt}, User: {user_img_path}, Item: {item_img_path}")

        try:
            user_image = Image.open(os.path.join(settings.MEDIA_ROOT, user_img_path))
            item_image = Image.open(os.path.join(settings.MEDIA_ROOT, item_img_path))

            # Check that images were actually opened and have dimensions
            if user_image.size == (0, 0) or item_image.size == (0, 0):
                raise ValueError("One or both images have zero dimensions for Gemini API.")
            
            # Add additional_prompt to the main prompt
            contents = [user_image, item_image, prompt]
            if mask_img_path:
                mask_image = Image.open(os.path.join(settings.MEDIA_ROOT, mask_img_path))
                if mask_image.size == (0, 0):
                    logger.warning("Mask has zero dimensions.")
                contents.insert(1, mask_image) # Add mask after user_image, but before item_image and prompt

            response = self.model.generate_content(
                contents,
                request_options={"timeout": settings.REQUEST_TIMEOUT}
            )

            # Check if response exists and if it contains an image
            if response and response.candidates:
                # Assuming the first candidate contains the image in parts
                for part in response.candidates[0].content.parts:
                    if part.inline_data is not None:
                        # Save the generated image
                        today = date.today()
                        results_dir = os.path.join(settings.MEDIA_ROOT, 'results', f"{today.year:04d}-{today.month:02d}")
                        os.makedirs(results_dir, exist_ok=True)

                        file_name = f"ai_result_{uuid.uuid4()}.jpeg"
                        full_path = os.path.join(results_dir, file_name)
                        
                        # Save image from model response
                        image = Image.open(BytesIO(part.inline_data.data))   
                        image.save(full_path, format='JPEG', quality=85)
                        logger.info(f"Gemini API successfully returned result: {file_name}")
                        return os.path.relpath(full_path, settings.MEDIA_ROOT)
                raise ValueError("Gemini API response does not contain an image.")
            else:
                raise ValueError("Gemini API response is empty or invalid.")

        except Exception as e:
            logger.error(f"Error calling Gemini API: {e}", exc_info=True)
            raise ValueError(f"Gemini API error: {e}")

    def try_on_multiple_items(self, user_img_path: str, item_img_paths: list, prompt: str, mask_img_path: str = None) -> list:
        """
        Performs a single external call to the Gemini model with multiple items.
        Returns a list of relative paths to the saved AI images.
        """
        logger.info(f"Attempting to call Gemini API with {len(item_img_paths)} items. User: {user_img_path}")

        try:
            user_image = Image.open(os.path.join(settings.MEDIA_ROOT, user_img_path))
            
            # Check that user image was actually opened and has dimensions
            if user_image.size == (0, 0):
                raise ValueError("User image has zero dimensions for Gemini API.")
            
            # Load all item images
            item_images = []
            for item_path in item_img_paths:
                item_image = Image.open(os.path.join(settings.MEDIA_ROOT, item_path))
                if item_image.size == (0, 0):
                    raise ValueError(f"Item image {item_path} has zero dimensions for Gemini API.")
                item_images.append(item_image)
            
            # Build contents for Gemini API
            contents = [user_image]
            if mask_img_path:
                mask_image = Image.open(os.path.join(settings.MEDIA_ROOT, mask_img_path))
                if mask_image.size == (0, 0):
                    logger.warning("Mask has zero dimensions.")
                contents.append(mask_image)
            
            # Add all item images
            contents.extend(item_images)
            contents.append(prompt)

            response = self.model.generate_content(
                contents,
                request_options={"timeout": settings.REQUEST_TIMEOUT}
            )

            # Check if response exists and if it contains images
            if response and response.candidates:
                result_paths = []
                today = date.today()
                results_dir = os.path.join(settings.MEDIA_ROOT, 'results', f"{today.year:04d}-{today.month:02d}")
                os.makedirs(results_dir, exist_ok=True)

                # Process all parts in the response
                for i, part in enumerate(response.candidates[0].content.parts):
                    if part.inline_data is not None:
                        # Save the generated image
                        file_name = f"ai_result_{uuid.uuid4()}.jpeg"
                        full_path = os.path.join(results_dir, file_name)
                        
                        # Save image from model response
                        image = Image.open(BytesIO(part.inline_data.data))   
                        image.save(full_path, format='JPEG', quality=85)
                        logger.info(f"Gemini API successfully returned result {i+1}: {file_name}")
                        result_paths.append(os.path.relpath(full_path, settings.MEDIA_ROOT))
                
                if result_paths:
                    logger.info(f"Gemini API returned {len(result_paths)} results")
                    return result_paths
                else:
                    raise ValueError("Gemini API response does not contain any images.")
            else:
                raise ValueError("Gemini API response is empty or invalid.")

        except Exception as e:
            logger.error(f"Error calling Gemini API: {e}", exc_info=True)
            raise ValueError(f"Gemini API error: {e}")
