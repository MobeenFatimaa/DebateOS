from datetime import datetime
import json
import os
import re

from flask import Flask, jsonify, render_template, request, Response
from flask_sqlalchemy import SQLAlchemy
from google import genai
from google.genai import types


# ============================================================
# APP CONFIGURATION
# ============================================================

app = Flask(__name__)

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///debates.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# ============================================================
# CONSTANTS
# ============================================================

MAX_TOPIC_LENGTH = 255
MAX_ARGUMENT_LENGTH = 5000
MAX_HISTORY_MESSAGES = 12

TOTAL_ROUNDS = 5

VALID_STANCES = {
    "FOR (Pro)",
    "AGAINST (Con)"
}

ROUND_NAMES = {
    1: "Opening Statement",
    2: "Counter Argument",
    3: "Rebuttal",
    4: "Cross Examination",
    5: "Closing Statement"
}

# ------------------------------------------------------------
# Debate preparation settings
# ------------------------------------------------------------

PREPARATION_TIME_SECONDS = 30

VALID_DIFFICULTIES = {
    "Beginner",
    "Intermediate",
    "Advanced",
    "Expert"
}

DEFAULT_DIFFICULTY = "Intermediate"

# ------------------------------------------------------------
# Predefined topic categories
# ------------------------------------------------------------

TOPIC_CATEGORIES = {
    "Technology": [
        "Artificial Intelligence should replace some human jobs.",
        "Social media does more harm than good.",
        "AI should be regulated by governments.",
        "Students should be allowed to use AI for academic work.",
        "Technology has made people less socially connected."
    ],

    "Education": [
        "University education should be free.",
        "Exams are not an effective way to measure intelligence.",
        "Online education is better than traditional education.",
        "Homework should be abolished.",
        "Students should choose their own subjects."
    ],

    "Society": [
        "Freedom of speech should have limits.",
        "Social media platforms should be responsible for misinformation.",
        "Modern society is becoming too dependent on technology.",
        "Success depends more on hard work than luck.",
        "Privacy is more important than security."
    ],

    "Science": [
        "Humanity should invest more money in space exploration.",
        "Nuclear energy is necessary for the future.",
        "Genetic engineering should be allowed on humans.",
        "Climate change should be treated as the world's highest priority.",
        "Scientific research should be publicly funded."
    ],

    "Business": [
        "Remote work is better than office work.",
        "Companies should prioritize employees over profits.",
        "A four-day work week should become standard.",
        "Entrepreneurship should be taught in schools.",
        "Artificial intelligence will create more jobs than it destroys."
    ],

    "Ethics": [
        "Privacy should outweigh national security.",
        "Animal testing should be banned.",
        "Wealthy individuals should pay significantly higher taxes.",
        "Lying is acceptable when it prevents harm.",
        "Governments should have the right to monitor online activity."
    ]
}


# ============================================================
# DATABASE MODELS
# ============================================================

class Debate(db.Model):

    __tablename__ = "debate"

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

    # --------------------------------------------------------
    # New session fields
    # --------------------------------------------------------

    difficulty = db.Column(
        db.String(50),
        default=DEFAULT_DIFFICULTY
    )

    preparation_seconds = db.Column(
        db.Integer,
        default=PREPARATION_TIME_SECONDS
    )

    started_at = db.Column(
        db.DateTime,
        nullable=True
    )

    completed_at = db.Column(
        db.DateTime,
        nullable=True
    )

    arguments = db.relationship(
        "Argument",
        backref="debate",
        lazy=True,
        cascade="all, delete-orphan"
    )


class Argument(db.Model):

    __tablename__ = "argument"

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
# HELPER FUNCTIONS
# ============================================================

def clean_text(value):
    """
    Normalize incoming text safely.
    """

    if value is None:
        return ""

    return str(value).strip()


def clamp_score(value, default=50):
    """
    Force a score into the 0-100 range.
    """

    try:

        value = int(value)

        return max(
            0,
            min(100, value)
        )

    except (ValueError, TypeError):

        return default


def average(values):
    """
    Safely calculate average.
    """

    if not values:
        return 0

    return round(
        sum(values) / len(values),
        1
    )


def extract_json(text):
    """
    Safely parse JSON returned by Gemini.
    """

    if not text:

        raise ValueError(
            "AI returned an empty response."
        )

    text = text.strip()

    # Remove markdown fences
    text = re.sub(
        r"^```(?:json)?\s*",
        "",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r"\s*```$",
        "",
        text
    )

    text = text.strip()

    # First attempt
    try:

        return json.loads(text)

    except json.JSONDecodeError:
        pass

    # Attempt to extract JSON object
    match = re.search(
        r"\{.*\}",
        text,
        flags=re.DOTALL
    )

    if match:

        try:

            return json.loads(
                match.group(0)
            )

        except json.JSONDecodeError:
            pass

    raise ValueError(
        "The AI returned invalid JSON."
    )


