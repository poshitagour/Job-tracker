# core/ai_scorer.py
# Uses Claude to score job fit and generate cover letters

import anthropic
import re
import os
from config.profile import PROFILE

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

TOBI_CONTEXT = f"""
You are helping Tobi Akindele, a backend software engineer in Dublin, Ireland.

PROFILE:
- Name: Tobi Akindele (Oloruntobiloba Akindele)
- Role: Backend Software Engineer at Trivera Labs
- Education: MSc Computer Science, Cloud Platforms & Applications — Griffith College Dublin (graduating Aug 2027). BSc First Class Honours + Chancellor's Award, Chrisland University Nigeria (2023).
- Visa: Irish Stamp 2 → Stamp 1G post-graduation (24 months full-time work, no permit) → CSEP sponsorship after
- Location: Dublin 7, Ireland
- Skills: Python, FastAPI, REST APIs, Docker, MongoDB, Firebase, React, Next.js, C#, SQL
- AI/ML: RAG systems, LLM integration, Whisper STT, Kokoro TTS, Ollama, ChromaDB, BM25/vector retrieval, Anthropic API
- Cloud: Azure (Azurite), GCP, Docker, CI/CD
- Projects: AI Lecture Explainer (RAG + hybrid retrieval), Real-time TTS system (FastAPI + WebSocket), automated Python job bot, Twitter-like social app "Echo" (FastAPI + Firebase + MongoDB)
- Also: AI annotation/evaluation work (Outlier), FX platform documentation (English + Japanese), Excel VBA automation
- Working style: Direct, prefers output over discussion, practical over theoretical
- Experience: ~2 years backend engineering
"""

COVER_LETTER_RULES = """
COVER LETTER RULES — follow strictly:
- No em dashes (— or –). Use commas, periods, or colons instead.
- No cliches: "I am passionate about", "I would be a great fit", "I am excited to", "leverage", "synergy", "dynamic team"
- No corporate-speak. Write like a person, not an AI.
- Reference a specific real project from Tobi's background — not vague "projects"
- 3 sentences maximum for the opening paragraph
- Confident but not arrogant. Direct. Grounded.
- Do not use overly technical jargon unless the role specifically requires it
- First sentence should hook — what he brings, not who he is
- Do not start with "I"
- No em dashes. This is critical. Check twice before outputting.
"""


def score_job_fit(job_title: str, company: str, job_description: str) -> dict:
    """
    Score Tobi's fit for a job 0-10 and decide whether to apply.
    Returns: { score: int, reason: str, apply: bool, red_flags: list }
    """
    prompt = f"""
Score Tobi's fit for this job on a scale of 0-10.

JOB:
Title: {job_title}
Company: {company}
Description:
{job_description[:2000]}

Return ONLY a JSON object with these exact keys:
{{
  "score": <integer 0-10>,
  "reason": "<one sentence why this score>",
  "apply": <true if score >= 6, false otherwise>,
  "red_flags": ["<any dealbreaker requirements Tobi doesn't meet>"],
  "best_role_match": "<which of Tobi's target roles this is closest to>"
}}

Scoring guide:
- 9-10: Perfect match, target company, entry-level, uses his exact stack
- 7-8: Good match, relevant skills, reasonable requirements
- 6: Acceptable, some gaps but worth applying
- 4-5: Significant gaps, stretch application
- 0-3: Wrong level (senior/lead), wrong stack entirely, or excludes visa sponsorship

If the job explicitly says "no sponsorship" or "must be EU citizen" score it 0.
If it requires 5+ years experience, score it 1.
"""
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",  # Fast + cheap for scoring
            max_tokens=300,
            system=TOBI_CONTEXT,
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text.strip()
        # Extract JSON
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            import json
            return json.loads(json_match.group())
    except Exception as e:
        print(f"  [AI] Scoring error: {e}")

    return {"score": 5, "reason": "Could not score", "apply": True, "red_flags": [], "best_role_match": job_title}


def generate_cover_letter(job_title: str, company: str, job_description: str) -> str:
    """
    Generate the full cover letter opening (3 sentences) for a specific role.
    """
    prompt = f"""
Write the opening paragraph (3 sentences) of a cover letter for Tobi applying to:

Role: {job_title}
Company: {company}
Job description excerpt:
{job_description[:1500]}

{COVER_LETTER_RULES}

Output ONLY the 3 sentences. No heading, no "Dear Hiring Manager", no sign-off. Just the paragraph.
"""
    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=250,
            system=TOBI_CONTEXT,
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text.strip()
        # Safety check: remove any em dashes that slipped through
        text = text.replace("—", ",").replace("–", ",")
        return text
    except Exception as e:
        print(f"  [AI] Cover letter error: {e}")
        return generate_fallback_cover_letter(job_title, company)


def generate_full_cover_letter(job_title: str, company: str, job_description: str) -> str:
    """
    Generate a complete cover letter (3 paragraphs) when the form requires one.
    """
    prompt = f"""
Write a full cover letter for Tobi applying to:

Role: {job_title}
Company: {company}
Job description:
{job_description[:2000]}

{COVER_LETTER_RULES}

Structure:
- Opening paragraph (3 sentences): what he brings + specific project hook
- Middle paragraph (3-4 sentences): why this company specifically, what he can contribute
- Closing paragraph (2 sentences): availability + call to action

No "Dear Hiring Manager" header needed. Start directly with the opening paragraph.
No em dashes anywhere. No cliches. No AI-speak.
Total length: 150-200 words maximum.
"""
    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            system=TOBI_CONTEXT,
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text.strip()
        text = text.replace("—", ",").replace("–", ",")
        return text
    except Exception as e:
        print(f"  [AI] Full cover letter error: {e}")
        return generate_fallback_cover_letter(job_title, company)


def answer_application_question(question: str, job_title: str, company: str) -> str:
    """
    AI answers a custom application question in Tobi's voice.
    Used for free-text questions like "Why do you want to work here?"
    """
    prompt = f"""
Tobi is applying for {job_title} at {company}.
Answer this application question in his voice:

Question: {question}

Rules:
- 2-4 sentences maximum
- Direct and specific, not generic
- No em dashes
- No cliches ("passionate about", "excited to", "would be a great fit")
- Reference his actual experience where relevant
- If it's a yes/no question, answer yes/no first then explain briefly
"""
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            system=TOBI_CONTEXT,
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text.strip()
        return text.replace("—", ",").replace("–", ",")
    except Exception as e:
        print(f"  [AI] Question answering error: {e}")
        return ""


def generate_fallback_cover_letter(job_title: str, company: str) -> str:
    """Fallback if API fails."""
    return (
        f"Building production systems at Trivera Labs gave me direct experience with the kind of "
        f"backend work {company} is hiring for in this {job_title} role. "
        f"My recent project, a real-time TTS pipeline built with FastAPI and WebSocket streaming, "
        f"reflects the kind of end-to-end engineering I bring to every problem. "
        f"I would welcome the chance to contribute to your team and grow within a structured engineering environment."
    )
