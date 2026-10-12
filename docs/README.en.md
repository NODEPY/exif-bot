# EXIF Bot

A Telegram bot for photo metadata, local image captions and practical image tools.

[Українська](../README.md) · [Download source](https://github.com/NODEPY/exif-bot/releases/latest)

## Features

- Camera and EXIF details: model, lens, capture date, ISO, exposure, aperture and author fields.
- GPS coordinates from EXIF, with an optional Google Maps link.
- Local BLIP captions and Marian translation into Ukrainian or Russian.
- Dimensions, aspect ratio, brightness, contrast, edge-based sharpness and entropy.
- SHA-256 of received bytes and perceptual aHash.
- New JPEG copies with metadata removed or Artist/Copyright fields added.
- An image preview containing technical information.

Ukrainian, English and Russian are available. Some technical labels and error messages remain in English.

## Setup

Use macOS or Linux; Windows requires WSL because the current code uses `fcntl` for its process lock. The original local environment uses Python 3.14. PyTorch package availability varies with platform and Python version.

```sh
git clone https://github.com/NODEPY/exif-bot.git
cd exif-bot
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

Create a Telegram bot with [@BotFather](https://t.me/BotFather). Edit `.env` locally and replace the `BOT_TOKEN` placeholder. Never publish the real token.

```sh
python bot.py
```

Open the bot, send `/start`, choose a language and send a photo **as an uncompressed file** to preserve metadata. On macOS, `zsh start_bot.command` is an alternative launcher after creating `venv`.

## Models

- `Salesforce/blip-image-captioning-base`
- `Helsinki-NLP/opus-mt-en-uk`
- `Helsinki-NLP/opus-mt-en-ru`

BLIP loads at startup. Translation models load when first needed. Image inference selects Apple MPS, then CUDA, then CPU; translation uses CPU. The first run needs internet access to download model files. Models retain their own usage terms.

## Boundaries

Captions and numerical image metrics do not establish authenticity. GPS comes from EXIF, not visual location inference. Cleaning and copyright operations create re-encoded JPEG files; transparency is lost and the original Telegram file is unchanged. Copyright currently uses the year 2026.

The bot keeps up to five analyses per user in memory. Old buttons expire after a restart. A folder-level process lock prevents duplicate local instances.

## Data handling

Images travel through Telegram and are downloaded by the computer running the bot. Inference runs on that computer. Generated captions are printed to its console. Working JPEG copies remain in memory; model weights are cached by the model libraries. Opening a Maps link sends the embedded coordinates to Google.

The published source includes no tokens, personal images, local environments or model caches. Syntax and publication checks were performed; no live Telegram bot or full model startup was exercised during packaging.