def normalize_ai_result(result):
    """
    Normalize Gemini's response so the frontend
    always receives the expected structure.
    """

    if not isinstance(result, dict):

        result = {}

    metrics = result.get(
        "metrics",
        {}
    )

    if not isinstance(metrics, dict):

        metrics = {}

    reasoning_tags = result.get(
        "reasoning_tags",
        []
    )

    if not isinstance(
        reasoning_tags,
        list
    ):

        reasoning_tags = []

    challenge_reasons = result.get(
        "challenge_reasons",
        []
    )

    if not isinstance(
        challenge_reasons,
        list
    ):

        challenge_reasons = []

    cleaned_tags = []

    for tag in reasoning_tags:

        tag = clean_text(tag)

        if tag:

            cleaned_tags.append(
                tag
            )

    cleaned_reasons = []

    for reason in challenge_reasons:

        if not isinstance(
            reason,
            dict
        ):

            continue

        cleaned_reasons.append({

            "title":
                clean_text(
                    reason.get(
                        "title"
                    )
                ) or "Reason",

            "detail":
                clean_text(
                    reason.get(
                        "detail"
                    )
                ) or "No explanation provided."

        })

    normalized_metrics = {

        "argument_strength":
            clamp_score(
                metrics.get(
                    "argument_strength"
                )
            ),

        "evidence":
            clamp_score(
                metrics.get(
                    "evidence"
                )
            ),

        "logical_consistency":
            clamp_score(
                metrics.get(
                    "logical_consistency"
                )
            ),

        "relevance":
            clamp_score(
                metrics.get(
                    "relevance"
                )
            ),

        "ai_score":
            clamp_score(
                metrics.get(
                    "ai_score"
                )
            ),

        "user_score":
            clamp_score(
                metrics.get(
                    "user_score"
                )
            )
    }

    return {

        "core_claim":
            clean_text(
                result.get(
                    "core_claim"
                )
            ),

        "assumptions":
            clean_text(
                result.get(
                    "assumptions"
                )
            ),

        "logical_gaps":
            clean_text(
                result.get(
                    "logical_gaps"
                )
            ),

        "counter_evidence":
            clean_text(
                result.get(
                    "counter_evidence"
                )
            ),

        "reasoning_tags":
            cleaned_tags,

        "challenge_reasons":
            cleaned_reasons,

        "reply":
            clean_text(
                result.get(
                    "reply"
                )
            ),

        "metrics":
            normalized_metrics
    }


# ============================================================
# GEMINI CLIENT
# ============================================================

def get_gemini_client(api_key=None):

    api_key = clean_text(
        api_key
    )

    # Frontend key
    if not api_key:

        api_key = os.getenv(
            "GEMINI_API_KEY",
            ""
        ).strip()

    if not api_key:

        raise ValueError(
            "Gemini API key is not configured."
        )

    return genai.Client(
        api_key=api_key
    )


# ============================================================
# REQUEST VALIDATION
# ============================================================

def validate_debate_request(data):

    if not isinstance(
        data,
        dict
    ):

        return None, (
            "Invalid request body."
        )

    topic = clean_text(
        data.get("topic")
    )

    stance = clean_text(
        data.get("user_stance")
    )

    api_key = clean_text(
        data.get("api_key")
    )

    if not topic:

        return None, (
            "Debate topic is required."
        )

    if len(topic) > MAX_TOPIC_LENGTH:

        return None, (
            f"Debate topic cannot exceed "
            f"{MAX_TOPIC_LENGTH} characters."
        )

    if stance not in VALID_STANCES:

        return None, (
            "Invalid stance. Choose "
            "FOR (Pro) or AGAINST (Con)."
        )

    history = data.get(
        "history",
        []
    )

    if not isinstance(
        history,
        list
    ):

        return None, (
            "History must be a list."
        )

    history = history[
        -MAX_HISTORY_MESSAGES:
    ]

    cleaned_history = []

    for message in history:

        if not isinstance(
            message,
            dict
        ):

            continue

        role = message.get(
            "role"
        )

        content = clean_text(
            message.get(
                "content"
            )
        )

        if role not in {
            "user",
            "assistant",
            "model"
        }:

            continue

        if not content:

            continue

        if len(content) > MAX_ARGUMENT_LENGTH:

            content = content[
                :MAX_ARGUMENT_LENGTH
            ]

        cleaned_history.append({

            "role":
                role,

            "content":
                content

        })

    return {

        "api_key":
            api_key,

        "topic":
            topic,

        "stance":
            stance,

        "history":
            cleaned_history,

        "debate_id":
            data.get(
                "debate_id"
            )

    }, None


# ============================================================
# START DEBATE REQUEST VALIDATION
# ============================================================

def validate_start_request(data):

    if not isinstance(
        data,
        dict
    ):

        return None, (
            "Invalid request body."
        )

    topic = clean_text(
        data.get("topic")
    )

    stance = clean_text(
        data.get("user_stance")
    )

    difficulty = clean_text(
        data.get(
            "difficulty",
            DEFAULT_DIFFICULTY
        )
    )

    if not topic:

        return None, (
            "Please select or enter a debate topic."
        )

    if len(topic) > MAX_TOPIC_LENGTH:

        return None, (
            f"Topic cannot exceed "
            f"{MAX_TOPIC_LENGTH} characters."
        )

    if stance not in VALID_STANCES:

        return None, (
            "Please select a valid stance."
        )

    if difficulty not in VALID_DIFFICULTIES:

        difficulty = DEFAULT_DIFFICULTY

    return {

        "topic":
            topic,

        "stance":
            stance,

        "difficulty":
            difficulty

    }, None


