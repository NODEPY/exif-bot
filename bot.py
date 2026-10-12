import io
import os
import sys
import math
import uuid
import fcntl
import hashlib
import asyncio
from html import escape

import torch

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from PIL import (
    Image,
    ExifTags,
    ImageOps,
    ImageStat,
    ImageFilter,
    ImageDraw,
    ImageFont,
    UnidentifiedImageError,
)

from transformers import (
    BlipProcessor,
    BlipForConditionalGeneration,
    AutoTokenizer,
    AutoModelForSeq2SeqLM,
)

from dotenv import load_dotenv


# =========================================================
# SINGLE INSTANCE LOCK
# =========================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCK_PATH = os.path.join(BASE_DIR, ".bot.lock")

lock_file = open(LOCK_PATH, "w")

try:
    fcntl.flock(
        lock_file,
        fcntl.LOCK_EX | fcntl.LOCK_NB
    )

except BlockingIOError:
    print("❌ Бот уже запущений в іншому процесі.")
    print("Зупини стару копію перед новим запуском.")
    sys.exit(1)


# =========================================================
# CONFIG
# =========================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN не знайдено у .env"
    )


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# =========================================================
# DEVICES
# =========================================================

if torch.backends.mps.is_available():
    AI_DEVICE = "mps"

elif torch.cuda.is_available():
    AI_DEVICE = "cuda"

else:
    AI_DEVICE = "cpu"


# Marian перекладач на CPU стабільніший на macOS.
TRANSLATION_DEVICE = "cpu"


print("")
print("==============================")
print("🤖 AI EXIF BOT v4")
print("==============================")
print(f"AI device: {AI_DEVICE}")
print("")


# =========================================================
# BLIP
# =========================================================

print("⏳ Завантаження BLIP...")


blip_processor = BlipProcessor.from_pretrained(
    "Salesforce/blip-image-captioning-base"
)

blip_model = (
    BlipForConditionalGeneration.from_pretrained(
        "Salesforce/blip-image-captioning-base"
    )
)

blip_model.to(AI_DEVICE)
blip_model.eval()


print("✅ BLIP готовий")


# =========================================================
# LOCAL TRANSLATION
# =========================================================

TRANSLATION_MODELS = {

    "uk":
        "Helsinki-NLP/opus-mt-en-uk",

    "ru":
        "Helsinki-NLP/opus-mt-en-ru",
}


loaded_translators = {}


def get_translator(language):

    if language in loaded_translators:
        return loaded_translators[language]


    model_name = TRANSLATION_MODELS.get(
        language
    )

    if not model_name:
        return None


    print(
        f"⏳ Завантаження EN → {language.upper()}..."
    )


    tokenizer = AutoTokenizer.from_pretrained(
        model_name
    )


    model = AutoModelForSeq2SeqLM.from_pretrained(
        model_name
    )


    model.to(
        TRANSLATION_DEVICE
    )

    model.eval()


    loaded_translators[language] = (
        tokenizer,
        model
    )


    print(
        f"✅ EN → {language.upper()} готовий"
    )


    return tokenizer, model


# =========================================================
# MEMORY
# =========================================================

user_languages = {}

# analysis_cache[user_id][analysis_id] = data
analysis_cache = {}


def save_analysis(
    user_id,
    analysis_id,
    data
):

    if user_id not in analysis_cache:
        analysis_cache[user_id] = {}


    analysis_cache[user_id][
        analysis_id
    ] = data


    # Зберігаємо максимум 5 останніх аналізів.
    keys = list(
        analysis_cache[
            user_id
        ].keys()
    )


    while len(keys) > 5:

        old_id = keys.pop(0)

        analysis_cache[
            user_id
        ].pop(
            old_id,
            None
        )


def get_analysis(
    user_id,
    analysis_id
):

    return (
        analysis_cache
        .get(user_id, {})
        .get(analysis_id)
    )


# =========================================================
# LANGUAGE
# =========================================================

