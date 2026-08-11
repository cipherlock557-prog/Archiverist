from __future__ import annotations

import io
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional
from urllib.parse import urlparse

import aiohttp
import discord
from PIL import Image, ImageDraw, ImageFont, ImageOps

DEFAULT_WIDTH = 1000
DEFAULT_HEIGHT = 700

MIN_CANVAS_SIZE = 300
MAX_CANVAS_WIDTH = 1600
MAX_CANVAS_HEIGHT = 1200

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_ELEMENTS = 100

DEFAULT_BACKGROUND = "#20232B"

ALLOWED_TYPES = {
    "image",
    "text",
    "quote",
    "rect",
    "line",
}

def valid_url(url: Any) -> bool:
    try:
        parsed = urlparse(str(url or "").strip())
        return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False

def normalize_color(value: Any, fallback: str = DEFAULT_BACKGROUND) -> str:
    value = str(value or "").strip()

    if re.fullmatch(r"#?[0-9a-fA-F]{6}", value):
        return "#" + value.lstrip("#").upper()

    return fallback

def safe_int(value: Any, default: int = 0, minimum: int = 0,
             maximum: int = 10000) -> int:
    try:
        number = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default

    return max(minimum, min(maximum, number))

def safe_float(value: Any, default: float = 0.0,
               minimum: float = -360.0, maximum: float = 360.0) -> float:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return default

    return max(minimum, min(maximum, number))

def clip_text(value: Any, limit: int = 4000) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit - 3] + "..."

def build_variables(
    oc: Dict[str, Any],
    message: str = "",
    owner: str = "",
) -> Dict[str, str]:

    variables = {
        "name": str(oc.get("name", "")),
        "age": str(oc.get("age", "")),
        "pronouns": str(oc.get("pronouns", "")),
        "personality": str(oc.get("personality", "")),
        "appearance": str(oc.get("appearance", "")),
        "lore": str(oc.get("lore", "")),
        "likes": str(oc.get("likes", "")),
        "dislikes": str(oc.get("dislikes", "")),
        "abilities": str(oc.get("abilities", "")),
        "relationships": str(oc.get("relationships", "")),
        "notes": str(oc.get("notes", "")),
        "pfp": str(oc.get("image", "")),
        "banner": str(oc.get("banner", "")),
        "color": str(oc.get("color", "#5865F2")),
        "message": str(message or ""),
        "owner": str(owner or ""),
    }

    return variables

def replace_variables(value: Any, variables: Dict[str, str]) -> str:
    text = str(value or "")

    def replace(match):
        key = match.group(1).strip().lower()
        return variables.get(key, match.group(0))

    return re.sub(r"\{([^{}]+)\}", replace, text)

def parse_layout(
    content: str,
    oc: Optional[Dict[str, Any]] = None,
    message: str = "",
    owner: str = "",
) -> Dict[str, Any]:

    oc = oc or {}
    variables = build_variables(oc, message, owner)

    result = {
        "width": DEFAULT_WIDTH,
        "height": DEFAULT_HEIGHT,
        "background": DEFAULT_BACKGROUND,
        "elements": [],
    }

    content = clip_text(content, 20000)

    cleaned_lines = []
    for raw_line in content.splitlines():
        line = raw_line.strip()

        if not line:
            cleaned_lines.append("")
            continue

        if line.startswith("#"):
            if not line.lower().startswith("# background"):
                continue

        cleaned_lines.append(line)

    blocks: List[List[str]] = []
    current: List[str] = []

    for line in cleaned_lines:
        if not line:
            if current:
                blocks.append(current)
                current = []
        else:
            current.append(line)

    if current:
        blocks.append(current)

    for block in blocks:
        first = block[0]

        if first.lower().startswith("canvas "):
            parts = first.split()
            if len(parts) >= 3:
                result["width"] = safe_int(
                    parts[1],
                    DEFAULT_WIDTH,
                    MIN_CANVAS_SIZE,
                    MAX_CANVAS_WIDTH,
                )
                result["height"] = safe_int(
                    parts[2],
                    DEFAULT_HEIGHT,
                    MIN_CANVAS_SIZE,
                    MAX_CANVAS_HEIGHT,
                )
            continue

        if first.lower().startswith("background "):
            value = replace_variables(first[len("background "):], variables)
            result["background"] = value.strip()
            continue

        element_type = first.lower()

        if element_type not in ALLOWED_TYPES:
            continue

        values: Dict[str, str] = {}

        for line in block[1:]:
            if " " not in line:
                continue

            key, value = line.split(" ", 1)
            values[key.lower().strip()] = replace_variables(
                value.strip(),
                variables,
            )

        element: Dict[str, Any] = {
            "type": element_type,
            "x": safe_int(values.get("x"), 0, -2000, 5000),
            "y": safe_int(values.get("y"), 0, -2000, 5000),
            "width": safe_int(values.get("width"), 200, 1, 5000),
            "height": safe_int(values.get("height"), 100, 1, 5000),
            "size": safe_int(values.get("size"), 24, 6, 200),
            "rotation": safe_float(values.get("rotation"), 0),
            "color": normalize_color(values.get("color"), "#FFFFFF"),
            "content": values.get("content", ""),
            "url": values.get("url", ""),
            "align": str(values.get("align", "left")).lower().strip(),
            "radius": safe_int(values.get("radius"), 0, 0, 500),
            "thickness": safe_int(values.get("thickness"), 4, 1, 100),
        }

        result["elements"].append(element)

        if len(result["elements"]) >= MAX_ELEMENTS:
            break

    return result

