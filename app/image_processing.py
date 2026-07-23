import io
import warnings

from fastapi import HTTPException, UploadFile, status
from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import Settings


Image.MAX_IMAGE_PIXELS = 25_000_000


async def normalize_uploaded_image(upload: UploadFile, settings: Settings) -> bytes:
    raw = await upload.read(settings.max_upload_bytes + 1)

    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty upload")

    if len(raw) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Image is too large",
        )

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            probe = Image.open(io.BytesIO(raw))
            probe.verify()

        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(raw))
            source_format = image.format
            image = ImageOps.exif_transpose(image)
            image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only valid JPEG or PNG images are accepted",
        ) from exc

    if source_format not in {"JPEG", "PNG"}:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only JPEG or PNG images are accepted",
        )

    if image.width < 320 or image.height < 240:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Image resolution is too small",
        )

    if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        image = background
    else:
        image = image.convert("RGB")

    image.thumbnail(
        (settings.max_image_dimension, settings.max_image_dimension),
        Image.Resampling.LANCZOS,
    )

    output = io.BytesIO()
    image.save(
        output,
        format="JPEG",
        quality=settings.jpeg_quality,
        optimize=True,
    )
    return output.getvalue()