TEXTS = {

    "uk": {

        "welcome":
            "🧠 <b>AI EXIF Analyzer</b>\n\n"
            "📎 Надішли фотографію.\n\n"
            "Краще надсилати її як "
            "<b>файл без стиснення</b>, "
            "щоб Telegram не видалив EXIF.\n\n"
            "🤖 AI-опис\n"
            "📷 EXIF\n"
            "🔬 forensic-аналіз\n"
            "🔐 SHA-256 / aHash\n"
            "📍 GPS\n"
            "🛡 очищення метаданих\n"
            "🏷 copyright\n"
            "🖼 інформаційне превʼю",

        "analyzing":
            "🔄 Аналізую нове фото...",

        "translating":
            "🌐 Перекладаю AI-опис...",

        "preview":
            "🖼 Створити превʼю",

        "clean":
            "🛡 Очистити",

        "copyright":
            "🏷 Copyright",

        "maps":
            "🗺 Google Maps",

        "expired":
            "❌ Цей аналіз уже недоступний.",

        "copyright_prompt":
            "🖋 Введи імʼя автора або назву бренду:",

        "copyright_done":
            "✅ Copyright записано в EXIF.",

        "cleaned":
            "🛡 Метадані видалено з цієї копії.",
    },


    "en": {

        "welcome":
            "🧠 <b>AI EXIF Analyzer</b>\n\n"
            "📎 Send a photo.\n\n"
            "For best EXIF preservation, send it "
            "as an <b>uncompressed file</b>.\n\n"
            "🤖 AI description\n"
            "📷 EXIF\n"
            "🔬 forensic analysis\n"
            "🔐 SHA-256 / aHash\n"
            "📍 GPS\n"
            "🛡 metadata removal\n"
            "🏷 copyright\n"
            "🖼 information preview",

        "analyzing":
            "🔄 Analyzing new image...",

        "translating":
            "🌐 Translating AI description...",

        "preview":
            "🖼 Create preview",

        "clean":
            "🛡 Clean",

        "copyright":
            "🏷 Copyright",

        "maps":
            "🗺 Google Maps",

        "expired":
            "❌ This analysis is no longer available.",

        "copyright_prompt":
            "🖋 Enter author or brand:",

        "copyright_done":
            "✅ Copyright added to EXIF.",

        "cleaned":
            "🛡 Metadata removed from this copy.",
    },


    "ru": {

        "welcome":
            "🧠 <b>AI EXIF Analyzer</b>\n\n"
            "📎 Отправь фотографию.\n\n"
            "Лучше отправлять как "
            "<b>файл без сжатия</b>.\n\n"
            "🤖 AI-описание\n"
            "📷 EXIF\n"
            "🔬 forensic-анализ\n"
            "🔐 SHA-256 / aHash\n"
            "📍 GPS\n"
            "🛡 удаление метаданных\n"
            "🏷 copyright\n"
            "🖼 информационное превью",

        "analyzing":
            "🔄 Анализирую новое фото...",

        "translating":
            "🌐 Перевожу AI-описание...",

        "preview":
            "🖼 Создать превью",

        "clean":
            "🛡 Очистить",

        "copyright":
            "🏷 Copyright",

        "maps":
            "🗺 Google Maps",

        "expired":
            "❌ Этот анализ уже недоступен.",

        "copyright_prompt":
            "🖋 Введи имя автора или название бренда:",

        "copyright_done":
            "✅ Copyright записан в EXIF.",

        "cleaned":
            "🛡 Метаданные удалены из этой копии.",
    },
}


def get_language(user_id):

    return user_languages.get(
        user_id,
        "uk"
    )


def html(value):

    return escape(
        str(value)
    )


# =========================================================
# FSM
# =========================================================

class CopyrightStates(
    StatesGroup
):

    waiting_for_name = State()


# =========================================================
# AI
# =========================================================

def generate_caption(image):

    inputs = blip_processor(
        images=image,
        return_tensors="pt"
    )


    inputs = {

        key: value.to(
            AI_DEVICE
        )

        for key, value
        in inputs.items()
    }


    with torch.inference_mode():

        result = blip_model.generate(
            **inputs,
            max_new_tokens=50
        )


    return blip_processor.decode(
        result[0],
        skip_special_tokens=True
    ).strip()


def translate_text(
    text,
    language
):

    if language == "en":
        return text


    translator = get_translator(
        language
    )


    if not translator:
        return text


    tokenizer, model = translator


    inputs = tokenizer(
        text,
        return_tensors="pt",
        truncation=True
    )


    inputs = {

        key: value.to(
            TRANSLATION_DEVICE
        )

        for key, value
        in inputs.items()
    }


    with torch.inference_mode():

        output = model.generate(
            **inputs,
            max_new_tokens=80,
            num_beams=4
        )


    translated = tokenizer.decode(
        output[0],
        skip_special_tokens=True
    ).strip()


    print(
        f"🌐 {language.upper()}: "
        f"{translated}"
    )


    return translated


