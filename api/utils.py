from datetime import datetime
import io
from django.core.files.base import ContentFile
from django.conf import settings


ALLOWED_IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/webp'}
ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}


def compress_igazolas_image(uploaded_file) -> ContentFile:
    """
    Validate, compress and convert an uploaded image for storage.

    - Checks content type and file extension against the allowed list.
    - Enforces the IMAGE_MAX_UPLOAD_SIZE_MB upload cap.
    - Resizes the image so that neither dimension exceeds IMAGE_MAX_DIMENSION px,
      preserving the original aspect ratio.
    - Saves the result as a JPEG with IMAGE_QUALITY compression.

    Returns a ContentFile ready to be saved to an ImageField.
    Raises ValueError with a human-readable message on validation failure.
    """
    from PIL import Image as PILImage
    import os

    max_size_bytes = getattr(settings, 'IMAGE_MAX_UPLOAD_SIZE_MB', 10) * 1024 * 1024
    max_dimension = getattr(settings, 'IMAGE_MAX_DIMENSION', 1920)
    quality = getattr(settings, 'IMAGE_QUALITY', 85)

    # --- size check ---
    uploaded_file.seek(0, 2)  # seek to end
    file_size = uploaded_file.tell()
    uploaded_file.seek(0)
    if file_size > max_size_bytes:
        max_mb = getattr(settings, 'IMAGE_MAX_UPLOAD_SIZE_MB', 10)
        raise ValueError(f'A fájl mérete meghaladja a megengedett {max_mb} MB-ot.')

    # --- type check ---
    content_type = getattr(uploaded_file, 'content_type', '') or ''
    ext = os.path.splitext(getattr(uploaded_file, 'name', '') or '')[1].lower()
    if content_type not in ALLOWED_IMAGE_TYPES and ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError('Csak JPEG, PNG vagy WebP képeket lehet feltölteni.')

    # --- open & process ---
    try:
        img = PILImage.open(uploaded_file)
    except Exception:
        raise ValueError('A feltöltött fájl nem érvényes kép.')

    # Convert palette/transparency modes to RGB before JPEG save
    if img.mode in ('RGBA', 'LA', 'P'):
        background = PILImage.new('RGB', img.size, (255, 255, 255))
        if img.mode == 'P':
            img = img.convert('RGBA')
        background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
        img = background
    elif img.mode != 'RGB':
        img = img.convert('RGB')

    # Resize if necessary
    w, h = img.size
    if w > max_dimension or h > max_dimension:
        img.thumbnail((max_dimension, max_dimension), PILImage.LANCZOS)

    # Save as JPEG
    buffer = io.BytesIO()
    img.save(buffer, format='JPEG', quality=quality, optimize=True)
    buffer.seek(0)

    # Derive a safe filename
    base_name = os.path.splitext(os.path.basename(getattr(uploaded_file, 'name', 'image') or 'image'))[0]
    return ContentFile(buffer.read(), name=f'{base_name}.jpg')


def erintett_tanorak(eleje: datetime, vege: datetime) -> list[int]:
    # megmondja, mely órák érintettek két időopont között
    orak = [
        ("07:30", "08:15"), # 0. óra
        ("08:25", "09:10"), # 1. óra
        ("09:20", "10:05"), # 2. óra
        ("10:20", "11:05"), # 3. óra
        ("11:15", "12:00"), # 4. óra
        ("12:20", "13:05"), # 5. óra
        ("13:25", "14:10"), # 6. óra
        ("14:20", "15:05"), # 7. óra
        ("15:15", "16:00"), # 8. óra
    ]

    erintett = []

    for i, (kezdes_str, veg_str) in enumerate(orak):
        kezdes_ido = datetime.combine(eleje.date(), datetime.strptime(kezdes_str, "%H:%M").time())
        veg_ido = datetime.combine(eleje.date(), datetime.strptime(veg_str, "%H:%M").time())

        if eleje < veg_ido and vege > kezdes_ido:
            erintett.append(i)
    
    return erintett