# Prompt: Strategist Story Aggregator

Summarize this cluster into one dense macro story.

Rules:
- Deduplicate repeated reports.
- Mention the likely market transmission channel.
- Keep it to 2-4 sentences.

Output Format:
Return ONLY a JSON object with this schema:
{
  "summary": "The dense macro story summary",
  "confidence": 0.0-1.0,
  "affected_assets": ["Asset1", "Asset2"],
  "market_transmission": "description of how this affects markets"
}
