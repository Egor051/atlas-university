"""Convert a bounded, untrusted input to a fresh, image-only PDF in a child process."""
import io
import math
import os
import sys
import warnings


MAX_BYTES = 5 * 1024 * 1024
MAX_PAGES = 8
PAGE_PIXELS = 2100


def set_limits():
    if os.name == 'posix':
        import resource

        memory = 192 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        resource.setrlimit(resource.RLIMIT_CPU, (7, 8))


def render_pdf(content):
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(content)
    try:
        if not 1 <= len(pdf) <= MAX_PAGES:
            raise ValueError('page count')
        pages = []
        for number in range(len(pdf)):
            page = pdf[number]
            width, height = page.get_size()
            if not all(math.isfinite(axis) and 1 <= axis <= 20_000 for axis in (width, height)):
                raise ValueError('page dimensions')
            bitmap = page.render(scale=min(3, PAGE_PIXELS / max(width, height)), may_draw_forms=False,
                                 draw_annots=True, limit_image_cache=True)
            pages.append(bitmap.to_pil().convert('RGB'))
            bitmap.close()
            page.close()
        return pages
    finally:
        pdf.close()


def render_photo(content, kind):
    from PIL import Image, ImageOps

    Image.MAX_IMAGE_PIXELS = 24_000_000
    warnings.simplefilter('error', Image.DecompressionBombWarning)
    expected = 'PNG' if kind == 'png' else 'JPEG'
    with Image.open(io.BytesIO(content), formats=[expected]) as photo:
        if photo.n_frames != 1:
            raise ValueError('animated picture')
        image = ImageOps.exif_transpose(photo)
        image.thumbnail((PAGE_PIXELS, PAGE_PIXELS))
        canvas = Image.new('RGB', image.size, 'white')
        if 'A' in image.getbands() or 'transparency' in image.info:
            image = image.convert('RGBA')
            canvas.paste(image, mask=image.getchannel('A'))
        else:
            canvas.paste(image.convert('RGB'))
        return [canvas]


def main():
    set_limits()
    content = sys.stdin.buffer.read(MAX_BYTES + 1)
    if not 0 < len(content) <= MAX_BYTES:
        return 1
    kind = sys.argv[1]
    pages = render_pdf(content) if kind == 'pdf' else render_photo(content, kind)
    output = io.BytesIO()
    pages[0].save(output, 'PDF', save_all=True, append_images=pages[1:], resolution=180, quality=88)
    if not 0 < output.tell() <= MAX_BYTES:
        return 1
    sys.stdout.buffer.write(output.getbuffer())
    return 0


if __name__ == '__main__':
    # Parser diagnostics can contain document information. The caller only
    # consumes the exit code and the rebuilt payload.
    try:
        status = main()
    except Exception:
        status = 1
    sys.exit(status)