def _get_font(size: int, bold: bool = False, italic: bool = False):

    candidates = []

    if bold:
        candidates.extend([
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
        ])
    elif italic:
        candidates.extend([
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
            "C:/Windows/Fonts/ariali.ttf",
        ])
    else:
        candidates.extend([
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ])

    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            pass

    return ImageFont.load_default()

async def download_image(url: str) -> Optional[Image.Image]:

    if not valid_url(url):
        return None

    timeout = aiohttp.ClientTimeout(total=15)

    headers = {
        "User-Agent": "Archivist-OC-Layout/1.0",
        "Accept": "image/*,*/*;q=0.8",
    }

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers, allow_redirects=True) as response:
                if response.status != 200:
                    return None

                data = await response.read()

                if len(data) > MAX_IMAGE_BYTES:
                    return None

        image = Image.open(io.BytesIO(data))
        image.load()

        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGBA")

        return image.convert("RGBA")

    except Exception:
        return None

def _paste_rotated(
    canvas: Image.Image,
    image: Image.Image,
    x: int,
    y: int,
    width: int,
    height: int,
    rotation: float = 0,
):
    # Match the HTML editor's image behavior: width/height are exact
    # (object-fit: fill), and CSS rotation happens around the element center.
    width = max(1, int(width))
    height = max(1, int(height))
    image = image.resize(
        (width, height),
        resample=Image.Resampling.LANCZOS,
    )

    if rotation:
        rotated = image.rotate(
            -float(rotation),
            expand=True,
            resample=Image.Resampling.BICUBIC,
        )
        paste_x = int(round(x + (width - rotated.width) / 2))
        paste_y = int(round(y + (height - rotated.height) / 2))
        canvas.alpha_composite(rotated, (paste_x, paste_y))
    else:
        canvas.alpha_composite(image, (int(x), int(y)))

def _draw_wrapped_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font,
    fill: str,
    x: int,
    y: int,
    max_width: int,
    line_spacing: int = 6,
    align: str = "left",
):
    words = text.split()
    if not words:
        return

    lines = []
    current = ""

    for word in words:
        test = word if not current else f"{current} {word}"

        try:
            bbox = draw.textbbox((0, 0), test, font=font)
            width = bbox[2] - bbox[0]
        except Exception:
            width = len(test) * 8

        if width <= max_width or not current:
            current = test
        else:
            lines.append(current)
            current = word

    if current:
        lines.append(current)

    line_y = y

    align = str(align or "left").lower()

    for line in lines:
        try:
            bbox = draw.textbbox((0, 0), line, font=font)
            line_width = bbox[2] - bbox[0]
            height = bbox[3] - bbox[1]
        except Exception:
            line_width = len(line) * 8
            height = font.size if hasattr(font, "size") else 20

        draw_x = x
        if align == "center":
            draw_x = x + max(0, (max_width - line_width) / 2)
        elif align == "right":
            draw_x = x + max(0, max_width - line_width)

        draw.text(
            (draw_x, line_y),
            line,
            font=font,
            fill=fill,
        )

        line_y += height + line_spacing

