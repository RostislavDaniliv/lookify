from django.shortcuts import render, redirect
from django.http import HttpResponse
from .forms import UploadForm, ProcessForm
from django.conf import settings
import os
from django.contrib import messages
from .services.gemini_client import GeminiClient
from .services.image_utils import build_preview_placeholder, combine_item_images
import logging
import base64
import uuid
from datetime import date
from io import BytesIO
from PIL import Image

logger = logging.getLogger(__name__)

# Create your views here.

def home(request):
    return render(request, 'home.html')

def upload_view(request):
    if request.method == 'POST':
        logger.info(f"Upload view - FILES keys: {list(request.FILES.keys())}")
        for key in request.FILES.keys():
            files = request.FILES.getlist(key) if hasattr(request.FILES, 'getlist') else [request.FILES[key]]
            logger.info(f"Upload view - {key}: {len(files)} files")
            for i, file in enumerate(files):
                logger.info(f"Upload view - {key}[{i}]: {file.name}, size: {file.size}")
        
        form = UploadForm(request.POST, request.FILES)
        if form.is_valid():
            user_file = form.cleaned_data['user_photo']
            item_files = form.cleaned_data['item_photo']

            # Зберігаємо в MEDIA як .webp
            today_dir = os.path.join(settings.MEDIA_ROOT, 'uploads', str(date.today().year), str(date.today().month))
            os.makedirs(today_dir, exist_ok=True)

            def save_memfile(memfile):
                file_name = f"{uuid.uuid4()}.webp"
                full_path = os.path.join(today_dir, file_name)
                with open(full_path, 'wb') as f:
                    f.write(memfile.read())
                return os.path.relpath(full_path, settings.MEDIA_ROOT)

            user_path = save_memfile(user_file)
            processed_item_paths = [save_memfile(f) for f in item_files]

            request.session['upload'] = {
                'user': user_path,
                'items': processed_item_paths,
                'prompt': form.cleaned_data['prompt_text']
            }
            return redirect('preview_view')
    else:
        form = UploadForm()
    return render(request, 'upload.html', {'form': form})

def preview_view(request):
    if 'upload' not in request.session:
        messages.error(request, "Please upload a photo first.")
        return redirect('upload_view')

    uploaded_data = request.session['upload']
    user_photo_url = os.path.join(settings.MEDIA_URL, uploaded_data['user'])
    item_photo_paths = uploaded_data['items'] # Очікуємо список шляхів
    item_photo_urls = [os.path.join(settings.MEDIA_URL, path) for path in item_photo_paths] # Створюємо список URL-адрес

    context = {
        'user_photo_url': user_photo_url,
        'item_photo_urls': item_photo_urls, # Передаємо список URL-адрес
    }
    return render(request, 'preview.html', context)

def build_prompt(user_prompt=None, additional_prompt=None, use_mask=False):
    base = (
        "[TASK]\n"
        "Perform image editing: place the ITEM from the combined item image onto the PERSON in the person image as a natural try-on.\n"
        "The combined item image contains multiple items arranged in a grid - treat them as separate items to try on.\n\n"
        "[ASSETS]\n"
        "- PERSON: keep face, body, lighting, and background unchanged.\n"
        "- ITEMS: copy exactly from the item image, maintaining their individual characteristics and details.\n\n"
        "[PLACEMENT]\n"
        "Align each ITEM to the anatomically correct region; match scale, rotation, perspective; resolve occlusions.\n"
        "Choose the most suitable item from the combined image for the person's pose and body type.\n\n"
        "[CONSTRAINTS]\n"
        "Preserve ITEM identity: exact color, material, texture, logos, patterns, fasteners.\n"
        "Do not redesign or replace the ITEM. Do not alter PERSON identity or background. No extra accessories.\n\n"
        "[STYLE]\n"
        "Photorealistic blend; consistent shadows/highlights and noise.\n\n"
        "[OUTPUT]\n"
        "Return a single edited image where the chosen ITEM is clearly visible and naturally fitted on the PERSON.\n\n"
        "[FAIL IF]\n"
        "Never return an unchanged image. If uncertain, still place the most suitable ITEM as best as possible.\n\n"
        "[NEGATIVE]\n"
        "No fantasy variations, no color shifts, no new patterns, no brand swaps, no AI-art look.\n"
    )
    if user_prompt:
        base += f"\n[USER]\n{user_prompt}\n"
    if additional_prompt:
        base += f"\n[USER-SPECIFIC]\n{additional_prompt}\n"
    if use_mask:
        base += (
            "\n[MASK]\nUse the provided binary MASK over the item image. White=ITEM region of interest; use only this shape and texture.\n"
        )
    return base

