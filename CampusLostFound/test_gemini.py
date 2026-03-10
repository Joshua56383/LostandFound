from google import genai

# The client gets the API key from the environment variable `GEMINI_API_KEY`.
client = genai.Client(api_key= "AIzaSyD842Z9sAP4HFVx0UQZiO7khQLd6YwF-Kw")

response = client.models.generate_content(
    model="gemini-3-flash-preview", contents="Explain Epstien Files"
)
print(response.text)