"""
LLM-powered summarization pipeline for Civic City Hub.

Takes raw agenda text and produces:
- Plain-language summary of the meeting
- Key decisions with explanations
- Budget/financial items highlighted
- Public comment opportunities
- Per-item plain-language translations

Uses DeepSeek API (OpenAI-compatible) for cost-effective summarization.
"""

import json
import os
from typing import Optional

from openai import OpenAI

from models.schemas import Agenda, Minutes, SummaryResponse


# System prompt for agenda summarization
SYSTEM_PROMPT = """You are a civic technology assistant that helps residents understand 
their local government. Your job is to translate complex city council agendas into 
plain, accessible language.

For each agenda, you will:
1. Identify the most important decisions the council will make
2. Explain what each item means in plain language
3. Highlight any items that affect residents directly (taxes, fees, zoning, services)
4. Note opportunities for public comment
5. Flag budget/financial items with estimated amounts

Be objective and factual. Do not express political opinions. 
Do not speculate on outcomes. Just explain what's being proposed.

Format your response as JSON with this structure:
{
  "summary": "2-3 paragraph plain-language overview of the meeting",
  "key_decisions": [
    {
      "title": "Short title of the decision",
      "plain_english": "What this means in simple terms",
      "impact": "Who this affects and how",
      "category": "zoning|budget|public-safety|infrastructure|administration|other"
    }
  ],
  "budget_items": [
    {
      "title": "Item title",
      "amount": "$X,XXX",
      "description": "What the money is for"
    }
  ],
  "public_comment_opportunities": [
    {
      "item": "Item title",
      "deadline": "When to comment",
      "how": "How to submit comments"
    }
  ],
  "items": [
    {
      "title": "Original agenda item title",
      "plain_english": "Plain language explanation",
      "category": "section category",
      "action_needed": "vote|discussion|information|public-hearing|none"
    }
  ]
}"""

# System prompt for minutes summarization
MINUTES_SYSTEM_PROMPT = """You are a civic technology assistant that helps residents understand
what happened at their local government meetings. Your job is to translate official city council
meeting minutes into plain, accessible language.

Minutes are the OFFICIAL RECORD of what actually happened at a meeting — what was discussed,
what decisions were made, how council members voted, and what actions were taken. This is
different from an agenda, which only lists what was planned.

For each set of minutes, you will:
1. Summarize what actually happened at the meeting in plain language
2. Identify all decisions made and how each council member voted (if available)
3. Explain what each action means for residents
4. Highlight any items that affect residents directly (taxes, fees, zoning, services)
5. Note any public comments made by residents
6. Flag budget/financial items with amounts

Be objective and factual. Do not express political opinions.
Focus on WHAT HAPPENED — the actual outcomes, votes, and actions taken.

Format your response as JSON with this structure:
{
  "summary": "2-3 paragraph plain-language overview of what happened at the meeting",
  "key_decisions": [
    {
      "title": "Short title of the decision",
      "plain_english": "What this means in simple terms",
      "impact": "Who this affects and how",
      "category": "zoning|budget|public-safety|infrastructure|administration|other",
      "vote": "How the vote went (e.g. 5-0 passed, 3-2 failed)"
    }
  ],
  "budget_items": [
    {
      "title": "Item title",
      "amount": "$X,XXX",
      "description": "What the money is for"
    }
  ],
  "public_comment_opportunities": [
    {
      "item": "Topic discussed",
      "deadline": "When comments were received or next opportunity",
      "how": "How residents provided input"
    }
  ],
  "items": [
    {
      "title": "Agenda item or topic discussed",
      "plain_english": "Plain language explanation of what happened",
      "category": "section category",
      "action_needed": "approved|denied|tabled|discussed|received"
    }
  ]
}"""