async def ensure_translation(
    user_id,
    analysis_id,
    language
):

    if language == "en":
        return


    data = get_analysis(
        user_id,
        analysis_id
    )


    if not data:
        return


    if language in data["ai_texts"]:
        return


    english = data[
        "ai_texts"
    ]["en"]


    translated = await asyncio.to_thread(
        translate_text,
        english,
        language
    )


    data["ai_texts"][
        language
    ] = translated


# =========================================================
# GPS
# =========================================================

def gps_degrees(value):

    try:

        return (
            float(value[0])
            + float(value[1]) / 60
            + float(value[2]) / 3600
        )

    except Exception:

        return None


def gps_ref(value):

    if isinstance(
        value,
        bytes
    ):

        return value.decode(
            errors="ignore"
        )


    return str(value)


# =========================================================
# FORENSICS
# =========================================================

def average_hash(image):

    gray = (
        image
        .convert("L")
        .resize(
            (8, 8),
            Image.Resampling.LANCZOS
        )
    )


    pixels = list(
        gray.getdata()
    )


    average = (
        sum(pixels)
        / len(pixels)
    )


    bits = "".join(

        "1"
        if value >= average
        else "0"

        for value in pixels
    )


    return (
        f"{int(bits, 2):016x}"
    )


def forensic_analysis(
    image,
    original_bytes,
    raw_image,
    exif
):

    rgb = image.convert(
        "RGB"
    )


    gray = rgb.convert(
        "L"
    )


    stat = ImageStat.Stat(
        gray
    )


    edges = gray.filter(
        ImageFilter.FIND_EDGES
    )


    edge_stat = ImageStat.Stat(
        edges
    )


    minimum, maximum = (
        gray.getextrema()
    )


    avg_rgb = (
        rgb.resize(
            (1, 1)
        ).getpixel(
            (0, 0)
        )
    )


    width, height = rgb.size

    divider = math.gcd(
        width,
        height
    )


    return {

        "sha256":
            hashlib.sha256(
                original_bytes
            ).hexdigest(),

        "ahash":
            average_hash(
                rgb
            ),

        "entropy":
            round(
                gray.entropy(),
                2
            ),

        "brightness":
            round(
                stat.mean[0],
                1
            ),

        "contrast":
            round(
                stat.stddev[0],
                1
            ),

        "sharpness":
            round(
                edge_stat.var[0],
                1
            ),

        "dynamic":
            maximum - minimum,

        "rgb":
            avg_rgb,

        "aspect":
            (
                f"{width // divider}:"
                f"{height // divider}"
            ),

        "exif_count":
            len(exif)
            if exif
            else 0,

        "dpi":
            raw_image.info.get(
                "dpi"
            ),

        "icc":
            bool(
                raw_image.info.get(
                    "icc_profile"
                )
            ),

        "alpha":
            "A" in image.getbands(),

        "jpeg_tables":
            bool(
                getattr(
                    raw_image,
                    "quantization",
                    None
                )
            ),
    }


# =========================================================
# REPORT
# =========================================================

def make_keyboard(
    user_id,
    analysis_id,
    language
):

    data = get_analysis(
        user_id,
        analysis_id
    )


    t = TEXTS[
        language
    ]


    rows = [

        [

            InlineKeyboardButton(
                text=(
                    f"{'✅ ' if language == 'uk' else ''}"
                    "🇺🇦 UA"
                ),
                callback_data=(
                    f"lang:uk:{analysis_id}"
                )
            ),

            InlineKeyboardButton(
                text=(
                    f"{'✅ ' if language == 'en' else ''}"
                    "🇬🇧 EN"
                ),
                callback_data=(
                    f"lang:en:{analysis_id}"
                )
            ),

            InlineKeyboardButton(
                text=(
                    f"{'✅ ' if language == 'ru' else ''}"
                    "🇷🇺 RU"
                ),
                callback_data=(
                    f"lang:ru:{analysis_id}"
                )
            ),

        ],

        [

            InlineKeyboardButton(
                text=t["preview"],
                callback_data=(
                    f"preview:{analysis_id}"
                )
            )

        ],

    ]


    if (
        data
        and data[
            "google_maps_url"
        ]
    ):

        rows.append(

            [

                InlineKeyboardButton(
                    text=t["maps"],
                    url=data[
                        "google_maps_url"
                    ]
                )

            ]

        )


    rows.append(

        [

            InlineKeyboardButton(
                text=t["clean"],
                callback_data=(
                    f"clean:{analysis_id}"
                )
            ),

            InlineKeyboardButton(
                text=t["copyright"],
                callback_data=(
                    f"copyright:{analysis_id}"
                )
            ),

        ]

    )


    return InlineKeyboardMarkup(
        inline_keyboard=rows
    )


