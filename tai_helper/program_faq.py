"""Program answers confirmed by Towards AI on 2026-11-28 for prospective learners."""
import re
from html import escape
from urllib.parse import urlsplit

from .catalog import offer_ids_for_query

MENTOR = "https://towardsai.com/academy/mentorship/"
AGENTS = "https://towardsai.com/academy/agent-engineering/"
FAQ_URL = "https://towardsai-tutors-tai-helper.hf.space/program-faq"
# Keep the public FAQ and the words returned by the helper on the same source.
TOPICS = {
    "overview": ("Does Towards AI offer mentorship?",
                 "Yes. Towards AI offers mentorship for engineers working on real AI projects. Bring design decisions, code or career questions to group Q&A, and follow up with mentors by text."),
    "time": ("How long does Agent Engineering take?",
             "Allow roughly 40–70 hours for Agent Engineering, including the projects and capstone. The scope and ambition of your own project affect the time."),
    "career": ("How can I prepare for an AI engineering role?",
               "Bring a project in progress, specific questions and, if you have one, a target job description. Mentors can review your résumé, suggest additions, identify skills or materials to focus on, and help with interview preparation in group Q&A and asynchronously in chat. A dedicated multi-hour private interview-prep session is outside the offer."),
    "calls": ("What are the live sessions like?",
              "The program currently runs two 45-minute group Q&A sessions each week. Bring a capstone, personal project or a specific blocker. Ask your question and leave, or stay and learn from others. Louis reported 9 a.m. and noon Pacific slots on November 28, 2026. For the current weekday and time in your zone, check the current member calendar or email louis@towardsai.net."),
    "projects": ("Can I bring personal projects or private questions?",
                 "Yes. Small personal projects, work-in-progress and real engineering problems are central to mentorship. Course projects are welcome too. For private feedback, DM Louis or a mentor for asynchronous one-to-one text help. In a group call you can request a private moment if others are able to step out."),
    "resources": ("What practical resources do mentees get?",
                  "Mentees can use the Production Blueprints course. The team aims to add a practical resource each month that shows how the mentors work or apply engineering practices. For ordinary coursework questions, use the course tutor, forums or Discord."),
    "plans": ("Are expert workshops, internships or partner perks included?",
              "Monthly expert workshops starting in January 2027 were being explored as of November 2026. Company projects, internships, credits and perks were also under discussion. None of those opportunities is confirmed or guaranteed."),
}
PATTERNS = {
    "time": r"\b(hours?|duration|workload|how long|time commitment)\b",
    "career": r"\b(interviews?|r[ée]sum[ée]s?|cv|career|job description|transition|switch roles)\b",
    "calls": r"\b(calls?|sessions?|weekly|pacific|schedule|time zone|live q&a|one.on.one|1.on.1|group|office hours)\b",
    "projects": r"\b(personal|small projects?|private|async\w*|direct message|dm|real projects?|own projects?|project feedback)\b",
    "resources": r"\b(blueprints?|monthly resources?|practical resources?)\b",
    "plans": r"\b(workshops?|internships?|partnerships?|perks?|credits?|placements?)\b",
}


def program_answer(query, user_history, url):
    q = query.casefold()
    # The sales catalog owns current commercial terms and entitlement questions.
    if re.search(r"\b(free preview|certificate|price|cost|refund|cancel\w*|discount|tuition|lifetime|billing|subscription|which courses|course access)\b", q):
        return None
    path = urlsplit(url).path.rstrip("/")
    history = " ".join(user_history[-2:]).casefold()
    mentor = bool(re.search(r"\bmentor(?:s|ship|ing)?\b", q))
    agent = bool(re.search(r"\bagent(?:ic ai)? engineering\b", q))
    full_stack = bool(re.search(r"\bfull[ -]stack\b", q))
    if not (mentor or agent or full_stack) and not offer_ids_for_query(query):
        mentor = "mentor" in history or path == "/academy/mentorship"
        agent = "agent engineering" in history or path == "/academy/agent-engineering"
    topics = [k for k, pattern in PATTERNS.items() if re.search(pattern, q)
              and ((agent and k == "time") or (mentor and k != "time"))]
    if not topics and mentor and not agent and not full_stack and re.search(r"(do you (?:have|offer) (?:a |any )?mentor|is there (?:a |any )?mentor|find mentors|what is (?:the |your )?mentorship)", q):
        topics = ["overview"]
    if not topics:
        return None
    return "\n\n".join(TOPICS[k][1] for k in topics), topics[0]


def public_page():
    sections = "".join(f'<section id="{key}"><h2>{escape(question)}</h2><p>{escape(answer)}</p></section>'
                       for key, (question, answer) in TOPICS.items())
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            '<title>Towards AI program FAQ</title><main style="max-width:44rem;margin:2rem auto;font:18px/1.55 system-ui">'
            '<h1>Towards AI program FAQ</h1><p>Program guidance confirmed November 28, 2026.</p>'
            + sections + f'<p><a href="{MENTOR}">Mentorship program</a> · <a href="{AGENTS}">Agent Engineering</a></p></main></html>')
