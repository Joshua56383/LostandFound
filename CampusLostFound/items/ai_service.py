import os
from google import genai
from openai import OpenAI
from django.core.cache import cache
from dotenv import load_dotenv
from PIL import Image
import sys

# Load environment variables
load_dotenv()

# Configure APIs
gemini_api_key = os.getenv("GEMINI_API_KEY")
gemini_client = None
if gemini_api_key:
    gemini_client = genai.Client(api_key=gemini_api_key)

openai_api_key = os.getenv("OPENAI_API_KEY")
client = None
if openai_api_key:
    client = OpenAI(api_key=openai_api_key)


def generate_notification_message(item, status):
    """
    Generate a dynamic notification message using AI (OpenAI primary, Gemini fallback).
    """

    # 1. Check if we're running tests to avoid API limits
    import sys
    if 'test' in sys.argv:
        return _generate_fallback_message(item, status)

    # 1b. Check cache
    cache_key = f"ai_notif_{item.id}_{status}"
    cached_msg = cache.get(cache_key)
    if cached_msg:
        return cached_msg

    # 2. Try OpenAI
    if client:
        try:
            model_name = os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini")
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": "You are an AI assistant for a Lost and Found Management System. Write a short notification message (1–2 sentences)."},
                    {"role": "user", "content": f"Item Name: {item.name}\nCategory: {item.category}\nLocation: {item.location}\nDescription: {item.description}\nStatus: {status}\nDate Reported: {item.date_reported}\n\nGenerate only the notification message."}
                ],
                max_tokens=100
            )
            ai_message = response.choices[0].message.content.strip()
            if ai_message:
                cache.set(cache_key, ai_message, timeout=86400)
                return ai_message
        except Exception as e:
            print(f"OpenAI API Error: {e}")

    # 3. Try Gemini fallback
    if gemini_client:
        try:
            model_name = os.getenv("GEMINI_MODEL_NAME", "gemini-2.0-flash")
            prompt = f"You are an AI assistant for a Lost and Found Management System. Write a short notification message (1–2 sentences).\n\nItem Name: {item.name}\nCategory: {item.category}\nLocation: {item.location}\nDescription: {item.description}\nStatus: {status}\nDate Reported: {item.date_reported}\n\nGenerate only the notification message."
            
            response = gemini_client.models.generate_content(
                model=model_name,
                contents=prompt
            )
            ai_message = response.text.strip()
            if ai_message:
                cache.set(cache_key, ai_message, timeout=86400)
                return ai_message
        except Exception as e:
            if "429" in str(e):
                print(f"Gemini API Quota Exceeded (429): {e}")
            else:
                print(f"Gemini API Error: {e}")

    # 4. Final fallback
    return _generate_fallback_message(item, status)


def extract_image_tags(image_path):
    """
    Extract visual tags from an image using Gemini Vision.
    """
    if 'test' in sys.argv:
        return "test, image, tags"

    if not gemini_client:
        return ""

    try:
        model_name = os.getenv("GEMINI_MODEL_NAME", "gemini-2.0-flash")
        
        with Image.open(image_path) as img:
            prompt = "Identify the main object, color, brand, and any distinctive features in this image. Return 5 to 10 comma-separated keywords (e.g. 'black, leather, wallet, expensive')."
            
            response = gemini_client.models.generate_content(
                model=model_name,
                contents=[prompt, img]
            )
            
            return response.text.strip()
    except Exception as e:
        print(f"Gemini Vision Error: {e}")
        return ""


def _generate_fallback_message(item, status):
    """
    Hardcoded fallback messages if AI fails.
    """

    messages = {
        'lost_reported': f"A new lost item '{item.name}' has been reported at {item.location}.",
        'found_reported': f"A new found item '{item.name}' has been submitted at {item.location}.",
        'match_detected': f"A possible match for your lost '{item.name}' has been found.",
        'claim_submitted': f"A claim request has been submitted for the '{item.name}'.",
        'claim_approved': f"Your claim for the '{item.name}' has been approved.",
        'claim_rejected': f"Your claim for the '{item.name}' was not approved.",
        'resolved': f"The status of '{item.name}' has been marked as resolved.",
        'item_approved': f"Your reported item '{item.name}' has been approved and is now visible.",
        'item_rejected': f"Your reported item '{item.name}' was not approved by the admin.",
    }

    return messages.get(
        status,
        f"Notice regarding the item '{item.name}': Status changed to {status}."
    )