# ============================================================
# ARIA SYSTEM INSTRUCTION
# ============================================================

def build_system_instruction(
    topic,
    user_stance,
    round_num
):

    ai_stance = (
        "AGAINST (Con)"
        if user_stance == "FOR (Pro)"
        else "FOR (Pro)"
    )

    round_name = ROUND_NAMES.get(
        round_num,
        "Debate Round"
    )

    return f"""
You are ARIA
(Adversarial Reasoning Intelligence).

You are an elite AI debate opponent and critical-thinking
training system.

Your job is NOT simply to disagree.

Your job is to intelligently challenge the user's reasoning,
identify weaknesses, and force the user to construct stronger
arguments.

============================================================
DEBATE INFORMATION
============================================================

Topic:
"{topic}"

User Stance:
{user_stance}

ARIA Stance:
{ai_stance}

Current Round:
{round_num} of {TOTAL_ROUNDS}

Round Type:
{round_name}

============================================================
ROUND OBJECTIVE
============================================================

Adapt your response to the current round.

ROUND 1 — OPENING STATEMENT
Evaluate the user's initial position.

ROUND 2 — COUNTER ARGUMENT
Attack the strongest parts of the user's opening argument.

ROUND 3 — REBUTTAL
Identify whether the user's rebuttal successfully answers
ARIA's previous objections.

ROUND 4 — CROSS EXAMINATION
Expose contradictions, assumptions, missing evidence and
weak logical connections.

ROUND 5 — CLOSING STATEMENT
Evaluate the user's strongest overall case and challenge
remaining weaknesses.

============================================================
ANALYSIS REQUIREMENTS
============================================================

You must:

1. Identify the user's central claim.
2. Identify hidden assumptions.
3. Detect logical gaps.
4. Detect possible logical fallacies.
5. Evaluate evidence quality.
6. Identify missing evidence.
7. Provide counter-evidence or an alternative perspective.
8. Challenge the argument directly.
9. Defend your assigned stance.
10. Remain educational.
11. Never personally attack the user.
12. Never invent statistics.
13. Never invent studies.
14. Never fabricate citations.
15. Clearly distinguish known evidence from reasoning.

============================================================
RESPONSE STYLE
============================================================

Your counterargument should be:

- Sharp
- Persuasive
- Specific
- Educational
- Evidence-aware
- Concise

Keep the reply under 150 words.

============================================================
REASONING TAGS
============================================================

Use useful tags when appropriate.

Examples:

- Generalization
- Unsupported assumption
- Appeal to authority
- False dilemma
- Straw man
- Circular reasoning
- Correlation vs causation
- Slippery slope
- Missing evidence
- Strong causal claim
- Emotional reasoning
- Ad hominem
- False equivalence

Only use tags that actually apply.

============================================================
CHALLENGE REASONS
============================================================

Provide several concise reasons explaining why
the user's reasoning can be challenged.

============================================================
SCORING
============================================================

Score the USER'S CURRENT ARGUMENT.

argument_strength:
Overall quality and persuasiveness.

evidence:
Quality and strength of supporting evidence.

logical_consistency:
Whether the reasoning follows logically.

relevance:
How directly the argument addresses the topic.

user_score:
Overall quality of the user's argument.

ai_score:
Strength of ARIA's counterargument.

All scores must be integers from 0 to 100.

============================================================
REQUIRED JSON
============================================================

Return ONLY valid JSON.

{{
    "core_claim":
        "Short description of the user's central claim",

    "assumptions":
        "Important hidden or explicit assumption",

    "logical_gaps":
        "Logical weakness, fallacy, or reasoning problem",

    "counter_evidence":
        "Counter-evidence, alternative perspective, or missing consideration",

    "reasoning_tags": [
        "Generalization",
        "Missing evidence"
    ],

    "challenge_reasons": [
        {{
            "title":
                "Unsupported assumption",

            "detail":
                "Explain why the assumption is insufficiently supported."
        }},
        {{
            "title":
                "Missing evidence",

            "detail":
                "Explain what evidence is missing."
        }},
        {{
            "title":
                "Weak causal relationship",

            "detail":
                "Explain any problematic causal reasoning."
        }},
        {{
            "title":
                "Alternative explanation exists",

            "detail":
                "Explain another plausible interpretation."
        }}
    ],

    "reply":
        "Your powerful counterargument.",

    "metrics": {{
        "argument_strength": 0,
        "evidence": 0,
        "logical_consistency": 0,
        "relevance": 0,
        "ai_score": 0,
        "user_score": 0
    }}
}}
"""


# ============================================================
# PAGE ROUTES
# ============================================================

@app.route("/")
def index():

    return render_template(
        "index.html"
    )


@app.route("/debate")
def debate_page():

    return render_template(
        "debate.html"
    )


# ============================================================
# TOPIC API
# ============================================================

@app.route(
    "/api/topics",
    methods=["GET"]
)
def get_topics():

    try:

        return jsonify({

            "success":
                True,

            "categories":
                TOPIC_CATEGORIES,

            "total_topics":
                sum(
                    len(topics)
                    for topics
                    in TOPIC_CATEGORIES.values()
                )

        })

    except Exception:

        app.logger.exception(
            "Failed to load topics"
        )

        return jsonify({

            "error":
                "Unable to load debate topics."

        }), 500


