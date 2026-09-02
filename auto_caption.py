import asyncio
import json
import re
import urllib.request
import ssl
import base64
import time
import os
from playwright.async_api import async_playwright

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL_NAME = "gemini-2.5-flash"

SYSTEM_INSTRUCTION = """You are an accurate, objective human annotator for Project Origami. 
Your primary task is to describe exactly what is visible in the provided image without guessing, storytelling, or using subjective/opinionated language."""

PROMPT = """Analyze the provided image and generate two captions based strictly on the following guidelines. Return ONLY a valid JSON object with keys "short_caption" and "detailed_caption".

=== GUIDELINES ===
1. Short Caption:
   - Exactly 1 sentence, 6 to 20 words (max 25).
   - Describe primary subject, action/pose, and immediate setting.
   - Absolutely NO opinions (e.g. vibrant, scenic, peaceful) or speed/timing words (e.g. slowly, quickly).
   - NEVER name living people.

2. Detailed Caption:
   - 1 to 3 sentences.
   - STRICT WORD COUNT: MUST be between 25 and 38 words (Hard maximum: 40 words).
   - Expand on spatial relationships, colors, clothing, background, and textures. Must fully agree with the short caption.

3. General Rules:
   - Numbers: Spell out counted objects as words ("three dogs"). Printed text/dates remain as digits.
   - Present tense only.

Return format:
{"short_caption": "...", "detailed_caption": "..."}"""

LAST_PROCESSED_URL = ""

async def get_captions_gemini(image_bytes):
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}

    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
        "contents": [
            {
                "parts": [
                    {"inline_data": {"mime_type": "image/jpeg", "data": base64_image}},
                    {"text": PROMPT}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "response_mime_type": "application/json"
        }
    }

    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    def _make_request():
        with urllib.request.urlopen(req, context=ssl_context) as resp:
            return json.loads(resp.read().decode('utf-8'))

    response_data = await asyncio.to_thread(_make_request)
    raw_content = response_data["candidates"][0]["content"]["parts"][0]["text"]
    cleaned_json = re.sub(r"```json\s*|\s*```", "", raw_content).strip()
    return json.loads(cleaned_json)

async def select_no_issue(task_frame):
    try:
        no_option = task_frame.locator("#image_error_group label").nth(1)
        if await no_option.is_visible():
            await no_option.click()
            print("Selected 'No (No Issue Identified)'.")
            await asyncio.sleep(0.3)
    except Exception as e:
        print(f"Radio selection notice: {e}")

async def click_skip_button(page, task_frame):
    try:
        skip_element = await task_frame.query_selector("span.action-label:has-text('Skip')")
        if not skip_element:
            skip_element = await page.query_selector("span.action-label:has-text('Skip')")
            
        if skip_element and await skip_element.is_visible():
            await skip_element.click()
            print("Successfully clicked 'Skip' button.")
            await asyncio.sleep(2.0)
            return True
    except Exception as err:
        print(f"Error attempting skip action: {err}")
    return False

async def process_task(page):
    global LAST_PROCESSED_URL
    task_frame = None
    img_url = None
    
    for frame in page.frames:
        try:
            img = await frame.query_selector("img#task-image")
            if img and await img.is_visible():
                src = await img.get_attribute("src")
                if src and src.startswith("http"):
                    task_frame = frame
                    img_url = src
                    break
        except Exception:
            continue

    if not task_frame or not img_url or img_url == LAST_PROCESSED_URL:
        return False

    print(f"\n--- New Task Detected ({img_url[-20:]}) ---")
    
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(img_url, headers={'User-Agent': 'Mozilla/5.0'})
    image_bytes = urllib.request.urlopen(req, context=ssl_context).read()

    await select_no_issue(task_frame)

    attempts = 0
    max_attempts = 3

    while attempts < max_attempts:
        attempts += 1
        print(f"Generating captions via Gemini 2.5 Flash (Attempt {attempts}/{max_attempts})...")
        
        try:
            captions = await get_captions_gemini(image_bytes)
        except Exception as api_err:
            print(f"API Call Failed: {api_err}")
            await asyncio.sleep(2)
            continue

        short_cap = captions.get("short_caption", "")
        detailed_cap = captions.get("detailed_caption", "")

        print(f"Short ({len(short_cap.split())} words): {short_cap}")
        print(f"Detailed ({len(detailed_cap.split())} words): {detailed_cap}")

        detailed_field = await task_frame.query_selector("textarea[placeholder*='detailed caption']")
        short_field = await task_frame.query_selector("textarea[placeholder*='short caption']")

        if not detailed_field or not short_field:
            textareas = await task_frame.query_selector_all("textarea")
            if len(textareas) >= 2:
                detailed_field = textareas[0]
                short_field = textareas[1]

        if short_field and detailed_field:
            await short_field.fill("")
            await short_field.fill(short_cap)
            await detailed_field.fill("")
            await detailed_field.fill(detailed_cap)
            print("Successfully populated text fields.")
        
        validate_btn = await task_frame.query_selector("button:has-text('Validate Captions')")
        if validate_btn:
            await validate_btn.click()
            print("Clicked 'Validate Captions'. Waiting for Submit button...")

        submit_found = False
        for _ in range(20):
            await asyncio.sleep(0.5)
            
            submit_btn = await task_frame.query_selector("button:has-text('Submit')")
            if not submit_btn:
                submit_btn = await page.query_selector("button:has-text('Submit')")

            if submit_btn and await submit_btn.is_visible() and await submit_btn.is_enabled():
                target_time_str = time.strftime("%H:%M:%S", time.localtime(time.time() + 840))
                print(f"Submit button visible! Holding submission for 14 minutes. Scheduled click time: {target_time_str}")
                
                await asyncio.sleep(840)
                
                await submit_btn.click()
                print("Submitted task successfully!")
                LAST_PROCESSED_URL = img_url
                submit_found = True
                await asyncio.sleep(3.0)
                return True

        if not submit_found:
            print("Validation failed or Submit button missing. Retrying caption generation...")

    print("Max retries reached (3 attempts). Triggering Skip button action...")
    skipped = await click_skip_button(page, task_frame)
    if skipped:
        LAST_PROCESSED_URL = img_url
    return False

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--blink-settings=imagesEnabled=true",
            ]
        )
        context = await browser.new_context()
        page = await context.new_page()

        print("Navigating to annotation page...")
        await page.goto(
            "https://dq0uw9vf3nt8l.cloudfront.net/annotate/6664f132-ce46-4fe7-81d4-d4146530d802?mode=annotation",
            wait_until="domcontentloaded"
        )

        print("Entering continuous execution loop...")
        
        while True:
            try:
                success = await process_task(page)
                if not success:
                    await asyncio.sleep(1.0)
            except Exception as e:
                print(f"Loop exception: {e}")
                await asyncio.sleep(2.0)

if __name__ == "__main__":
    asyncio.run(main())
