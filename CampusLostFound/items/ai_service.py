import os
import google.generativeai as genai
from django.core.cache import cache
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure Gemini once
api_key = os.getenv("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)


def generate_notification_message(item, status):
    """
    Generate a dynamic notification message using Gemini AI.
    """

    # 1. Check cache
    cache_key = f"ai_notif_{item.id}_{status}"
    cached_msg = cache.get(cache_key)
    if cached_msg:
        return cached_msg

    # 2. If no API key → fallback
    if not api_key:
        return _generate_fallback_message(item, status)

    try:
        # 3. Create model
        model_name = os.getenv("GEMINI_MODEL_NAME", "gemini-1.5-flash")
        model = genai.GenerativeModel(model_name)

        # 4. Prompt
        prompt = f"""
You are an AI assistant for a Lost and Found Management System.

Write a short notification message (1–2 sentences).

Item Name: {item.name}
Category: {item.category}
Location: {item.location}
Description: {item.description}
Status: {status}
Date Reported: {item.date_reported}

Generate only the notification message.
"""

        # 5. Generate content
        response = model.generate_content(prompt)

        ai_message = response.text.strip()

        if not ai_message:
            raise ValueError("Empty response from Gemini")

        # 6. Cache result (24 hours)
        cache.set(cache_key, ai_message, timeout=86400)

        return ai_message

    except Exception as e:
        print(f"Gemini API Error: {e}")
        return _generate_fallback_message(item, status)


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