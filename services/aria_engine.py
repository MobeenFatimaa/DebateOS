import json
from google import genai
from google.genai import types


ROUND_CONFIG = {
    1: {
        "name": "Opening Statement",
        "objective": """
Evaluate the user's opening position.
Identify the thesis, assumptions, evidence quality,
clarity, and initial logical structure.
"""
    },

    2: {
        "name": "Counter Argument",
        "objective": """
Aggressively challenge the user's position.
Attack weak assumptions, missing evidence,
logical gaps, contradictions, and unsupported claims.
"""
    },

    3: {
        "name": "Rebuttal",
        "objective": """
Evaluate whether the user successfully responded
to the previous counterargument.

Look specifically for:
- Whether the actual challenge was answered
- New unsupported claims
- Contradictions
- Evasion
- Strong rebuttal points
"""
    },

    4: {
        "name": "Cross Examination",
        "objective": """
Act as a rigorous cross-examiner.

Ask a sharp question that exposes the weakest
remaining part of the user's reasoning.

Do not simply repeat the previous argument.
Force the user to clarify, justify, or defend
their assumptions.
"""
    },

    5: {
        "name": "Closing Statement",
        "objective": """
Evaluate the user's final position.

Determine whether the user successfully:
- defended the thesis
- answered major objections
- maintained logical consistency
- used evidence
- remained relevant
- presented a persuasive conclusion
"""
    }
}


def build_system_instruction(topic, user_stance, round_number):
    """
    Build ARIA's system instruction based on the current
    debate round.
    """

    round_number = max(1, min(5, int(round_number)))

    round_info = ROUND_CONFIG[round_number]

    ai_stance = (
        "AGAINST (Con)"
        if user_stance == "FOR (Pro)"
        else "FOR (Pro)"
    )

    return f"""
You are ARIA.

ARIA stands for:
Adversarial Reasoning Intelligence Architecture.

You are an elite debate opponent and critical-thinking coach.

You are NOT merely a chatbot.

Your job is to:
- challenge reasoning
- detect unsupported assumptions
- detect logical fallacies
- evaluate evidence
- expose contradictions
- provide meaningful counterarguments
- train the user to think more rigorously

==================================================
DEBATE INFORMATION
==================================================

Topic:
{topic}

User Stance:
{user_stance}

ARIA Stance:
{ai_stance}

Current Round:
{round_number}/5

Round Name:
{round_info["name"]}

==================================================
CURRENT ROUND OBJECTIVE
==================================================

{round_info["objective"]}

==================================================
IMPORTANT RULES
==================================================

1. Stay focused on the debate topic.

2. Do not invent citations, statistics, studies,
   quotations, or factual sources.

3. If the user makes an unsupported factual claim,
   explicitly identify it as unsupported rather than
   pretending it is true.

4. Do not attack the user personally.
   Attack the reasoning.

5. Be intellectually rigorous but educational.

6. Keep the main counterargument concise.

7. Identify the strongest part of the user's argument
   as well as the weakest part.

8. Distinguish between:
   - fact
   - assumption
   - inference
   - opinion

9. Avoid generic feedback.

10. Your response MUST be valid JSON.

==================================================
REQUIRED JSON FORMAT
==================================================

{{
    "core_claim": "Short description of the user's main claim",

    "strongest_point": "Strongest aspect of the user's reasoning",

    "weakest_point": "Weakest aspect of the user's reasoning",

    "assumptions": "Important assumption behind the argument",

    "logical_gaps": "Important logical weakness or fallacy",

    "counter_evidence": "Counter-evidence or alternative angle",

    "reasoning_tags": [
        "Generalization",
        "Unsupported assumption"
    ],

    "challenge_reasons": [
        {{
            "title": "Unsupported assumption",
            "detail": "Explain exactly why the assumption is weak."
        }},
        {{
            "title": "Missing evidence",
            "detail": "Explain what evidence would strengthen the claim."
        }},
        {{
            "title": "Logical weakness",
            "detail": "Explain the reasoning problem."
        }},
        {{
            "title": "Alternative explanation",
            "detail": "Explain another plausible interpretation."
        }}
    ],

    "reply": "A strong and concise response from ARIA.",

    "next_question": "A challenging question the user should consider.",

    "metrics": {{
        "argument_strength": 0,
        "evidence": 0,
        "logical_consistency": 0,
        "relevance": 0,
        "persuasiveness": 0,
        "ai_score": 0,
        "user_score": 0
    }}
}}

==================================================
SCORING
==================================================

Every metric must be an integer from 0 to 100.

argument_strength:
Overall quality of the argument.

evidence:
Quality and sufficiency of supporting evidence.

logical_consistency:
How logically sound the reasoning is.

relevance:
How directly the argument addresses the topic.

persuasiveness:
How convincing the argument is.

user_score:
Overall performance of the user in this round.

ai_score:
Quality of ARIA's counterargument.

Do not automatically give high scores.

A strong argument should earn a high score.
A weak argument should receive a lower score.

Return ONLY valid JSON.
"""


