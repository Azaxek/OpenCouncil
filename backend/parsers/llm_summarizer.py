"""
LLM-powered summarization pipeline for Civic City Hub.

Takes meeting minutes text or scanned document images and produces:
- Plain-language summary of what happened at the meeting
- Key decisions with explanations
- Budget/financial items highlighted
- Public comment opportunities
- Per-item plain-language translations

Supports two modes:
1. Text-based summarization (DeepSeek) — for documents with extractable text
2. Vision-based summarization (GPT-4o) — for scanned document images (TIFF)
"""

import base64
import json
import os
from typing import Optional

import httpx
from openai import OpenAI

from models.schemas import Minutes, SummaryResponse


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

# Vision system prompt — instructs GPT-4o to first extract text from images,
# then produce the same structured summary
VISION_SYSTEM_PROMPT = """You are a civic technology assistant that helps residents understand
what happened at their local government meetings. Your job is to read scanned city council
meeting minutes from document images and translate them into plain, accessible language.

First, carefully read all text visible in the scanned document images.
Then, produce a structured summary of what happened at the meeting.

Minutes are the OFFICIAL RECORD of what actually happened at a meeting — what was discussed,
what decisions were made, how council members voted, and what actions were taken.

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
    """Summarizes city council minutes using LLM APIs.

    Supports two modes:
    - Text mode (DeepSeek): For documents with extractable text content
    - Vision mode (GPT-4o): For scanned document images (TIFF) from Laserfiche

    Falls back to text mode if no page_image_urls are available.
    Uses GPT-4o Vision when page images are present.
    """

    def __init__(
        self,
        deepseek_key: Optional[str] = None,
        openai_key: Optional[str] = None,
        vision_model: str = "gpt-4o-mini",
        text_model: str = "deepseek-chat",
    ):
        self.deepseek_key = deepseek_key or os.getenv("DEEPSEEK_API_KEY")
        self.openai_key = openai_key or os.getenv("OPENAI_API_KEY")
        self.vision_model = vision_model
        self.text_model = text_model

        # Initialize DeepSeek client (text mode)
        if self.deepseek_key:
            self.deepseek_client = OpenAI(
                api_key=self.deepseek_key,
                base_url="https://api.deepseek.com",
            )
        else:
            self.deepseek_client = None

        # Initialize OpenAI client (vision mode)
        if self.openai_key:
            self.openai_client = OpenAI(api_key=self.openai_key)
        else:
            self.openai_client = None

        if not self.deepseek_key and not self.openai_key:
            raise ValueError(
                "At least one of DEEPSEEK_API_KEY or OPENAI_API_KEY is required. "
                "Set them as environment variables or pass to the constructor."
            )

        # HTTP client for fetching page images
        self.http_client = httpx.AsyncClient(timeout=30.0)

    async def close(self):
        await self.http_client.aclose()

    async def summarize_minutes(self, minutes: Minutes) -> SummaryResponse:
        """Summarize meeting minutes using the best available method.

        Priority:
        1. Vision mode (GPT-4o) — if page_image_urls are available and
           OPENAI_API_KEY is set. This reads scanned document images directly.
        2. Text mode (DeepSeek) — if raw_text is available and DEEPSEEK_API_KEY
           is set. This works for text-based documents.
        """
        # Prefer vision mode for scanned document images
        if (
            minutes.page_image_urls
            and self.openai_client
        ):
            return await self._summarize_with_vision(minutes)

        # Fall back to text mode
        if self.deepseek_client:
            return await self._summarize_with_text(minutes)

        # If only one client is available, use it
        if self.openai_client:
            return await self._summarize_with_vision(minutes)

        if self.deepseek_client:
            return await self._summarize_with_text(minutes)

        raise RuntimeError("No LLM client available for summarization.")

    async def _summarize_with_vision(
        self, minutes: Minutes
    ) -> SummaryResponse:
        """Summarize minutes using GPT-4o Vision on scanned document images.

        Fetches each page image from the Laserfiche server and passes them
        to GPT-4o Vision, which reads the text from the scanned images and
        produces a structured summary.
        """
        # Build the user message with text context + images
        content_parts: list[dict] = [
            {
                "type": "text",
                "text": (
                    f"Please summarize the following city council meeting minutes "
                    f"for {minutes.city}, {minutes.state} on "
                    f"{minutes.meeting_date.strftime('%B %d, %Y')}.\n\n"
                    f"Meeting Type: {minutes.meeting_type}\n"
                    f"Title: {minutes.title}\n\n"
                    f"The document has {len(minutes.page_image_urls)} page(s). "
                    f"Please read all pages carefully and produce a complete summary.\n\n"
                    f"Return ONLY valid JSON matching the specified structure."
                ),
            }
        ]

        # Fetch and attach each page image
        for i, image_url in enumerate(minutes.page_image_urls):
            try:
                image_data = await self._fetch_image(image_url)
                if image_data:
                    content_parts.append({
                        "type": "text",
                        "text": f"--- Page {i + 1} ---",
                    })
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_data}",
                            "detail": "high",
                        },
                    })
            except Exception as e:
                print(
                    f"[WARN] Failed to fetch page {i + 1} image: {e}"
                )

        response = self.openai_client.chat.completions.create(
            model=self.vision_model,
            messages=[
                {
                    "role": "system",
                    "content": VISION_SYSTEM_PROMPT,
                },
                {"role": "user", "content": content_parts},
            ],
            temperature=0.3,
            max_tokens=4000,
            response_format={"type": "json_object"},
        )

        result = json.loads(response.choices[0].message.content)

        return SummaryResponse(
            minutes_id=minutes.id,
            meeting_date=minutes.meeting_date,
            meeting_type=minutes.meeting_type,
            summary=result.get("summary", "No summary available."),
            key_decisions=result.get("key_decisions", []),
            budget_items=result.get("budget_items", []),
            public_comment_opportunities=result.get(
                "public_comment_opportunities", []
            ),
            items=result.get("items", []),
        )

    async def _fetch_image(self, url: str) -> Optional[str]:
        """Fetch an image from a URL and return it as base64-encoded string."""
        try:
            response = await self.http_client.get(url)
            response.raise_for_status()
            return base64.b64encode(response.content).decode("utf-8")
        except Exception as e:
            print(f"[WARN] Error fetching image {url}: {e}")
            return None

    async def _summarize_with_text(
        self, minutes: Minutes
    ) -> SummaryResponse:
        """Summarize minutes using DeepSeek text model."""
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

        response = self.deepseek_client.chat.completions.create(
            model=self.text_model,
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
            minutes_id=minutes.id,
            meeting_date=minutes.meeting_date,
            meeting_type=minutes.meeting_type,
            summary=result.get("summary", "No summary available."),
            key_decisions=result.get("key_decisions", []),
            budget_items=result.get("budget_items", []),
            public_comment_opportunities=result.get(
                "public_comment_opportunities", []
            ),
            items=result.get("items", []),
        )

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
