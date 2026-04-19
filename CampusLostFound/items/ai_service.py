import os
from google import genai
from google.genai import types
from django.core.cache import cache
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure Gemini client once
api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key) if api_key else None


def generate_notification_message(item, status):
    """
    Generate a dynamic notification message using Gemini AI.
    """

    # 1. Check cache
    cache_key = f"ai_notif_{item.id}_{status}"
    cached_msg = cache.get(cache_key)
    if cached_msg:
        return cached_msg

    # 2. If no API key or client → fallback
    if not client:
        return _generate_fallback_message(item, status)

    try:
        # 3. Model name
        model_name = os.getenv("GEMINI_MODEL_NAME", "gemini-1.5-flash")

        # 4. Prompt
        prompt = f"""
        You are the Recovery Hub Concierge for DMMMSU. 
        Your goal is to provide clear, empathetic, and professional updates to students about their lost or found items.
        
        Write a warm, concise notification (max 150 characters).
        
        Item: {item.name}
        Category: {item.category}
        Location: {item.location}
        Status Context: {status}
        
        Guidelines:
        - Be human, not robotic.
        - Use campus-friendly language.
        - Encourage the student.
        """

        # 5. Generate content using new SDK
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
        )

        ai_message = response.text.strip()

        if not ai_message:
            raise ValueError("Empty response from Gemini")

        # 6. Cache result (24 hours)
        cache.set(cache_key, ai_message, timeout=86400)

        return ai_message

    except Exception as e:
        print(f"Gemini API Error: {e}")
        return _generate_fallback_message(item, status)


def extract_image_tags(image_path):
    """
    Extract AI tags from an item image using Gemini Vision.
    """
    if not client or not image_path or not os.path.exists(image_path):
        return ""

    try:
        # 1. Clean model name
        model_name = os.getenv("GEMINI_MODEL_NAME", "gemini-1.5-flash").strip()
        # The new SDK adds 'models/' automatically if missing, but sometimes 
        # double 'models/models/' happens if not careful. We pass it clean.
        
        if not image_path or not os.path.exists(image_path):
            return ""

        with open(image_path, "rb") as f:
            image_bytes = f.read()

        # Detect MIME type from extension
        ext = os.path.splitext(image_path)[-1].lower()
        mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
        mime_type = mime_map.get(ext, "image/jpeg")

        response = client.models.generate_content(
            model=model_name,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                "List 5-10 concise keywords describing this item for a lost-and-found system. Separate with commas. No sentences.",
            ],
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
        'lost_reported': f"Your report for '{item.name}' is now live. We're keeping a close watch on the registry for you!",
        'found_reported': f"Success! '{item.name}' has been safely reported. Our matching engine is already at work.",
        'match_detected': f"Exciting news! We've found a potential match for your lost '{item.name}'. Click to see if it's yours.",
        'claim_submitted': f"Your claim for '{item.name}' has been received. Our staff will review it shortly.",
        'claim_approved': f"Great news! Your claim for '{item.name}' was approved. You can now get your Handover Pass.",
        'claim_rejected': f"Update: Your claim for '{item.name}' couldn't be verified at this time. Please contact staff for help.",
        'resolved': f"Mission accomplished! '{item.name}' has been officially returned to its owner.",
        'item_approved': f"Your report for '{item.name}' is approved and visible to the campus community.",
        'item_rejected': f"We couldn't approve your report for '{item.name}'. Please ensure your description is clear and try again.",
    }

    return messages.get(
        status,
        f"Notice regarding the item '{item.name}': Status changed to {status}."
    )