def generate_report(
    user_id,
    analysis_id,
    language
):

    data = get_analysis(
        user_id,
        analysis_id
    )


    d = data["details"]
    f = data["forensics"]


    ai = (
        data["ai_texts"].get(
            language
        )
        or
        data["ai_texts"]["en"]
    )


    if language == "uk":

        title = "ЩО НА ЗОБРАЖЕННІ"
        technical = "ТЕХНІЧНИЙ АНАЛІЗ"
        camera = "КАМЕРА / EXIF"
        forensic = "ЦИФРОВИЙ FORENSIC"
        geo = "ГЕОЛОКАЦІЯ"

    elif language == "ru":

        title = "ЧТО НА ИЗОБРАЖЕНИИ"
        technical = "ТЕХНИЧЕСКИЙ АНАЛИЗ"
        camera = "КАМЕРА / EXIF"
        forensic = "ЦИФРОВОЙ FORENSIC"
        geo = "ГЕОЛОКАЦИЯ"

    else:

        title = "WHAT IS IN THE IMAGE"
        technical = "TECHNICAL ANALYSIS"
        camera = "CAMERA / EXIF"
        forensic = "DIGITAL FORENSICS"
        geo = "GEOLOCATION"


    report = (

        f"🤖 <b>{title}</b>\n"
        f"└ <code>{html(ai)}</code>\n\n"


        f"📊 <b>{technical}</b>\n"

        f" ├ 📐 "
        f"<code>{d['width']} × "
        f"{d['height']}</code> px "
        f"({d['mp']:.2f} MP)\n"

        f" ├ 🗂 "
        f"<code>{html(d['format'])}</code>\n"

        f" ├ 📏 Ratio: "
        f"<code>{f['aspect']}</code>\n"

        f" └ 💾 "
        f"<code>{d['size_mb']:.2f} MB</code>\n\n"


        f"📷 <b>{camera}</b>\n"

        f" ├ 🏭 Brand: "
        f"<code>{html(d['make'])}</code>\n"

        f" ├ 📱 Model: "
        f"<code>{html(d['model'])}</code>\n"

        f" ├ 🕒 Date: "
        f"<code>{html(d['date'])}</code>\n"

        f" ├ 👁 Lens: "
        f"<code>{html(d['lens'])}</code>\n"

        f" ├ 🔭 Focal: "
        f"<code>{html(d['focal'])}</code>\n"

        f" ├ 📸 ISO: "
        f"<code>{html(d['iso'])}</code>\n"

        f" ├ ⏱ Exposure: "
        f"<code>{html(d['exposure'])}</code>\n"

        f" ├ 🌕 Aperture: "
        f"<code>{html(d['aperture'])}</code>\n"

        f" ├ 💻 Software: "
        f"<code>{html(d['software'])}</code>\n"

        f" ├ 👤 Artist: "
        f"<code>{html(d['artist'])}</code>\n"

        f" └ 🔒 Copyright: "
        f"<code>{html(d['copyright'])}</code>\n\n"


        f"🔬 <b>{forensic}</b>\n"

        f" ├ 🔐 SHA-256:\n"
        f" │ <code>{f['sha256']}</code>\n"

        f" ├ 🧬 aHash: "
        f"<code>{f['ahash']}</code>\n"

        f" ├ 🎲 Entropy: "
        f"<code>{f['entropy']}</code>\n"

        f" ├ ☀️ Brightness: "
        f"<code>{f['brightness']}/255</code>\n"

        f" ├ 🌓 Contrast: "
        f"<code>{f['contrast']}</code>\n"

        f" ├ 🔎 Sharpness: "
        f"<code>{f['sharpness']}</code>\n"

        f" ├ 📈 Dynamic: "
        f"<code>{f['dynamic']}/255</code>\n"

        f" ├ 🎨 RGB: "
        f"<code>{f['rgb']}</code>\n"

        f" └ 🧾 EXIF tags: "
        f"<code>{f['exif_count']}</code>\n\n"


        f"📍 <b>{geo}</b>\n"
    )


    if data["coordinates"]:

        report += (
            f" └ <code>"
            f"{html(data['coordinates'])}"
            f"</code>"
        )

    else:

        report += " └ ❌"


    return report


# =========================================================
# PREVIEW
# =========================================================