def process_view(request):
    if request.method == 'POST':
        form = ProcessForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Invalid form data.")
            return redirect('upload_view')

        if 'upload' not in request.session:
            messages.error(request, "Please upload photos for processing.")
            return redirect('upload_view')

        uploaded_data = request.session['upload']
        user_img_path = uploaded_data['user']
        item_img_paths = uploaded_data['items'] # Отримуємо список шляхів
        
        logger.info(f"Processing view - User image: {user_img_path}")
        logger.info(f"Processing view - Item images count: {len(item_img_paths) if item_img_paths else 0}")
        logger.info(f"Processing view - Item images: {item_img_paths}")

        user_prompt = uploaded_data.get('prompt', '')
        additional_prompt = form.cleaned_data.get('additional_prompt', '')

        selection_mask_base64 = form.cleaned_data.get('selection_mask')
        mask_img_path = None

        use_mask = False
        if selection_mask_base64:
            use_mask = True
            try:
                # Remove data URI prefix
                header, encoded = selection_mask_base64.split(',', 1)
                decoded_mask = base64.b64decode(encoded)

                # Save mask as a temporary file
                mask_dir = os.path.join(settings.MEDIA_ROOT, 'masks')
                os.makedirs(mask_dir, exist_ok=True)

                mask_file_name = f"mask_{uuid.uuid4()}.png"
                full_mask_path = os.path.join(mask_dir, mask_file_name)

                with open(full_mask_path, 'wb') as f:
                    f.write(decoded_mask)

                mask_img_path = os.path.relpath(full_mask_path, settings.MEDIA_ROOT)
                logger.info(f"Mask successfully saved: {mask_img_path}")
            except Exception as e:
                logger.error(f"Error decoding or saving mask: {e}", exc_info=True)
                messages.error(request, "Error processing selection mask.")

        all_result_paths = []

        logger.info(f"Processing {len(item_img_paths)} items together")

        # Об'єднуємо всі фото айтемів в одне зображення
        try:
            combined_items_path = combine_item_images(item_img_paths)
            logger.info(f"Successfully combined {len(item_img_paths)} items into: {combined_items_path}")
        except Exception as e:
            logger.error(f"Failed to combine item images: {e}", exc_info=True)
            messages.error(request, "Failed to process item images. Please try again.")
            return redirect('upload_view')

        prompt = build_prompt(user_prompt, additional_prompt, use_mask) # Використання нової функції build_prompt

        if settings.USE_GEMINI:
            gemini_client = GeminiClient()
            try:
                # Використовуємо звичайний метод з об'єднаним зображенням айтемів
                result_path = gemini_client.try_on_item(user_img_path, combined_items_path, prompt, mask_img_path)
                all_result_paths = [result_path]  # Один результат для об'єднаного зображення
                messages.success(request, "Image successfully processed with Gemini!")
            except Exception as e:
                logger.warning(f"Error calling Gemini API ({e}). Using placeholder.", exc_info=True)
                messages.warning(request, f"Error processing images with AI: {e}. Showing temporary preview.")
                # Fallback to placeholder in case of AI error
                try:
                    result_path = build_preview_placeholder(user_img_path, combined_items_path, additional_prompt)
                    if result_path:
                        all_result_paths = [result_path]
                except Exception as placeholder_e:
                    logger.error(f"Failed to create placeholder: {placeholder_e}", exc_info=True)
        else: # USE_GEMINI is False
            messages.info(request, "AI integration is disabled or unavailable. Showing temporary preview.")
            try:
                result_path = build_preview_placeholder(user_img_path, combined_items_path, additional_prompt)
                if result_path:
                    all_result_paths = [result_path]
            except Exception as placeholder_e:
                logger.error(f"Failed to create placeholder: {placeholder_e}", exc_info=True)

        if all_result_paths:
            request.session['results'] = all_result_paths # Зберігаємо список результатів
            return redirect('result_view')
        else:
            messages.error(request, "Failed to generate any result. Please try again.")
            return redirect('upload_view')