async def _render_elements(
    canvas: Image.Image,
    elements: List[Dict[str, Any]],
):
    draw = ImageDraw.Draw(canvas)

    for element in elements:
        element_type = element.get("type")
        x = element.get("x", 0)
        y = element.get("y", 0)

        if element_type == "image":
            image = await download_image(element.get("url", ""))

            if image is None:
                continue

            _paste_rotated(
                canvas,
                image,
                x,
                y,
                element.get("width", 200),
                element.get("height", 100),
                element.get("rotation", 0),
            )

        elif element_type in {"text", "quote"}:
            content = element.get("content", "")
            if not content:
                continue

            size = element.get("size", 24)
            font = _get_font(
                size,
                bold=(element_type == "text"),
            )

            # The HTML editor uses padding on text/quote elements. Keep the
            # exported coordinates tied to the same top-left box.
            padding = 3 if element_type == "text" else 10
            text_x = x + padding
            text_y = y + padding
            text_width = max(1, element.get("width", 700) - padding * 2)

            if element_type == "quote":
                content = f"“ {content}"

            _draw_wrapped_text(
                draw,
                content,
                font,
                element.get("color", "#FFFFFF"),
                text_x,
                text_y,
                text_width,
                line_spacing=max(0, round(size * 0.2)),
                align=element.get("align", "left"),
            )

        elif element_type == "rect":
            x2 = x + element.get("width", 200)
            y2 = y + element.get("height", 100)

            draw.rounded_rectangle(
                (x, y, x2, y2),
                radius=element.get("radius", 0),
                fill=element.get("color", "#FFFFFF"),
            )

        elif element_type == "line":
            x2 = x + element.get("width", 200)
            y2 = y + element.get("height", 0)

            draw.line(
                (x, y, x2, y2),
                fill=element.get("color", "#FFFFFF"),
                width=element.get("thickness", 4),
            )

async def render_oc_layout(
    oc: Dict[str, Any],
    message: str = "",
    owner: str = "",
    layout_content: Optional[str] = None,
) -> io.BytesIO:

    if layout_content is None:
        custom = oc.get("custom_layout") or {}
        layout_content = custom.get("content", "")

    parsed = parse_layout(
        layout_content,
        oc=oc,
        message=message,
        owner=owner,
    )

    width = parsed["width"]
    height = parsed["height"]

    background = parsed["background"]

    canvas = Image.new(
        "RGBA",
        (width, height),
        normalize_color(background, DEFAULT_BACKGROUND),
    )

    if valid_url(background):
        background_image = await download_image(background)

        if background_image is not None:
            background_image = ImageOps.fit(
                background_image,
                (width, height),
                method=Image.Resampling.LANCZOS,
            )
            canvas.alpha_composite(background_image)

    await _render_elements(
        canvas,
        parsed["elements"],
    )

    output = io.BytesIO()
    canvas.convert("RGB").save(
        output,
        format="PNG",
        optimize=True,
    )
    output.seek(0)

    return output

DEFAULT_LAYOUT_EXAMPLE = """canvas 1000 700
background #20232B

image
url {banner}
x 0
y 0
width 1000
height 220

image
url {pfp}
x 50
y 120
width 220
height 220

text
content {name}
x 310
y 125
size 42
width 600

text
content {age} • {pronouns}
x 310
y 185
size 20
width 600

quote
content {message}
x 50
y 400
size 24
width 850
"""

GetOC = Callable[[int, str], Optional[Dict[str, Any]]]
SaveOC = Callable[[], Awaitable[None]]