# ============================================================
# START DEBATE SESSION
# ============================================================

@app.route(
    "/api/debates/start",
    methods=["POST"]
)
def start_debate():

    try:

        data = request.get_json(
            silent=True
        )

        validated, error = (
            validate_start_request(
                data
            )
        )

        if error:

            return jsonify({

                "success":
                    False,

                "error":
                    error

            }), 400

        topic = validated[
            "topic"
        ]

        stance = validated[
            "stance"
        ]

        difficulty = validated[
            "difficulty"
        ]

        # ----------------------------------------------------
        # Prevent duplicate active session for exact topic
        # ----------------------------------------------------

        existing = (
            Debate.query
            .filter_by(
                topic=topic,
                stance=stance,
                status="Active"
            )
            .order_by(
                Debate.id.desc()
            )
            .first()
        )

        if existing:

            return jsonify({

                "success":
                    True,

                "existing":
                    True,

                "message":
                    "An active debate session already exists.",

                "debate_id":
                    existing.id,

                "topic":
                    existing.topic,

                "stance":
                    existing.stance,

                "difficulty":
                    existing.difficulty
                    or DEFAULT_DIFFICULTY,

                "status":
                    existing.status,

                "total_rounds":
                    TOTAL_ROUNDS,

                "current_round":
                    len(
                        existing.arguments
                    ) + 1,

                "preparation_seconds":
                    existing.preparation_seconds
                    or PREPARATION_TIME_SECONDS,

                "round_names":
                    ROUND_NAMES

            })

        # ----------------------------------------------------
        # Create new debate
        # ----------------------------------------------------

        debate = Debate(

            topic=
                topic,

            stance=
                stance,

            difficulty=
                difficulty,

            preparation_seconds=
                PREPARATION_TIME_SECONDS,

            final_score=
                50,

            status=
                "Preparing",

            started_at=
                None,

            completed_at=
                None
        )

        db.session.add(
            debate
        )

        db.session.commit()

        return jsonify({

            "success":
                True,

            "existing":
                False,

            "message":
                "Debate session created successfully.",

            "debate_id":
                debate.id,

            "topic":
                debate.topic,

            "stance":
                debate.stance,

            "difficulty":
                debate.difficulty,

            "status":
                debate.status,

            "total_rounds":
                TOTAL_ROUNDS,

            "current_round":
                1,

            "round_name":
                ROUND_NAMES[1],

            "preparation_seconds":
                PREPARATION_TIME_SECONDS,

            "round_names":
                ROUND_NAMES

        }), 201

    except Exception:

        db.session.rollback()

        app.logger.exception(
            "Failed to start debate"
        )

        return jsonify({

            "success":
                False,

            "error":
                "Unable to start debate session."

        }), 500


# ============================================================
# CONFIRM DEBATE IS READY / START TIMER
# ============================================================

@app.route(
    "/api/debates/<int:debate_id>/begin",
    methods=["POST"]
)
def begin_debate(
    debate_id
):

    try:

        debate = db.session.get(
            Debate,
            debate_id
        )

        if not debate:

            return jsonify({

                "success":
                    False,

                "error":
                    "Debate not found."

            }), 404

        if debate.status == "Completed":

            return jsonify({

                "success":
                    False,

                "error":
                    "This debate has already been completed."

            }), 400

        if debate.status == "Active":

            return jsonify({

                "success":
                    True,

                "message":
                    "Debate is already active.",

                "debate_id":
                    debate.id,

                "status":
                    debate.status,

                "current_round":
                    len(
                        debate.arguments
                    ) + 1,

                "round_name":
                    ROUND_NAMES.get(
                        len(
                            debate.arguments
                        ) + 1,
                        "Debate Round"
                    )

            })

        debate.status = "Active"

        debate.started_at = (
            datetime.utcnow()
        )

        db.session.commit()

        return jsonify({

            "success":
                True,

            "message":
                "Debate has started.",

            "debate_id":
                debate.id,

            "status":
                debate.status,

            "started_at":
                debate.started_at.isoformat(),

            "current_round":
                1,

            "round_name":
                ROUND_NAMES[1],

            "total_rounds":
                TOTAL_ROUNDS,

            "preparation_seconds":
                debate.preparation_seconds
                or PREPARATION_TIME_SECONDS

        })

    except Exception:

        db.session.rollback()

        app.logger.exception(
            "Failed to begin debate %s",
            debate_id
        )

        return jsonify({

            "success":
                False,

            "error":
                "Unable to begin debate."

        }), 500


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route(
    "/api/health",
    methods=["GET"]
)
def health():

    try:

        db.session.execute(
            db.text(
                "SELECT 1"
            )
        )

        database_status = "connected"

    except Exception:

        database_status = "error"

    return jsonify({

        "status":
            "online",

        "application":
            "DebateOS",

        "engine":
            "ARIA",

        "database":
            database_status,

        "gemini_server_key_configured":
            bool(
                os.getenv(
                    "GEMINI_API_KEY"
                )
            ),

        "version":
            "4.0.0"

    })


# ============================================================
# GET ALL DEBATES
# ============================================================