def analyze_argument(
    api_key,
    topic,
    user_stance,
    round_number,
    chat_history
):
    """
    Send the debate state to Gemini and return structured
    ARIA analysis.
    """

    client = genai.Client(api_key=api_key)

    system_instruction = build_system_instruction(
        topic=topic,
        user_stance=user_stance,
        round_number=round_number
    )

    contents = []

    for message in chat_history:

        role = (
            "user"
            if message.get("role") == "user"
            else "model"
        )

        content = message.get("content", "").strip()

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

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.7,
            response_mime_type="application/json",
        ),
    )

    if not response.text:
        raise ValueError("ARIA returned an empty response.")

    try:
        result = json.loads(response.text)

    except json.JSONDecodeError as exc:
        raise ValueError(
            f"ARIA returned invalid JSON: {response.text}"
        ) from exc

    return normalize_result(result)


def normalize_result(result):
    """
    Make sure the frontend always receives the expected fields.
    """

    metrics = result.get("metrics", {})

    normalized_metrics = {
        "argument_strength": safe_metric(
            metrics.get("argument_strength", 50)
        ),

        "evidence": safe_metric(
            metrics.get("evidence", 50)
        ),

        "logical_consistency": safe_metric(
            metrics.get("logical_consistency", 50)
        ),

        "relevance": safe_metric(
            metrics.get("relevance", 50)
        ),

        "persuasiveness": safe_metric(
            metrics.get("persuasiveness", 50)
        ),

        "ai_score": safe_metric(
            metrics.get("ai_score", 50)
        ),

        "user_score": safe_metric(
            metrics.get("user_score", 50)
        ),
    }

    result["core_claim"] = result.get(
        "core_claim",
        "No core claim identified."
    )

    result["strongest_point"] = result.get(
        "strongest_point",
        "No strongest point identified."
    )

    result["weakest_point"] = result.get(
        "weakest_point",
        "No weakest point identified."
    )

    result["assumptions"] = result.get(
        "assumptions",
        "No major assumption identified."
    )

    result["logical_gaps"] = result.get(
        "logical_gaps",
        "No major logical gap identified."
    )

    result["counter_evidence"] = result.get(
        "counter_evidence",
        "No specific counter-evidence identified."
    )

    result["reasoning_tags"] = result.get(
        "reasoning_tags",
        []
    )

    result["challenge_reasons"] = result.get(
        "challenge_reasons",
        []
    )

    result["reply"] = result.get(
        "reply",
        "ARIA could not generate a counterargument."
    )

    result["next_question"] = result.get(
        "next_question",
        "What evidence would strengthen your position?"
    )

    result["metrics"] = normalized_metrics

    return result


def safe_metric(value):
    """
    Safely convert an AI-generated metric to 0-100.
    """

    try:
        value = int(value)
    except (TypeError, ValueError):
        return 50

    return max(0, min(100, value))
