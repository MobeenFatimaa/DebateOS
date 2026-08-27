from flask import Flask, render_template, request, jsonify
from google import genai
from google.genai import types

app = Flask(__name__)

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/api/debate", methods=["POST"])
def debate():
    data = request.json
    api_key = data.get("api_key")
    topic = data.get("topic")
    user_stance = data.get("user_stance")
    chat_history = data.get("history", [])

    if not api_key or not topic or not user_stance:
        return jsonify({"error": "Missing required fields (API Key, Topic, or Stance)."}), 400

    ai_stance = "AGAINST (Con)" if user_stance == "FOR (Pro)" else "FOR (Pro)"

    # Construct the System Instruction for the Gemini agent
    system_instruction = (
        f"You are a skilled, highly persuasive debate opponent.\n"
        f"Topic: '{topic}'\n"
        f"User's Stance: {user_stance}\n"
        f"Your Stance: {ai_stance}\n\n"
        f"Rules:\n"
        f"1. Challenge the user's logic directly and highlight fallacies.\n"
        f"2. Firmly maintain your assigned stance ({ai_stance}).\n"
        f"3. Be polite and professional.\n"
        f"4. Keep responses under 150 words."
    )

    try:
        # Initialize client with user's key (stateless per request)
        client = genai.Client(api_key=api_key)

        # Convert simple JSON history into SDK Content objects
        contents = []
        for msg in chat_history:
            role = "user" if msg["role"] == "user" else "model"
            contents.append(
                types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=msg["content"])]
                )
            )

        # Call Gemini model
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.7,
            )
        )

        return jsonify({"reply": response.text})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5000)