def get_font(
    size,
    bold=False
):

    paths = [

        (
            "/System/Library/Fonts/"
            "Supplemental/Arial Bold.ttf"
            if bold
            else
            "/System/Library/Fonts/"
            "Supplemental/Arial.ttf"
        ),

        "/System/Library/Fonts/Helvetica.ttc",
    ]


    for path in paths:

        try:

            if os.path.exists(path):

                return ImageFont.truetype(
                    path,
                    size
                )

        except Exception:
            pass


    return ImageFont.load_default()


def create_preview(
    data
):

    source = Image.open(
        io.BytesIO(
            data["photo_bytes"]
        )
    ).convert(
        "RGB"
    )


    d = data["details"]
    f = data["forensics"]


    width = 1200
    height = 1500


    bg = ImageOps.fit(
        source,
        (
            width,
            height
        ),
        method=Image.Resampling.LANCZOS
    )


    bg = bg.filter(
        ImageFilter.GaussianBlur(
            28
        )
    ).convert(
        "RGBA"
    )


    overlay = Image.new(
        "RGBA",
        (
            width,
            height
        ),
        (
            0,
            0,
            0,
            145
        )
    )


    bg = Image.alpha_composite(
        bg,
        overlay
    )


    photo = ImageOps.contain(
        source,
        (
            900,
            720
        ),
        Image.Resampling.LANCZOS
    )


    x = (
        width
        - photo.width
    ) // 2

    y = 70


    bg.alpha_composite(
        photo.convert(
            "RGBA"
        ),
        (
            x,
            y
        )
    )


    draw = ImageDraw.Draw(
        bg
    )


    panel_y = (
        y
        + photo.height
        + 50
    )


    draw.rounded_rectangle(
        (
            70,
            panel_y,
            1130,
            1430
        ),
        radius=40,
        fill=(
            15,
            15,
            18,
            225
        )
    )


    title_font = get_font(
        46,
        True
    )

    normal_font = get_font(
        28
    )


    tx = 120
    ty = panel_y + 45


    draw.text(
        (
            tx,
            ty
        ),
        "PHOTO ANALYSIS",
        font=title_font,
        fill="white"
    )


    ty += 85


    lines = [

        f"Camera: {d['make']} {d['model']}",

        (
            f"Resolution: "
            f"{d['width']} × {d['height']} "
            f"({d['mp']:.2f} MP)"
        ),

        f"ISO: {d['iso']}",

        f"Exposure: {d['exposure']}",

        f"Aperture: {d['aperture']}",

        f"Date: {d['date']}",

        f"Artist: {d['artist']}",

        f"Copyright: {d['copyright']}",

        "",

        f"Entropy: {f['entropy']}",

        f"Brightness: {f['brightness']}",

        f"Sharpness: {f['sharpness']}",

        f"aHash: {f['ahash']}",

        f"SHA256: {f['sha256'][:28]}...",
    ]


    for line in lines:

        draw.text(
            (
                tx,
                ty
            ),
            line[:70],
            font=normal_font,
            fill="white"
        )

        ty += 47


    output = io.BytesIO()


    bg.convert(
        "RGB"
    ).save(
        output,
        format="JPEG",
        quality=94
    )


    return output.getvalue()


# =========================================================
# /START
# =========================================================

@dp.message(
    Command("start")
)
async def start(
    message: types.Message
):

    keyboard = InlineKeyboardMarkup(

        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="🇺🇦 Українська",
                    callback_data="startlang:uk"
                )
            ],

            [
                InlineKeyboardButton(
                    text="🇬🇧 English",
                    callback_data="startlang:en"
                )
            ],

            [
                InlineKeyboardButton(
                    text="🇷🇺 Русский",
                    callback_data="startlang:ru"
                )
            ],
        ]
    )


    await message.answer(

        "🌐 <b>"
        "Оберіть мову / "
        "Choose language / "
        "Выберите язык"
        "</b>",

        parse_mode="HTML",

        reply_markup=keyboard
    )


@dp.callback_query(
    F.data.startswith(
        "startlang:"
    )
)
async def start_language(
    callback: types.CallbackQuery
):

    language = callback.data.split(
        ":",
        1
    )[1]


    if language not in (
        "uk",
        "en",
        "ru"
    ):

        return


    user_languages[
        callback.from_user.id
    ] = language


    await callback.answer()


    await callback.message.edit_text(

        TEXTS[
            language
        ]["welcome"],

        parse_mode="HTML"
    )


# =========================================================
# IMAGE HANDLER
# =========================================================