class CustomLayoutModal(discord.ui.Modal, title="🖼️ Custom OC Layout"):

    layout = discord.ui.TextInput(
        label="Advanced Layout",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=4000,
        placeholder="canvas 1000 700\nimage\nurl {pfp}\nx 50\ny 50",
    )

    def __init__(
        self,
        owner_id: int,
        oc_key: str,
        get_oc: GetOC,
        save_oc: SaveOC,
    ):
        super().__init__()

        self.owner_id = owner_id
        self.oc_key = oc_key
        self.get_oc = get_oc
        self.save_oc = save_oc

        oc = self.get_oc(owner_id, oc_key)

        if oc:
            custom = oc.get("custom_layout") or {}
            existing = custom.get("content", "")
            if existing:
                self.layout.default = existing[:4000]

    async def on_submit(self, interaction: discord.Interaction):
        oc = self.get_oc(self.owner_id, self.oc_key)

        if oc is None:
            await interaction.response.send_message(
                "❌ That OC no longer exists.",
                ephemeral=True,
            )
            return

        content = str(self.layout.value or "").strip()

        try:
            parsed = parse_layout(
                content,
                oc=oc,
                message="",
                owner=str(interaction.user.display_name),
            )
        except Exception as error:
            await interaction.response.send_message(
                f"❌ I couldn't read that layout:\n`{error}`",
                ephemeral=True,
            )
            return

        oc["custom_layout"] = {
            "enabled": bool(content),
            "content": content,
            "width": parsed["width"],
            "height": parsed["height"],
        }

        try:
            await self.save_oc()
        except Exception as error:
            await interaction.response.send_message(
                f"❌ The layout was prepared, but I couldn't save it:\n`{error}`",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "✅ **Custom layout saved!**\n"
            "Use **Preview Layout** to check how it looks.",
            ephemeral=True,
        )

class CustomLayoutButton(discord.ui.Button):

    def __init__(
        self,
        owner_id: int,
        oc_key: str,
        get_oc: GetOC,
        save_oc: SaveOC,
    ):
        super().__init__(
            label="Custom Layout",
            emoji="🖼️",
            style=discord.ButtonStyle.secondary,
            row=2,
        )

        self.owner_id = owner_id
        self.oc_key = oc_key
        self.get_oc = get_oc
        self.save_oc = save_oc

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "🔒 Only the OC owner can edit the custom layout.",
                ephemeral=True,
            )
            return

        oc = self.get_oc(self.owner_id, self.oc_key)

        if oc is None:
            await interaction.response.send_message(
                "❌ That OC no longer exists.",
                ephemeral=True,
            )
            return

        try:
            await interaction.response.send_modal(
                CustomLayoutModal(
                    owner_id=self.owner_id,
                    oc_key=self.oc_key,
                    get_oc=self.get_oc,
                    save_oc=self.save_oc,
                )
            )
        except Exception as error:
            print(f"❌ Could not open Custom Layout modal: {error}")

            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"❌ I couldn't open the layout editor:\n`{error}`",
                    ephemeral=True,
                )

class PreviewLayoutButton(discord.ui.Button):

    def __init__(
        self,
        owner_id: int,
        oc_key: str,
        get_oc: GetOC,
    ):
        super().__init__(
            label="Preview Layout",
            emoji="👁️",
            style=discord.ButtonStyle.primary,
            row=2,
        )

        self.owner_id = owner_id
        self.oc_key = oc_key
        self.get_oc = get_oc

    async def callback(self, interaction: discord.Interaction):
        oc = self.get_oc(self.owner_id, self.oc_key)

        if oc is None:
            await interaction.response.send_message(
                "❌ That OC no longer exists.",
                ephemeral=True,
            )
            return

        custom = oc.get("custom_layout") or {}

        if not custom.get("enabled") or not custom.get("content"):
            await interaction.response.send_message(
                "ℹ️ This OC doesn't have a custom layout yet.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            image = await render_oc_layout(
                oc,
                message="Preview message",
                owner=str(interaction.user.display_name),
            )

            file = discord.File(
                image,
                filename="oc-layout-preview.png",
            )

            await interaction.followup.send(
                content="👁️ **OC Layout Preview**",
                file=file,
                ephemeral=True,
            )

        except Exception as error:
            print(f"❌ OC layout preview failed: {error}")

            await interaction.followup.send(
                f"❌ I couldn't render the layout:\n`{error}`",
                ephemeral=True,
            )

def layout_is_enabled(oc: Dict[str, Any]) -> bool:
    custom = oc.get("custom_layout") or {}
    return bool(
        custom.get("enabled")
        and str(custom.get("content", "")).strip()
    )