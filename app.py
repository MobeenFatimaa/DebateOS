from datetime import datetime
from flask import Flask, jsonify, render_template, request
from flask_sqlalchemy import SQLAlchemy
from google import genai
from google.genai import types
import json

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///debates.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)


# --- Database Models ---
class Debate(db.Model):
  id = db.Column(db.Integer, primary_key=True)
  topic = db.Column(db.String(255), nullable=False)
  stance = db.Column(db.String(50), nullable=False)
  created_at = db.Column(db.DateTime, default=datetime.utcnow)
  final_score = db.Column(db.Integer, default=50)
  status = db.Column(db.String(50), default="Active")
  arguments = db.relationship(
      "Argument", backref="debate", lazy=True, cascade="all, delete-orphan"
  )


class Argument(db.Model):
  id = db.Column(db.Integer, primary_key=True)
  debate_id = db.Column(db.Integer, db.ForeignKey("debate.id"), nullable=False)
  round_num = db.Column(db.Integer, nullable=False)
  user_argument = db.Column(db.Text, nullable=False)
  ai_response = db.Column(db.Text, nullable=False)
  score = db.Column(db.Integer, default=50)
  analysis = db.Column(db.JSON, nullable=True)


with app.app_context():
  db.create_all()


@app.route("/")
def index():
  return render_template("index.html")


@app.route("/debate")
def debate_page():
  return render_template("debate.html")


# --- History & Transcript API Routes ---
@app.route("/api/debates", methods=["GET"])
def get_debates():
  all_debates = Debate.query.order_by(Debate.id.desc()).all()
  return jsonify([{
      "id": d.id,
      "topic": d.topic,
      "rounds": len(d.arguments),
      "final_score": d.final_score,
      "created_at": d.created_at.strftime("%b %d, %Y"),
  } for d in all_debates])


@app.route("/api/debates/<int:debate_id>", methods=["GET"])
def get_debate_detail(debate_id):
  d = Debate.query.get_or_404(debate_id)
  return jsonify({
      "topic": d.topic,
      "stance": d.stance,
      "final_score": d.final_score,
      "arguments": [{
          "round_num": arg.round_num,
          "user_argument": arg.user_argument,
          "ai_response": arg.ai_response,
          "score": arg.score,
          "analysis": arg.analysis,
      } for arg in d.arguments],
  })


@app.route("/api/debate", methods=["POST"])
def debate():
  data = request.json
  api_key = data.get("api_key")
  topic = data.get("topic")
  user_stance = data.get("user_stance")
  chat_history = data.get("history", [])
  debate_id = data.get("debate_id")

  if not api_key or not topic or not user_stance:
    return jsonify({"error": "Missing required parameters."}), 400

  ai_stance = "AGAINST (Con)" if user_stance == "FOR (Pro)" else "FOR (Pro)"

  system_instruction = (
      f"You are ARIA (Adversarial Reasoning Intelligence), an elite, highly"
      f" persuasive, and uncompromising debate opponent.\nTopic: '{topic}'\nUser's"
      f" Stance: {user_stance}\nYour Stance: {ai_stance}\n\nRules:\n1."
      f" Challenge the user's logic directly, expose weak reasoning, and defend"
      f" your assigned stance ({ai_stance}).\n2. Keep counter-arguments sharp"
      f" and concise (under 150 words).\n3. Return your response in valid JSON"
      f" format with this exact structure:\n{{\n  \"core_claim\":"
      f" \"Identified core claim of user's argument (short phrase)\",\n "
      f" \"assumptions\": \"Identified hidden or explicit assumption\",\n "
      f" \"logical_gaps\": \"Identified logical gap or fallacy\",\n "
      f" \"counter_evidence\": \"Identified counter-evidence or angle\",\n "
      f" \"reasoning_tags\": [\"Appeal to authority\", \"Generalization\","
      f" \"Strong causal claim\"],\n  \"challenge_reasons\": [\n   "
      f" {{\"title\": \"Unsupported assumption\", \"detail\": \"Explanation of"
      f" why an assumption lacked grounding.\"}},\n    {{\"title\": \"Missing"
      f" evidence\", \"detail\": \"Explanation of empirical data or citations"
      f" lacking in the claim.\"}},\n    {{\"title\": \"Weak causal"
      f" relationship\", \"detail\": \"Explanation of the causal flaw between"
      f" premise and conclusion.\"}},\n    {{\"title\": \"Alternative"
      f" explanation exists\", \"detail\": \"Explanation of competing"
      f" variables or alternate outcomes.\"}}\n  ],\n  \"reply\":"
      f" \"Your powerful counter-argument text here\",\n  \"metrics\": {{\n"
      f"    \"argument_strength\": <int 0-100>,\n    \"evidence\": <int"
      f" 0-100>,\n    \"logical_consistency\": <int 0-100>,\n   "
      f" \"relevance\": <int 0-100>,\n    \"ai_score\": <int 0-100>,\n   "
      f" \"user_score\": <int 0-100>\n  }}\n}}"
  )

  try:
    client = genai.Client(api_key=api_key)
    contents = []
    for msg in chat_history:
      role = "user" if msg["role"] == "user" else "model"
      contents.append(
          types.Content(
              role=role, parts=[types.Part.from_text(text=msg["content"])]
          )
      )

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.7,
            response_mime_type="application/json",
        ),
    )

    result = json.loads(response.text)

    # --- Database Persistence Logic ---
    user_msg_text = (
        chat_history[-1]["content"] if chat_history else "Opening Statement"
    )
    current_score = (
        result.get("metrics", {}).get("user_score", 50)
    )

    if not debate_id:
      new_debate = Debate(topic=topic, stance=user_stance, final_score=current_score)
      db.session.add(new_debate)
      db.session.commit()
      debate_id = new_debate.id
    else:
      current_debate = Debate.query.get(debate_id)
      if current_debate:
        current_debate.final_score = current_score
        db.session.commit()

    # Calculate round number based on existing arguments for this debate
    existing_args_count = Argument.query.filter_by(debate_id=debate_id).count()
    round_num = existing_args_count + 1

    new_arg = Argument(
        debate_id=debate_id,
        round_num=round_num,
        user_argument=user_msg_text,
        ai_response=result.get("reply", ""),
        score=current_score,
        analysis=result,
    )
    db.session.add(new_arg)
    db.session.commit()

    result["debate_id"] = debate_id
    return jsonify(result)

  except Exception as e:
    return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
  app.run(debug=True, port=5000)