class LLMSummarizer:
    """Summarizes city council agendas and minutes using DeepSeek API."""

    def __init__(self, api_key: Optional[str] = None, model: str = "deepseek-chat"):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ValueError(
                "DEEPSEEK_API_KEY is required. Set it as an environment variable "
                "or pass it to the constructor."
            )
        self.client = OpenAI(
            api_key=self.api_key,
            base_url="https://api.deepseek.com",
        )
        self.model = model

    async def summarize_agenda(self, agenda: Agenda) -> SummaryResponse:
        """Summarize a full agenda using the LLM."""
        # Prepare the agenda text for the LLM
        agenda_text = self._prepare_agenda_text(agenda)

        user_content = (
            f"Please summarize the following city council agenda "
            f"for {agenda.city}, {agenda.state} on "
            f"{agenda.meeting_date.strftime('%B %d, %Y')}.\n\n"
            f"Meeting Type: {agenda.meeting_type}\n"
            f"Title: {agenda.title}\n\n"
            f"Agenda Text:\n{agenda_text}\n\n"
            f"Return ONLY valid JSON matching the specified structure."
        )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )

        result = json.loads(response.choices[0].message.content)

        return SummaryResponse(
            agenda_id=agenda.id,
            meeting_date=agenda.meeting_date,
            meeting_type=agenda.meeting_type,
            summary=result.get("summary", "No summary available."),
            key_decisions=result.get("key_decisions", []),
            budget_items=result.get("budget_items", []),
            public_comment_opportunities=result.get("public_comment_opportunities", []),
            items=result.get("items", []),
        )

    async def summarize_minutes(self, minutes: Minutes) -> SummaryResponse:
        """Summarize meeting minutes using the LLM.

        Minutes are the official record of what happened at a meeting,
        as opposed to an agenda which lists what's planned.
        """
        # Prepare the minutes text for the LLM
        minutes_text = self._prepare_minutes_text(minutes)

        user_content = (
            f"Please summarize the following city council meeting minutes "
            f"for {minutes.city}, {minutes.state} on "
            f"{minutes.meeting_date.strftime('%B %d, %Y')}.\n\n"
            f"Meeting Type: {minutes.meeting_type}\n"
            f"Title: {minutes.title}\n\n"
            f"Minutes Text:\n{minutes_text}\n\n"
            f"Return ONLY valid JSON matching the specified structure."
        )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": MINUTES_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )

        result = json.loads(response.choices[0].message.content)

        return SummaryResponse(
            agenda_id=minutes.id,
            meeting_date=minutes.meeting_date,
            meeting_type=minutes.meeting_type,
            summary=result.get("summary", "No summary available."),
            key_decisions=result.get("key_decisions", []),
            budget_items=result.get("budget_items", []),
            public_comment_opportunities=result.get("public_comment_opportunities", []),
            items=result.get("items", []),
        )

    async def summarize_text(
        self, text: str, city: str = "Paris", state: str = "TX", meeting_date: str = ""
    ) -> dict:
        """Summarize raw agenda text directly."""
        user_content = (
            f"Please summarize the following city council agenda "
            f"for {city}, {state} on {meeting_date}.\n\n"
            f"Agenda Text:\n{text[:15000]}\n\n"
            f"Return ONLY valid JSON matching the specified structure."
        )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )

        return json.loads(response.choices[0].message.content)

    def _prepare_agenda_text(self, agenda: Agenda) -> str:
        """Prepare agenda data as text for the LLM."""
        parts = [f"Meeting: {agenda.title}"]
        parts.append(f"Date: {agenda.meeting_date.strftime('%B %d, %Y')}")
        parts.append(f"Type: {agenda.meeting_type}")
        parts.append("")

        if agenda.raw_text:
            # Use the raw PDF text if available
            parts.append("--- Full Agenda Text ---")
            parts.append(agenda.raw_text[:12000])  # Limit length
        elif agenda.items:
            parts.append("--- Agenda Items ---")
            for i, item in enumerate(agenda.items, 1):
                parts.append(f"{i}. [{item.category}] {item.title}")
                if item.description:
                    parts.append(f"   {item.description[:200]}")
        else:
            parts.append("(No detailed agenda items available)")

        return "\n".join(parts)

    def _prepare_minutes_text(self, minutes: Minutes) -> str:
        """Prepare minutes data as text for the LLM."""
        parts = [f"Meeting: {minutes.title}"]
        parts.append(f"Date: {minutes.meeting_date.strftime('%B %d, %Y')}")
        parts.append(f"Type: {minutes.meeting_type}")
        parts.append("")

        if minutes.raw_text:
            # Use the raw document text if available
            parts.append("--- Full Minutes Text ---")
            parts.append(minutes.raw_text[:12000])  # Limit length
        else:
            parts.append("(No detailed minutes text available)")

        return "\n".join(parts)