@dp.message(
    F.photo | F.document
)
async def image_handler(
    message: types.Message
):

    user_id = message.from_user.id

    language = get_language(
        user_id
    )

    t = TEXTS[
        language
    ]


    analysis_id = (
        uuid.uuid4()
        .hex[:10]
    )


    # =====================================================
    # TELEGRAM FILE
    # =====================================================

    if message.photo:

        telegram_file = (
            message.photo[-1]
        )

        size = (
            telegram_file.file_size
            or 0
        )


    elif message.document:

        mime = (
            message.document.mime_type
            or ""
        )


        if not mime.startswith(
            "image/"
        ):

            await message.answer(
                "❌ Not an image"
            )

            return


        telegram_file = (
            message.document
        )

        size = (
            telegram_file.file_size
            or 0
        )


    else:
        return


    status = await message.answer(
        t["analyzing"]
    )


    try:

        # =================================================
        # DOWNLOAD
        # =================================================

        buffer = io.BytesIO()


        await bot.download(
            telegram_file,
            destination=buffer
        )


        original_bytes = (
            buffer.getvalue()
        )


        buffer.seek(0)


        raw = Image.open(
            buffer
        )

        raw.load()


        original_format = (
            raw.format
            or "Unknown"
        )


        exif = raw.getexif()


        image = ImageOps.exif_transpose(
            raw
        )


        rgb = image.convert(
            "RGB"
        )


        # =================================================
        # AI
        # =================================================

        ai_en = await asyncio.to_thread(
            generate_caption,
            rgb
        )


        print(
            f"\n🖼 {analysis_id}"
        )

        print(
            f"🤖 AI EN: {ai_en}"
        )


        # =================================================
        # DETAILS
        # =================================================

        width, height = rgb.size


        details = {

            "width":
                width,

            "height":
                height,

            "mp":
                (
                    width
                    * height
                    / 1_000_000
                ),

            "size_mb":
                size / 1024 / 1024,

            "format":
                original_format,

            "make":
                "Unknown",

            "model":
                "Unknown",

            "date":
                "Unknown",

            "software":
                "Unknown",

            "artist":
                "Unknown",

            "copyright":
                "Unknown",

            "iso":
                "Unknown",

            "exposure":
                "Unknown",

            "aperture":
                "Unknown",

            "focal":
                "Unknown",

            "lens":
                "Unknown",
        }


        coordinates = None
        google_maps_url = None


        # =================================================
        # BASE EXIF
        # =================================================

        if exif:

            for tag_id, value in exif.items():

                tag = ExifTags.TAGS.get(
                    tag_id,
                    tag_id
                )


                mapping = {

                    "Make":
                        "make",

                    "Model":
                        "model",

                    "DateTime":
                        "date",

                    "Software":
                        "software",

                    "Artist":
                        "artist",

                    "Copyright":
                        "copyright",
                }


                if tag in mapping:

                    details[
                        mapping[tag]
                    ] = str(
                        value
                    ).strip()


            # EXIF SUB IFD
            try:

                sub = exif.get_ifd(
                    ExifTags.IFD.Exif
                )

            except Exception:

                sub = {}


            if sub:

                if 34855 in sub:

                    details[
                        "iso"
                    ] = str(
                        sub[34855]
                    )


                if 33434 in sub:

                    try:

                        exposure = float(
                            sub[33434]
                        )


                        if exposure < 1:

                            details[
                                "exposure"
                            ] = (
                                f"1/"
                                f"{round(1 / exposure)} s"
                            )

                        else:

                            details[
                                "exposure"
                            ] = (
                                f"{exposure:g} s"
                            )

                    except Exception:
                        pass


                if 33437 in sub:

                    try:

                        details[
                            "aperture"
                        ] = (
                            f"f/"
                            f"{float(sub[33437]):g}"
                        )

                    except Exception:
                        pass


                if 37386 in sub:

                    try:

                        details[
                            "focal"
                        ] = (
                            f"{float(sub[37386]):g} mm"
                        )

                    except Exception:
                        pass


                if 42036 in sub:

                    details[
                        "lens"
                    ] = str(
                        sub[42036]
                    ).strip()


                if 36867 in sub:

                    details[
                        "date"
                    ] = str(
                        sub[36867]
                    ).strip()


            # GPS
            try:

                gps = exif.get_ifd(
                    ExifTags.IFD.GPSInfo
                )

            except Exception:

                gps = {}


            if gps:

                lat_raw = gps.get(2)
                lon_raw = gps.get(4)


                if lat_raw and lon_raw:

                    lat = gps_degrees(
                        lat_raw
                    )

                    lon = gps_degrees(
                        lon_raw
                    )


                    if (
                        lat is not None
                        and lon is not None
                    ):

                        if gps_ref(
                            gps.get(1)
                        ).upper() == "S":

                            lat = -lat


                        if gps_ref(
                            gps.get(3)
                        ).upper() == "W":

                            lon = -lon


                        coordinates = (
                            f"{lat:.7f}, "
                            f"{lon:.7f}"
                        )


                        google_maps_url = (

                            "https://www.google.com/"
                            "maps?q="
                            f"{lat:.7f},"
                            f"{lon:.7f}"

                        )


        # =================================================
        # FORENSICS
        # =================================================

        forensics = forensic_analysis(
            image,
            original_bytes,
            raw,
            exif
        )


        # =================================================
        # SAVE WORKING COPY
        # =================================================

        image_buffer = io.BytesIO()


        options = {

            "format":
                "JPEG",

            "quality":
                95,
        }


        if exif:

            try:

                exif[274] = 1

                options[
                    "exif"
                ] = exif.tobytes()

            except Exception:
                pass


        rgb.save(
            image_buffer,
            **options
        )


        # =================================================
        # NEW ANALYSIS CACHE
        # =================================================

        data = {

            "photo_bytes":
                image_buffer.getvalue(),

            "ai_texts": {
                "en": ai_en
            },

            "details":
                details,

            "forensics":
                forensics,

            "coordinates":
                coordinates,

            "google_maps_url":
                google_maps_url,
        }


        save_analysis(
            user_id,
            analysis_id,
            data
        )


        # =================================================
        # TRANSLATE THIS PHOTO
        # =================================================

        if language != "en":

            await status.edit_text(
                t["translating"]
            )


            await ensure_translation(
                user_id,
                analysis_id,
                language
            )


        # =================================================
        # SEND NEW MENU
        # =================================================

        report = generate_report(
            user_id,
            analysis_id,
            language
        )


        keyboard = make_keyboard(
            user_id,
            analysis_id,
            language
        )


        await status.delete()


        await message.answer(

            report,

            parse_mode="HTML",

            reply_markup=keyboard
        )


        # =================================================
        # COPYRIGHT ALERT
        # =================================================

        has_artist = (
            details["artist"]
            not in (
                "Unknown",
                "",
                None
            )
        )


        has_copyright = (
            details["copyright"]
            not in (
                "Unknown",
                "",
                None
            )
        )


        if (
            has_artist
            or has_copyright
        ):

            alert = (
                "⚠️ <b>COPYRIGHT METADATA FOUND</b>\n\n"
            )


            if has_artist:

                alert += (
                    f"👤 Artist: "
                    f"<code>"
                    f"{html(details['artist'])}"
                    f"</code>\n"
                )


            if has_copyright:

                alert += (
                    f"🔒 Copyright: "
                    f"<code>"
                    f"{html(details['copyright'])}"
                    f"</code>"
                )


            await message.answer(
                alert,
                parse_mode="HTML"
            )


    except UnidentifiedImageError:

        await status.edit_text(
            "❌ Image error"
        )


    except Exception as error:

        print(
            "❌ ERROR:",
            repr(error)
        )


        await status.edit_text(
            f"❌ Error:\n{error}"
        )


