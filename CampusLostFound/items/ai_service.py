import os
import google.genai as genai
from django.core.cache import cache

def generate_notification_message(item, status):
    """
    Generate a dynamic notification message using Gemini AI.
    """
    # 1. Check Cache first to avoid duplicate API calls
    cache_key = f"ai_notif_{item.id}_{status}"
    cached_msg = cache.get(cache_key)
    if cached_msg:
        return cached_msg

    api_key = os.environ.get("GEMINI_API_KEY")
    
    # 2. Check if API Key exists
    if not api_key:
        return _generate_fallback_message(item, status)

    try:
        # 3. Configure Gemini
        genai.configure(api_key=api_key)
        
        # Use a highly capable but fast model
        model_name = os.getenv("GEMINI_MODEL_NAME", "gemini-1.5-pro")
        model = genai.GenerativeModel(model_name)

        # 4. Construct Prompt
        prompt = f"""
You are an assistant for a Campus Lost and Found system.

Generate a short, clear notification message for a user based on the item details and status.

Item Details:
Item Name: {item.name}
Category: {item.category}
Location: {item.location}
Description: {item.description}
Current Status: {status}

Rules:
- Keep the notification under 25 words.
- Make the message clear and helpful.
- Focus only on the important event.
- Do not include unnecessary explanations.

Generate only the notification message.
"""
        # 5. Call API
        response = model.generate_content(prompt)
        ai_message = response.text.strip()
        
        if not ai_message:
            raise ValueError("Empty response from Gemini")
            
        # 6. Cache the successful result (e.g. for 24 hours)
        cache.set(cache_key, ai_message, timeout=86400)
        return ai_message

    except Exception as e:
        print(f"Gemini API Error: {e}")
        # Always return a fallback if AI fails, never crash
        return _generate_fallback_message(item, status)


def _generate_fallback_message(item, status):
    """
    Hardcoded fallback messages in case the AI is unavailable or no API key is set.
    """
    messages = {
        'lost_reported': f"A new lost item '{item.name}' has been reported at {item.location}.",
        'found_reported': f"A new found item '{item.name}' has been submitted at {item.location}.",
        'match_detected': f"A possible match for your lost '{item.name}' has been found.",
        'claim_submitted': f"A claim request has been submitted for the '{item.name}'.",
        'claim_approved': f"Your claim for the '{item.name}' has been approved.",
        'claim_rejected': f"Your claim for the '{item.name}' was not approved.",
        'resolved': f"The status of '{item.name}' has been marked as resolved."
    }
    
    # Return specific fallback or a generic one
    return messages.get(status, f"Notice regarding the item '{item.name}': Status changed to {status}.")
