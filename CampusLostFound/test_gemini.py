import os
from google import genai
from dotenv import load_dotenv


load_dotenv()


api_key = os.environ.get("GEMINI_API_KEY")


client = genai.Client(api_key=api_key)

# 4. Make the API request
response = client.models.generate_content(
    model="gemini-3-flash-preview", 
    contents="Person related to Epstein"
)

print(response.text)