@app.route(
    "/api/debates",
    methods=["GET"]
)
def get_debates():

    try:

        debates = (
            Debate.query
            .order_by(
                Debate.id.desc()
            )
            .all()
        )

        response = []

        for debate in debates:

            response.append({

                "id":
                    debate.id,

                "topic":
                    debate.topic,

                "stance":
                    debate.stance,

                "difficulty":
                    debate.difficulty
                    or DEFAULT_DIFFICULTY,

                "rounds":
                    len(
                        debate.arguments
                    ),

                "total_rounds":
                    TOTAL_ROUNDS,

                "final_score":
                    debate.final_score,

                "status":
                    debate.status,

                "created_at":
                    (
                        debate.created_at.strftime(
                            "%b %d, %Y"
                        )
                        if debate.created_at
                        else ""
                    ),

                "started_at":
                    (
                        debate.started_at.isoformat()
                        if debate.started_at
                        else None
                    ),

                "completed_at":
                    (
                        debate.completed_at.isoformat()
                        if debate.completed_at
                        else None
                    )

            })

        return jsonify(
            response
        )

    except Exception:

        app.logger.exception(
            "Failed to load debates"
        )

        return jsonify({

            "error":
                "Unable to load debate history."

        }), 500


# ============================================================
# GET SINGLE DEBATE
# ============================================================

@app.route(
    "/api/debates/<int:debate_id>",
    methods=["GET"]
)
def get_debate_detail(
    debate_id
):

    try:

        debate = db.session.get(
            Debate,
            debate_id
        )

        if not debate:

            return jsonify({

                "error":
                    "Debate not found."

            }), 404

        arguments = sorted(

            debate.arguments,

            key=lambda x:
                x.round_num

        )

        return jsonify({

            "id":
                debate.id,

            "topic":
                debate.topic,

            "stance":
                debate.stance,

            "difficulty":
                debate.difficulty
                or DEFAULT_DIFFICULTY,

            "final_score":
                debate.final_score,

            "status":
                debate.status,

            "total_rounds":
                TOTAL_ROUNDS,

            "completed_rounds":
                len(arguments),

            "current_round":
                min(
                    len(arguments) + 1,
                    TOTAL_ROUNDS
                ),

            "created_at":
                (
                    debate.created_at.isoformat()
                    if debate.created_at
                    else None
                ),

            "started_at":
                (
                    debate.started_at.isoformat()
                    if debate.started_at
                    else None
                ),

            "completed_at":
                (
                    debate.completed_at.isoformat()
                    if debate.completed_at
                    else None
                ),

            "arguments": [

                {

                    "id":
                        argument.id,

                    "round_num":
                        argument.round_num,

                    "round_name":
                        ROUND_NAMES.get(
                            argument.round_num,
                            "Debate Round"
                        ),

                    "user_argument":
                        argument.user_argument,

                    "ai_response":
                        argument.ai_response,

                    "score":
                        argument.score,

                    "analysis":
                        argument.analysis

                }

                for argument in arguments

            ]

        })

    except Exception:

        app.logger.exception(
            "Failed to load debate %s",
            debate_id
        )

        return jsonify({

            "error":
                "Unable to load debate."

        }), 500


# ============================================================
# PHASE 3 — DEBATE ANALYTICS
# ============================================================

@app.route(
    "/api/debates/<int:debate_id>/analytics",
    methods=["GET"]
)
def get_debate_analytics(
    debate_id
):

    try:

        debate = db.session.get(
            Debate,
            debate_id
        )

        if not debate:

            return jsonify({

                "error":
                    "Debate not found."

            }), 404

        arguments = sorted(

            debate.arguments,

            key=lambda x:
                x.round_num

        )

        user_scores = [

            clamp_score(
                arg.score
            )

            for arg in arguments

        ]

        ai_scores = []

        argument_strength = []
        evidence_scores = []
        logic_scores = []
        relevance_scores = []

        round_data = []

        for arg in arguments:

            analysis = (

                arg.analysis

                if isinstance(
                    arg.analysis,
                    dict
                )

                else {}

            )

            metrics = analysis.get(
                "metrics",
                {}
            )

            ai_score = clamp_score(
                metrics.get(
                    "ai_score"
                )
            )

            strength = clamp_score(
                metrics.get(
                    "argument_strength"
                )
            )

            evidence = clamp_score(
                metrics.get(
                    "evidence"
                )
            )

            logic = clamp_score(
                metrics.get(
                    "logical_consistency"
                )
            )

            relevance = clamp_score(
                metrics.get(
                    "relevance"
                )
            )

            ai_scores.append(
                ai_score
            )

            argument_strength.append(
                strength
            )

            evidence_scores.append(
                evidence
            )

            logic_scores.append(
                logic
            )

            relevance_scores.append(
                relevance
            )

            round_data.append({

                "round":
                    arg.round_num,

                "round_name":
                    ROUND_NAMES.get(
                        arg.round_num,
                        "Debate Round"
                    ),

                "user_score":
                    clamp_score(
                        arg.score
                    ),

                "ai_score":
                    ai_score,

                "argument_strength":
                    strength,

                "evidence":
                    evidence,

                "logical_consistency":
                    logic,

                "relevance":
                    relevance

            })

        strongest_round = None
        weakest_round = None

        if round_data:

            strongest_round = max(

                round_data,

                key=lambda x:
                    x["user_score"]

            )

            weakest_round = min(

                round_data,

                key=lambda x:
                    x["user_score"]

            )

        # Improvement calculation

        improvement = 0

        if len(user_scores) >= 2:

            improvement = round(

                user_scores[-1]
                - user_scores[0],

                1

            )

        # Trend

        trend = "stable"

        if improvement > 5:

            trend = "improving"

        elif improvement < -5:

            trend = "declining"

        return jsonify({

            "debate_id":
                debate.id,

            "topic":
                debate.topic,

            "stance":
                debate.stance,

            "difficulty":
                debate.difficulty
                or DEFAULT_DIFFICULTY,

            "status":
                debate.status,

            "total_rounds":
                len(arguments),

            "completed_rounds":
                len(arguments),

            "average_user_score":
                average(
                    user_scores
                ),

            "average_ai_score":
                average(
                    ai_scores
                ),

            "average_argument_strength":
                average(
                    argument_strength
                ),

            "average_evidence":
                average(
                    evidence_scores
                ),

            "average_logical_consistency":
                average(
                    logic_scores
                ),

            "average_relevance":
                average(
                    relevance_scores
                ),

            "opening_score":
                (
                    user_scores[0]
                    if user_scores
                    else 0
                ),

            "final_score":
                debate.final_score,

            "improvement":
                improvement,

            "trend":
                trend,

            "strongest_round":
                strongest_round,

            "weakest_round":
                weakest_round,

            "rounds":
                round_data

        })

    except Exception:

        app.logger.exception(
            "Failed to calculate analytics"
        )

        return jsonify({

            "error":
                "Unable to calculate debate analytics."

        }), 500