# =========================================================
# LANGUAGE CALLBACK
# =========================================================

@dp.callback_query(
    F.data.startswith(
        "lang:"
    )
)
async def language_callback(
    callback: types.CallbackQuery
):

    parts = callback.data.split(
        ":"
    )


    if len(parts) != 3:
        return


    language = parts[1]
    analysis_id = parts[2]

    user_id = callback.from_user.id


    data = get_analysis(
        user_id,
        analysis_id
    )


    if not data:

        await callback.answer(
            "❌ Analysis expired",
            show_alert=True
        )

        return


    user_languages[
        user_id
    ] = language


    await callback.answer(
        "🌐"
    )


    await ensure_translation(
        user_id,
        analysis_id,
        language
    )


    report = generate_report(
        user_id,
        analysis_id,
        language
    )


    keyboard = make_keyboard(
        user_id,
        analysis_id,
        language
    )


    await callback.message.edit_text(

        report,

        parse_mode="HTML",

        reply_markup=keyboard
    )


# =========================================================
# PREVIEW CALLBACK
# =========================================================

@dp.callback_query(
    F.data.startswith(
        "preview:"
    )
)
async def preview_callback(
    callback: types.CallbackQuery
):

    analysis_id = (
        callback.data.split(
            ":",
            1
        )[1]
    )


    user_id = (
        callback.from_user.id
    )


    data = get_analysis(
        user_id,
        analysis_id
    )


    if not data:

        await callback.answer(
            "❌ Analysis expired",
            show_alert=True
        )

        return


    await callback.answer(
        "🖼"
    )


    preview_bytes = (
        await asyncio.to_thread(
            create_preview,
            data
        )
    )


    file = BufferedInputFile(

        preview_bytes,

        filename=(
            f"analysis_"
            f"{analysis_id}.jpg"
        )
    )


    await bot.send_document(

        chat_id=callback.message.chat.id,

        document=file,

        caption=(
            f"🖼 Analysis "
            f"{analysis_id}"
        )
    )


