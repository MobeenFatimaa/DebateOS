from datetime import datetime

from flask import Flask, jsonify, render_template, request
from flask_sqlalchemy import SQLAlchemy

from services.aria_engine import analyze_argument
from services.scoring import (
    calculate_overall_score,
    get_performance_level,
)


app = Flask(__name__)

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///debates.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# ============================================================
# DATABASE MODELS
# ============================================================

class Debate(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    topic = db.Column(
        db.String(255),
        nullable=False
    )

    stance = db.Column(
        db.String(50),
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    final_score = db.Column(
        db.Integer,
        default=50
    )

    status = db.Column(
        db.String(50),
        default="Active"
    )

    duration = db.Column(
        db.Integer,
        default=0
    )

    winner = db.Column(
        db.String(50),
        default="Pending"
    )

    difficulty = db.Column(
        db.String(50),
        default="Advanced"
    )

    arguments = db.relationship(
        "Argument",
        backref="debate",
        lazy=True,
        cascade="all, delete-orphan"
    )


class Argument(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    debate_id = db.Column(
        db.Integer,
        db.ForeignKey("debate.id"),
        nullable=False
    )

    round_num = db.Column(
        db.Integer,
        nullable=False
    )

    user_argument = db.Column(
        db.Text,
        nullable=False
    )

    ai_response = db.Column(
        db.Text,
        nullable=False
    )

    score = db.Column(
        db.Integer,
        default=50
    )

    argument_strength = db.Column(
        db.Integer,
        default=50
    )

    evidence_score = db.Column(
        db.Integer,
        default=50
    )

    logic_score = db.Column(
        db.Integer,
        default=50
    )

    relevance_score = db.Column(
        db.Integer,
        default=50
    )

    persuasiveness_score = db.Column(
        db.Integer,
        default=50
    )

    analysis = db.Column(
        db.JSON,
        nullable=True
    )


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

with app.app_context():
    db.create_all()


# ============================================================
# PAGE ROUTES
# ============================================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/debate")
def debate_page():
    return render_template("debate.html")


# ============================================================
# DEBATE HISTORY
# ============================================================

@app.route("/api/debates", methods=["GET"])
def get_debates():

    all_debates = (
        Debate.query
        .order_by(Debate.id.desc())
        .all()
    )

    return jsonify([
        {
            "id": debate.id,

            "topic": debate.topic,

            "stance": debate.stance,

            "rounds": len(debate.arguments),

            "final_score": debate.final_score,

            "status": debate.status,

            "difficulty": debate.difficulty,

            "winner": debate.winner,

            "created_at": (
                debate.created_at.strftime("%b %d, %Y")
                if debate.created_at
                else ""
            ),
        }

        for debate in all_debates
    ])


# ============================================================
# SINGLE DEBATE / TRANSCRIPT
# ============================================================

@app.route(
    "/api/debates/<int:debate_id>",
    methods=["GET"]
)
def get_debate_detail(debate_id):

    debate = Debate.query.get_or_404(
        debate_id
    )

    return jsonify({

        "id": debate.id,

        "topic": debate.topic,

        "stance": debate.stance,

        "final_score": debate.final_score,

        "status": debate.status,

        "winner": debate.winner,

        "difficulty": debate.difficulty,

        "duration": debate.duration,

        "created_at": (
            debate.created_at.isoformat()
            if debate.created_at
            else None
        ),

        "arguments": [

            {
                "id": argument.id,

                "round_num": argument.round_num,

                "user_argument": argument.user_argument,

                "ai_response": argument.ai_response,

                "score": argument.score,

                "argument_strength":
                    argument.argument_strength,

                "evidence":
                    argument.evidence_score,

                "logical_consistency":
                    argument.logic_score,

                "relevance":
                    argument.relevance_score,

                "persuasiveness":
                    argument.persuasiveness_score,

                "analysis":
                    argument.analysis,
            }

            for argument in debate.arguments
        ],
    })


# ============================================================
# MAIN DEBATE API
# ============================================================

@app.route(
    "/api/debate",
    methods=["POST"]
)
def debate():

    data = request.get_json(
        silent=True
    ) or {}

    api_key = data.get("api_key")

    topic = (
        data.get("topic")
        or ""
    ).strip()

    user_stance = data.get(
        "user_stance"
    )

    chat_history = data.get(
        "history",
        []
    )

    debate_id = data.get(
        "debate_id"
    )

    round_number = data.get(
        "round_number"
    )

    # --------------------------------------------------------
    # VALIDATION
    # --------------------------------------------------------

    if not api_key:

        return jsonify({
            "error": "Gemini API key is missing."
        }), 400

    if not topic:

        return jsonify({
            "error": "Debate topic is required."
        }), 400

    if not user_stance:

        return jsonify({
            "error": "Your debate stance is required."
        }), 400

    if not chat_history:

        return jsonify({
            "error": "Your argument is required."
        }), 400

    try:

        # ----------------------------------------------------
        # DETERMINE ROUND
        # ----------------------------------------------------

        if round_number:

            try:
                round_number = int(
                    round_number
                )

            except (TypeError, ValueError):

                round_number = 1

        elif debate_id:

            existing_count = (
                Argument.query
                .filter_by(
                    debate_id=debate_id
                )
                .count()
            )

            round_number = (
                existing_count + 1
            )

        else:

            round_number = 1

        round_number = max(
            1,
            min(5, round_number)
        )

        # ----------------------------------------------------
        # AI ANALYSIS
        # ----------------------------------------------------

        result = analyze_argument(

            api_key=api_key,

            topic=topic,

            user_stance=user_stance,

            round_number=round_number,

            chat_history=chat_history,
        )

        # ----------------------------------------------------
        # USER ARGUMENT
        # ----------------------------------------------------

        user_msg_text = (
            chat_history[-1].get(
                "content",
                "Opening Statement"
            )
        )

        # ----------------------------------------------------
        # CALCULATE SCORE
        # ----------------------------------------------------

        metrics = result.get(
            "metrics",
            {}
        )

        overall_score = (
            calculate_overall_score(
                metrics
            )
        )

        # Keep the AI's score visible
        # but use our normalized score
        # for the database.

        metrics["user_score"] = (
            overall_score
        )

        result["metrics"] = metrics

        result["performance_level"] = (
            get_performance_level(
                overall_score
            )
        )

        # ----------------------------------------------------
        # CREATE OR UPDATE DEBATE
        # ----------------------------------------------------

        if not debate_id:

            new_debate = Debate(

                topic=topic,

                stance=user_stance,

                final_score=overall_score,

                status="Active",

                difficulty="Advanced",
            )

            db.session.add(
                new_debate
            )

            db.session.commit()

            debate_id = (
                new_debate.id
            )

        else:

            current_debate = (
                Debate.query.get(
                    debate_id
                )
            )

            if not current_debate:

                return jsonify({
                    "error":
                        "Debate session not found."
                }), 404

            current_debate.final_score = (
                overall_score
            )

            # Automatically mark complete
            # after round 5.

            if round_number >= 5:

                current_debate.status = (
                    "Completed"
                )

                if overall_score >= 50:

                    current_debate.winner = (
                        "User"
                    )

                else:

                    current_debate.winner = (
                        "ARIA"
                    )

            db.session.commit()

        # ----------------------------------------------------
        # SAVE ARGUMENT
        # ----------------------------------------------------

        existing_args_count = (
            Argument.query
            .filter_by(
                debate_id=debate_id
            )
            .count()
        )

        saved_round = (
            existing_args_count + 1
        )

        new_argument = Argument(

            debate_id=debate_id,

            round_num=saved_round,

            user_argument=user_msg_text,

            ai_response=result.get(
                "reply",
                ""
            ),

            score=overall_score,

            argument_strength=metrics.get(
                "argument_strength",
                50
            ),

            evidence_score=metrics.get(
                "evidence",
                50
            ),

            logic_score=metrics.get(
                "logical_consistency",
                50
            ),

            relevance_score=metrics.get(
                "relevance",
                50
            ),

            persuasiveness_score=metrics.get(
                "persuasiveness",
                50
            ),

            analysis=result,
        )

        db.session.add(
            new_argument
        )

        db.session.commit()

        # ----------------------------------------------------
        # RESPONSE
        # ----------------------------------------------------

        result["debate_id"] = (
            debate_id
        )

        result["round_number"] = (
            round_number
        )

        result["round_name"] = (
            {
                1: "Opening Statement",
                2: "Counter Argument",
                3: "Rebuttal",
                4: "Cross Examination",
                5: "Closing Statement",
            }.get(
                round_number,
                "Debate"
            )
        )

        return jsonify(
            result
        )

    except Exception as e:

        db.session.rollback()

        print(
            "ARIA ERROR:",
            repr(e)
        )

        return jsonify({

            "error":
                str(e)

        }), 500


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route(
    "/api/health",
    methods=["GET"]
)
def health():

    return jsonify({

        "status": "online",

        "service": "DebateOS",

        "engine": "ARIA",

        "version": "2.0",

    })


# ============================================================
# APPLICATION START
# ============================================================

if __name__ == "__main__":

    app.run(
        debug=True,
        port=5000
    )