# ============================================================
# PHASE 3 — GLOBAL STATISTICS
# ============================================================

@app.route(
    "/api/stats",
    methods=["GET"]
)
def get_global_stats():

    try:

        debates = Debate.query.all()

        arguments = Argument.query.all()

        completed = [

            d for d in debates

            if d.status == "Completed"

        ]

        scores = [

            clamp_score(
                d.final_score
            )

            for d in debates

        ]

        argument_scores = [

            clamp_score(
                a.score
            )

            for a in arguments

        ]

        return jsonify({

            "total_debates":
                len(debates),

            "completed_debates":
                len(completed),

            "active_debates":
                len(debates)
                - len(completed),

            "total_arguments":
                len(arguments),

            "average_debate_score":
                average(
                    scores
                ),

            "average_argument_score":
                average(
                    argument_scores
                ),

            "best_debate_score":
                max(scores)
                if scores
                else 0,

            "lowest_debate_score":
                min(scores)
                if scores
                else 0

        })

    except Exception:

        app.logger.exception(
            "Failed to calculate global statistics"
        )

        return jsonify({

            "error":
                "Unable to calculate statistics."

        }), 500


# ============================================================
# DELETE DEBATE
# ============================================================

@app.route(
    "/api/debates/<int:debate_id>",
    methods=["DELETE"]
)
def delete_debate(
    debate_id
):

    try:

        debate = db.session.get(
            Debate,
            debate_id
        )

        if not debate:

            return jsonify({

                "error":
                    "Debate not found."

            }), 404

        db.session.delete(
            debate
        )

        db.session.commit()

        return jsonify({

            "success":
                True,

            "message":
                "Debate deleted successfully.",

            "debate_id":
                debate_id

        })

    except Exception:

        db.session.rollback()

        app.logger.exception(
            "Failed to delete debate"
        )

        return jsonify({

            "error":
                "Unable to delete debate."

        }), 500


# ============================================================
# EXPORT DEBATE
# ============================================================

@app.route(
    "/api/debates/<int:debate_id>/export",
    methods=["GET"]
)
def export_debate(
    debate_id
):

    try:

        debate = db.session.get(
            Debate,
            debate_id
        )

        if not debate:

            return jsonify({

                "error":
                    "Debate not found."

            }), 404

        arguments = sorted(

            debate.arguments,

            key=lambda x:
                x.round_num

        )

        export_data = {

            "application":
                "DebateOS",

            "engine":
                "ARIA",

            "exported_at":
                datetime.utcnow().isoformat(),

            "debate": {

                "id":
                    debate.id,

                "topic":
                    debate.topic,

                "stance":
                    debate.stance,

                "difficulty":
                    debate.difficulty
                    or DEFAULT_DIFFICULTY,

                "status":
                    debate.status,

                "final_score":
                    debate.final_score,

                "created_at":
                    (
                        debate.created_at.isoformat()
                        if debate.created_at
                        else None
                    ),

                "started_at":
                    (
                        debate.started_at.isoformat()
                        if debate.started_at
                        else None
                    ),

                "completed_at":
                    (
                        debate.completed_at.isoformat()
                        if debate.completed_at
                        else None
                    ),

                "rounds": [

                    {

                        "round":
                            arg.round_num,

                        "round_name":
                            ROUND_NAMES.get(
                                arg.round_num,
                                "Debate Round"
                            ),

                        "user_argument":
                            arg.user_argument,

                        "aria_response":
                            arg.ai_response,

                        "score":
                            arg.score,

                        "analysis":
                            arg.analysis

                    }

                    for arg in arguments

                ]

            }

        }

        filename = (

            f"debate_{debate.id}_"

            f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

            ".json"

        )

        return Response(

            json.dumps(

                export_data,

                indent=4,

                ensure_ascii=False

            ),

            mimetype=
                "application/json",

            headers={

                "Content-Disposition":
                    f'attachment; filename="{filename}"'

            }

        )

    except Exception:

        app.logger.exception(
            "Failed to export debate"
        )

        return jsonify({

            "error":
                "Unable to export debate."

        }), 500