# =========================================================
# CLEAN CALLBACK
# =========================================================

@dp.callback_query(
    F.data.startswith(
        "clean:"
    )
)
async def clean_callback(
    callback: types.CallbackQuery
):

    analysis_id = (
        callback.data.split(
            ":",
            1
        )[1]
    )


    user_id = (
        callback.from_user.id
    )


    data = get_analysis(
        user_id,
        analysis_id
    )


    if not data:

        await callback.answer(
            "❌ Analysis expired",
            show_alert=True
        )

        return


    language = get_language(
        user_id
    )


    await callback.answer(
        "🛡"
    )


    image = Image.open(
        io.BytesIO(
            data["photo_bytes"]
        )
    ).convert(
        "RGB"
    )


    output = io.BytesIO()


    image.save(
        output,
        format="JPEG",
        quality=95
    )


    file = BufferedInputFile(

        output.getvalue(),

        filename=(
            f"clean_"
            f"{analysis_id}.jpg"
        )
    )


    await bot.send_document(

        chat_id=callback.message.chat.id,

        document=file,

        caption=TEXTS[
            language
        ]["cleaned"]
    )


# =========================================================
# COPYRIGHT
# =========================================================

@dp.callback_query(
    F.data.startswith(
        "copyright:"
    )
)
async def copyright_start(
    callback: types.CallbackQuery,
    state: FSMContext
):

    analysis_id = (
        callback.data.split(
            ":",
            1
        )[1]
    )


    user_id = (
        callback.from_user.id
    )


    data = get_analysis(
        user_id,
        analysis_id
    )


    if not data:

        await callback.answer(
            "❌ Analysis expired",
            show_alert=True
        )

        return


    await state.set_state(
        CopyrightStates.waiting_for_name
    )


    await state.update_data(
        analysis_id=analysis_id
    )


    language = get_language(
        user_id
    )


    await callback.message.answer(

        TEXTS[
            language
        ]["copyright_prompt"]

    )


    await callback.answer()


@dp.message(
    CopyrightStates.waiting_for_name
)
async def copyright_save(
    message: types.Message,
    state: FSMContext
):

    user_id = (
        message.from_user.id
    )


    state_data = (
        await state.get_data()
    )


    analysis_id = (
        state_data.get(
            "analysis_id"
        )
    )


    data = get_analysis(
        user_id,
        analysis_id
    )


    if not data:

        await state.clear()

        await message.answer(
            "❌ Analysis expired"
        )

        return


    author = (
        message.text
        or ""
    ).strip()


    if not author:
        return


    image = Image.open(
        io.BytesIO(
            data["photo_bytes"]
        )
    ).convert(
        "RGB"
    )


    exif = image.getexif()


    exif[315] = author


    exif[33432] = (

        f"Copyright 2026 "
        f"{author}. "
        "All rights reserved."

    )


    output = io.BytesIO()


    image.save(

        output,

        format="JPEG",

        quality=95,

        exif=exif.tobytes()
    )


    await state.clear()


    file = BufferedInputFile(

        output.getvalue(),

        filename=(
            f"copyright_"
            f"{analysis_id}.jpg"
        )
    )


    language = get_language(
        user_id
    )


    await bot.send_document(

        chat_id=message.chat.id,

        document=file,

        caption=(

            f"{TEXTS[language]['copyright_done']}\n\n"

            f"👤 Artist: {author}"

        )
    )


# =========================================================
# MAIN
# =========================================================

async def main():

    print("")
    print("==============================")
    print("🚀 BOT v4 STARTED")
    print("==============================")
    print("")


    # На випадок, якщо раніше був webhook.
    await bot.delete_webhook(
        drop_pending_updates=False
    )


    try:

        await dp.start_polling(
            bot
        )


    finally:

        await bot.session.close()


if __name__ == "__main__":

    asyncio.run(
        main()
    )