def result_view(request):
    if 'results' not in request.session:
        messages.error(request, "Processing results not found. Please start over.")
        return redirect('upload_view')

    result_paths = request.session['results'] # Очікуємо список шляхів
    result_urls = [os.path.join(settings.MEDIA_URL, path) for path in result_paths] # Створюємо список URL-адрес

    context = {
        'result_urls': result_urls, # Передаємо список URL-адрес
    }
    return render(request, 'result.html', context)

# =========================
# Hair try-on flow
# =========================

def hair_upload_view(request):
    if request.method == 'POST':
        logger.info(f"Hair Upload - FILES keys: {list(request.FILES.keys())}")
        form = UploadForm(request.POST, request.FILES)
        if form.is_valid():
            user_file = form.cleaned_data['user_photo']
            item_files = form.cleaned_data['item_photo']

            today_dir = os.path.join(settings.MEDIA_ROOT, 'uploads', str(date.today().year), str(date.today().month))
            os.makedirs(today_dir, exist_ok=True)

            def save_memfile(memfile):
                file_name = f"{uuid.uuid4()}.webp"
                full_path = os.path.join(today_dir, file_name)
                with open(full_path, 'wb') as f:
                    f.write(memfile.read())
                return os.path.relpath(full_path, settings.MEDIA_ROOT)

            user_path = save_memfile(user_file)
            processed_item_paths = [save_memfile(f) for f in item_files]

            request.session['hair_upload'] = {
                'user': user_path,
                'items': processed_item_paths,
                'prompt': form.cleaned_data['prompt_text']
            }
            return redirect('hair_preview_view')
    else:
        form = UploadForm()
    return render(request, 'hair_upload.html', {'form': form})


def hair_preview_view(request):
    if 'hair_upload' not in request.session:
        messages.error(request, "Спершу завантажте фото.")
        return redirect('hair_upload_view')

    uploaded_data = request.session['hair_upload']
    user_photo_url = os.path.join(settings.MEDIA_URL, uploaded_data['user'])
    item_photo_paths = uploaded_data['items']
    item_photo_urls = [os.path.join(settings.MEDIA_URL, path) for path in item_photo_paths]

    context = {
        'user_photo_url': user_photo_url,
        'item_photo_urls': item_photo_urls,
    }
    return render(request, 'hair_preview.html', context)