# ============================================================
# MAIN DEBATE AI ENDPOINT
# ============================================================

@app.route(
    "/api/debate",
    methods=["POST"]
)
def debate():

    # --------------------------------------------------------
    # 1. Parse request
    # --------------------------------------------------------

    try:

        data = request.get_json(
            silent=True
        )

        validated, error = (
            validate_debate_request(
                data
            )
        )

        if error:

            return jsonify({

                "error":
                    error

            }), 400

    except Exception:

        return jsonify({

            "error":
                "Invalid request."

        }), 400

    api_key = validated[
        "api_key"
    ]

    topic = validated[
        "topic"
    ]

    user_stance = validated[
        "stance"
    ]

    chat_history = validated[
        "history"
    ]

    debate_id = validated[
        "debate_id"
    ]


    # --------------------------------------------------------
    # 2. Validate user argument
    # --------------------------------------------------------

    if not chat_history:

        return jsonify({

            "error":
                "No argument was provided."

        }), 400

    last_message = (
        chat_history[-1]
    )

    user_msg_text = clean_text(

        last_message.get(
            "content"
        )

    )

    if not user_msg_text:

        return jsonify({

            "error":
                "Your argument cannot be empty."

        }), 400

    # Remove frontend round prefix

    user_msg_text = re.sub(

        r"^\[Round\s+\d+:\s*[^\]]+\]\s*",

        "",

        user_msg_text,

        flags=re.IGNORECASE

    )

    if len(user_msg_text) > MAX_ARGUMENT_LENGTH:

        return jsonify({

            "error":
                f"Argument cannot exceed "
                f"{MAX_ARGUMENT_LENGTH} characters."

        }), 400


    # --------------------------------------------------------
    # 3. Determine AI stance
    # --------------------------------------------------------

    ai_stance = (

        "AGAINST (Con)"

        if user_stance == "FOR (Pro)"

        else "FOR (Pro)"

    )


    # --------------------------------------------------------
    # 4. Find existing debate
    # --------------------------------------------------------

    current_debate = None

    if debate_id:

        try:

            debate_id = int(
                debate_id
            )

        except (
            TypeError,
            ValueError
        ):

            return jsonify({

                "error":
                    "Invalid debate ID."

            }), 400

        current_debate = db.session.get(

            Debate,

            debate_id

        )

        if not current_debate:

            return jsonify({

                "error":
                    "Debate session not found."

            }), 404

        if current_debate.status == "Completed":

            return jsonify({

                "error":
                    "This debate has already been completed."

            }), 400

        # ----------------------------------------------------
        # A debate must be started before submitting argument
        # ----------------------------------------------------

        if current_debate.status == "Preparing":

            return jsonify({

                "error":
                    "The debate has not started yet. "
                    "Press Start Debate first."

            }), 400

        if current_debate.topic != topic:

            return jsonify({

                "error":
                    "The topic does not match "
                    "the selected debate session."

            }), 400

        if current_debate.stance != user_stance:

            return jsonify({

                "error":
                    "The stance does not match "
                    "the selected debate session."

            }), 400


    # --------------------------------------------------------
    # 5. Determine current round
    # --------------------------------------------------------

    if current_debate:

        existing_rounds = (

            Argument.query

            .filter_by(

                debate_id=
                    current_debate.id

            )

            .count()

        )

    else:

        existing_rounds = 0

    round_num = (

        existing_rounds + 1

    )

    if round_num > TOTAL_ROUNDS:

        return jsonify({

            "error":
                "All five debate rounds are complete."

        }), 400


    # --------------------------------------------------------
    # 6. Build Gemini conversation
    # --------------------------------------------------------

    contents = []

    for message in chat_history:

        role = message.get(
            "role"
        )

        if role == "assistant":

            role = "model"

        if role not in {

            "user",
            "model"

        }:

            continue

        content = clean_text(

            message.get(
                "content"
            )

        )

        if not content:

            continue

        contents.append(

            types.Content(

                role=role,

                parts=[

                    types.Part.from_text(

                        text=content

                    )

                ]

            )

        )


    # --------------------------------------------------------
    # 7. Gemini client
    # --------------------------------------------------------

    try:

        client = get_gemini_client(
            api_key
        )

    except Exception as e:

        return jsonify({

            "error":
                str(e)

        }), 400


    # --------------------------------------------------------
    # 8. Generate ARIA response
    # --------------------------------------------------------

    try:

        response = client.models.generate_content(

            model=
                "gemini-2.5-flash",

            contents=
                contents,

            config=
                types.GenerateContentConfig(

                    system_instruction=
                        build_system_instruction(

                            topic,

                            user_stance,

                            round_num

                        ),

                    temperature=
                        0.7,

                    response_mime_type=
                        "application/json"

                )

        )

    except Exception as e:

        app.logger.exception(

            "Gemini API request failed"

        )

        return jsonify({

            "error":
                "ARIA could not process your argument. "
                + str(e)

        }), 502


    # --------------------------------------------------------
    # 9. Parse response
    # --------------------------------------------------------

    try:

        result = extract_json(

            response.text

        )

        result = normalize_ai_result(

            result

        )

    except Exception:

        app.logger.exception(

            "Failed to parse Gemini response"

        )

        return jsonify({

            "error":
                "ARIA returned an invalid analysis. "
                "Please try again."

        }), 502


    # --------------------------------------------------------
    # 10. Validate response
    # --------------------------------------------------------

    if not result["reply"]:

        return jsonify({

            "error":
                "ARIA generated an empty counterargument."

        }), 502


    # --------------------------------------------------------
    # 11. Scores
    # --------------------------------------------------------

    metrics = result[
        "metrics"
    ]

    user_score = clamp_score(

        metrics.get(
            "user_score"
        )

    )

    ai_score = clamp_score(

        metrics.get(
            "ai_score"
        )

    )


    # --------------------------------------------------------
    # 12. Save debate
    # --------------------------------------------------------

    try:

        if not current_debate:

            # ------------------------------------------------
            # Backward compatibility:
            # If frontend submits directly without using the
            # new Start Debate button, create an active debate.
            # ------------------------------------------------

            current_debate = Debate(

                topic=
                    topic,

                stance=
                    user_stance,

                difficulty=
                    DEFAULT_DIFFICULTY,

                preparation_seconds=
                    PREPARATION_TIME_SECONDS,

                final_score=
                    user_score,

                status=
                    "Active",

                started_at=
                    datetime.utcnow()

            )

            db.session.add(
                current_debate
            )

            db.session.flush()

            debate_id = (
                current_debate.id
            )

        else:

            current_debate.final_score = (

                user_score

            )


        # ----------------------------------------------------
        # 13. Save argument
        # ----------------------------------------------------

        new_argument = Argument(

            debate_id=
                current_debate.id,

            round_num=
                round_num,

            user_argument=
                user_msg_text,

            ai_response=
                result["reply"],

            score=
                user_score,

            analysis=
                result

        )

        db.session.add(
            new_argument
        )


        # ----------------------------------------------------
        # 14. Debate completion
        # ----------------------------------------------------

        if round_num >= TOTAL_ROUNDS:

            current_debate.status = (
                "Completed"
            )

            current_debate.completed_at = (
                datetime.utcnow()
            )

        else:

            current_debate.status = (
                "Active"
            )


        db.session.commit()

    except Exception:

        db.session.rollback()

        app.logger.exception(

            "Database persistence failed"

        )

        return jsonify({

            "error":
                "The argument was analyzed, "
                "but could not be saved."

        }), 500


    # --------------------------------------------------------
    # 15. Calculate live progress
    # --------------------------------------------------------

    all_arguments = (

        Argument.query

        .filter_by(

            debate_id=
                current_debate.id

        )

        .order_by(

            Argument.round_num.asc()

        )

        .all()

    )

    score_history = [

        clamp_score(
            arg.score
        )

        for arg in all_arguments

    ]

    current_average = average(

        score_history

    )

    improvement = 0

    if len(score_history) >= 2:

        improvement = round(

            score_history[-1]
            - score_history[0],

            1

        )


    # --------------------------------------------------------
    # 16. Return complete result
    # --------------------------------------------------------

    return jsonify({

        "success":
            True,

        "debate_id":
            current_debate.id,

        "round":
            round_num,

        "total_rounds":
            TOTAL_ROUNDS,

        "round_name":
            ROUND_NAMES.get(

                round_num,

                "Debate Round"

            ),

        "user_stance":
            user_stance,

        "ai_stance":
            ai_stance,

        "difficulty":
            current_debate.difficulty
            or DEFAULT_DIFFICULTY,

        "completed":
            round_num >= TOTAL_ROUNDS,

        "status":
            current_debate.status,

        "core_claim":
            result["core_claim"],

        "assumptions":
            result["assumptions"],

        "logical_gaps":
            result["logical_gaps"],

        "counter_evidence":
            result["counter_evidence"],

        "reasoning_tags":
            result["reasoning_tags"],

        "challenge_reasons":
            result["challenge_reasons"],

        "reply":
            result["reply"],

        "metrics":
            result["metrics"],

        # ----------------------------------------------------
        # Phase 3 intelligence
        # ----------------------------------------------------

        "progress": {

            "current_round":
                round_num,

            "completed_rounds":
                len(all_arguments),

            "average_user_score":
                current_average,

            "opening_score":
                (
                    score_history[0]
                    if score_history
                    else user_score
                ),

            "current_score":
                user_score,

            "improvement":
                improvement,

            "score_history":
                score_history

        }

    })


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(404)
def not_found(error):

    if request.path.startswith(
        "/api/"
    ):

        return jsonify({

            "error":
                "API endpoint not found."

        }), 404

    return render_template(
        "index.html"
    ), 404


@app.errorhandler(500)
def internal_error(error):

    try:

        db.session.rollback()

    except Exception:

        pass

    if request.path.startswith(
        "/api/"
    ):

        return jsonify({

            "error":
                "Internal server error."

        }), 500

    return (

        "Internal server error.",

        500

    )


# ============================================================
# APPLICATION START
# ============================================================

if __name__ == "__main__":

    app.run(

        debug=True,

        host=
            "127.0.0.1",

        port=
            5000

    )