def build_hair_prompt(user_prompt=None, additional_prompt=None):
    base = (
    "[TASK]\n"
    "Perform high-quality image editing: apply the HAIRSTYLE from the provided hairstyle image(s) onto the PERSON image as a natural, photorealistic hair try-on.\n\n"

    "[ASSETS]\n"
    "- PERSON: strictly preserve face identity, proportions, skin tone, lighting, and original background.\n"
    "- HAIRSTYLE: replicate exactly the length, texture, curl pattern, density, color, highlights, and hairline.\n\n"

    "[PLACEMENT]\n"
    "Precisely align the HAIRSTYLE to the PERSON’s head. Adjust scale, rotation, and perspective. Ensure seamless integration around forehead, temples, and ears. Respect occlusions (e.g., earrings, glasses, hats).\n\n"

    "[BLENDING]\n"
    "Smoothly merge hair edges with scalp. Preserve natural transparency in flyaway hairs. Match global and local lighting conditions, shadows, and reflections. Avoid hard edges or cutout look.\n\n"

    "[CONSTRAINTS]\n"
    "Do not modify the PERSON’s facial identity, head shape, skin, or background. Do not alter hairstyle identity unless explicitly requested (no recoloring, redesigning, or shortening/lengthening).\n\n"

    "[STYLE]\n"
    "Ultra-photorealistic output. Maintain natural texture, volume, depth, and strand-level detail. Ensure hair looks realistic under the given lighting.\n\n"

    "[OUTPUT]\n"
    "Return a single, final edited image with the chosen HAIRSTYLE naturally and convincingly fitted onto the PERSON.\n\n"

    "[NEGATIVE]\n"
    "No cartoonish style, no artificial glow, no extra accessories, no distortions, no unrealistic blending or duplicated strands.\n"
    )
    
    if user_prompt:
        base += f"\n[USER]\n{user_prompt}\n"
    if additional_prompt:
        base += f"\n[USER-SPECIFIC]\n{additional_prompt}\n"
    return base


def hair_process_view(request):
    if request.method == 'POST':
        form = ProcessForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Невалідні дані форми.")
            return redirect('hair_upload_view')

        if 'hair_upload' not in request.session:
            messages.error(request, "Будь ласка, завантажте фото для обробки.")
            return redirect('hair_upload_view')

        uploaded_data = request.session['hair_upload']
        user_img_path = uploaded_data['user']
        item_img_paths = uploaded_data['items']

        user_prompt = uploaded_data.get('prompt', '')
        additional_prompt = form.cleaned_data.get('additional_prompt', '')

        # Для зачісок не використовуємо маску за замовчуванням
        prompt = build_hair_prompt(user_prompt, additional_prompt)

        # Об'єднуємо фото зачісок в одну сітку (для вибору найкращої)
        try:
            combined_items_path = combine_item_images(item_img_paths)
        except Exception as e:
            logger.error(f"Failed to combine hairstyle images: {e}", exc_info=True)
            messages.error(request, "Не вдалося обробити фото зачісок. Спробуйте ще раз.")
            return redirect('hair_upload_view')

        all_result_paths = []

        if settings.USE_GEMINI:
            gemini_client = GeminiClient()
            try:
                result_path = gemini_client.try_on_item(user_img_path, combined_items_path, prompt, None)
                all_result_paths = [result_path]
                messages.success(request, "Зображення успішно оброблено за допомогою Gemini!")
            except Exception as e:
                logger.warning(f"Error calling Gemini API for hair ({e}). Using placeholder.", exc_info=True)
                messages.warning(request, f"Помилка AI-обробки: {e}. Показуємо тимчасовий прев'ю.")
                try:
                    result_path = build_preview_placeholder(user_img_path, combined_items_path, additional_prompt)
                    if result_path:
                        all_result_paths = [result_path]
                except Exception as placeholder_e:
                    logger.error(f"Failed to create hair placeholder: {placeholder_e}", exc_info=True)
        else:
            messages.info(request, "AI відключено. Показуємо тимчасовий прев'ю.")
            try:
                result_path = build_preview_placeholder(user_img_path, combined_items_path, additional_prompt)
                if result_path:
                    all_result_paths = [result_path]
            except Exception as placeholder_e:
                logger.error(f"Failed to create hair placeholder: {placeholder_e}", exc_info=True)

        if all_result_paths:
            request.session['hair_results'] = all_result_paths
            return redirect('hair_result_view')
        else:
            messages.error(request, "Не вдалося згенерувати результат.")
            return redirect('hair_upload_view')


def hair_result_view(request):
    if 'hair_results' not in request.session:
        messages.error(request, "Результати не знайдені. Почніть спочатку.")
        return redirect('hair_upload_view')

    result_paths = request.session['hair_results']
    result_urls = [os.path.join(settings.MEDIA_URL, path) for path in result_paths]
    context = {
        'result_urls': result_urls,
    }
    return render(request, 'hair_result.html', context)
