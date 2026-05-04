import os
import json
import asyncio
import aiofiles
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types


load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise ValueError("A variável de ambiente GEMINI_API_KEY não foi definida.")

client = genai.Client(api_key=API_KEY)

ROOT_DIR = Path(__file__).parent
DATA_DIR = ROOT_DIR / "data"

PROMPT_FILE = Path(
    os.getenv(
        "ORACLE_PROMPT_FILE",
        str(ROOT_DIR / "prompts" / "ia_trend_oracle.md"),
    )
)

DEFAULT_INPUT_FILE = DATA_DIR / "mock_intel_items_big_process_result.json"
DEFAULT_OUTPUT_FILE = DATA_DIR / "oracle_output_results.json"
DEFAULT_CANDIDATES_FILE = DATA_DIR / "oracle_candidates_input.json"
DEFAULT_MESSAGES_FILE = DATA_DIR / "oracle_messages.json"

INPUT_FILE = Path(os.getenv("ORACLE_INPUT_FILE", str(DEFAULT_INPUT_FILE)))
OUTPUT_FILE = Path(os.getenv("ORACLE_OUTPUT_FILE", str(DEFAULT_OUTPUT_FILE)))
CANDIDATES_FILE = Path(os.getenv("ORACLE_CANDIDATES_FILE", str(DEFAULT_CANDIDATES_FILE)))
MESSAGES_FILE = Path(os.getenv("ORACLE_MESSAGES_FILE", str(DEFAULT_MESSAGES_FILE)))

MAX_MESSAGES = int(os.getenv("ORACLE_MAX_MESSAGES", "0"))  # 0 = sem limite
CONCURRENCY = int(os.getenv("ORACLE_CONCURRENCY", "1"))
MAX_RETRIES = int(os.getenv("ORACLE_MAX_RETRIES", "15"))

MIN_MARKET_IMPACT = float(os.getenv("ORACLE_MIN_MARKET_IMPACT", "0.65"))
MIN_ORACLE_REVIEW = float(os.getenv("ORACLE_MIN_REVIEW_SCORE", "0.60"))
MIN_TRADE_EMIT = float(os.getenv("ORACLE_MIN_TRADE_EMIT_SCORE", "0.65"))
MIN_GEO_SEVERITY = float(os.getenv("ORACLE_MIN_GEO_SEVERITY", "0.85"))

ENABLE_URL_CONTEXT = os.getenv("ORACLE_ENABLE_URL_CONTEXT", "true").lower() == "true"
ENABLE_GOOGLE_SEARCH = os.getenv("ORACLE_ENABLE_GOOGLE_SEARCH", "false").lower() == "true"
INCLUDE_ROBOTICS_MODELS = os.getenv("ORACLE_INCLUDE_ROBOTICS_MODELS", "true").lower() == "true"

MODEL_ALLOWLIST = [
    model.strip()
    for model in os.getenv("ORACLE_MODEL_ALLOWLIST", "").split(",")
    if model.strip()
]

MODEL_DENYLIST = [
    model.strip()
    for model in os.getenv("ORACLE_MODEL_DENYLIST", "").split(",")
    if model.strip()
]

with open(PROMPT_FILE, "r", encoding="utf-8") as f:
    system_prompt = f.read()

tools: list[types.Tool] = []
if ENABLE_URL_CONTEXT:
    tools.append(types.Tool(url_context=types.UrlContext()))
if ENABLE_GOOGLE_SEARCH:
    tools.append(types.Tool(googleSearch=types.GoogleSearch()))

configuracao_playground = types.GenerateContentConfig(
    temperature=0.2,
    top_p=0.95,
    max_output_tokens=22000,
    thinking_config=types.ThinkingConfig(
        thinking_level="HIGH",
    ),
    media_resolution="MEDIA_RESOLUTION_MEDIUM",
    tools=tools,
    response_mime_type="application/json",
    system_instruction=[
        types.Part.from_text(text=system_prompt),
    ],
)


# ──────────────────────────────────────────────────────────────────────────────
# JSON helpers
# ──────────────────────────────────────────────────────────────────────────────

async def load_json(filepath: Path) -> Any:
    try:
        async with aiofiles.open(filepath, mode="r", encoding="utf-8") as f:
            return json.loads(await f.read())
    except FileNotFoundError:
        print(f"❌ Arquivo não encontrado: {filepath}")
        return []


async def save_json(filepath: Path, payload: Any) -> None:
    filepath.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(filepath, mode="w", encoding="utf-8") as f:
        await f.write(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"💾 Arquivo salvo: {filepath}")


def parse_llm_json(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None

    raw = text.strip()

    # Remove markdown fences se algum modelo insistir em envolver a resposta.
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", raw, flags=re.DOTALL | re.IGNORECASE)
    if fence_match:
        raw = fence_match.group(1).strip()

    try:
        return json.loads(raw)
    except Exception:
        pass

    # Fallback: tenta achar primeiro objeto JSON.
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except Exception:
            return None

    return None


# ──────────────────────────────────────────────────────────────────────────────
# Candidate selection
# ──────────────────────────────────────────────────────────────────────────────

def get_extra(event: dict[str, Any]) -> dict[str, Any]:
    extra = event.get("extra")
    return extra if isinstance(extra, dict) else {}


def get_scores(event: dict[str, Any]) -> dict[str, float]:
    extra = get_extra(event)
    scores = extra.get("scores") or {}
    return scores if isinstance(scores, dict) else {}


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def get_final_decision(event: dict[str, Any]) -> dict[str, Any]:
    extra = get_extra(event)
    decision = extra.get("final_decision") or extra.get("oracle_routing") or {}
    return decision if isinstance(decision, dict) else {}


def get_global_tag_emission(event: dict[str, Any]) -> dict[str, Any]:
    extra = get_extra(event)
    emission = extra.get("global_tag_emission") or {}
    return emission if isinstance(emission, dict) else {}


def combined_text(event: dict[str, Any]) -> str:
    extra = get_extra(event)
    parts = [
        str(event.get("title") or ""),
        str(event.get("body") or ""),
        str(extra.get("impact_category") or ""),
        str(extra.get("risk_bucket") or ""),
    ]
    return " ".join(p for p in parts if p).lower()


def extract_candidate_directives(event: dict[str, Any]) -> list[dict[str, Any]]:
    emission = get_global_tag_emission(event)
    payload = emission.get("oracle_review_payload") or {}
    directives = payload.get("candidate_directives") or emission.get("candidate_directives") or []
    if not isinstance(directives, list):
        return []

    # Não mandar directives neutras como sugestão forte ao Oracle.
    filtered: list[dict[str, Any]] = []
    for directive in directives:
        if not isinstance(directive, dict):
            continue
        if str(directive.get("bias", "")).lower() == "neutral":
            continue
        filtered.append(directive)
    return filtered


def oracle_candidate_reason(event: dict[str, Any]) -> tuple[bool, str, int]:
    """
    Retorna:
      - se vale mandar ao Oracle
      - motivo
      - prioridade numérica para ordenar os testes

    Política de custo:
      1. Sempre mandar candidatos que o router local teria emitido como GlobalTag.
      2. Mandar eventos já marcados como sent_to_oracle/oracle_review_requested.
      3. Mandar eventos com market impact alto e rota clara.
      4. Mandar geopolítico crítico sem rota clara só se passar limite.
      5. Não mandar ruído, histórico, promo, fofoca ou micro battlefield sem mercado.
    """
    extra = get_extra(event)
    scores = get_scores(event)
    final_decision = get_final_decision(event)
    emission = get_global_tag_emission(event)

    text = combined_text(event)
    impact_category = str(extra.get("impact_category") or "").lower()

    noise = safe_float(scores.get("noise_score"))
    market = safe_float(scores.get("market_impact_score"))
    geo = safe_float(scores.get("geopolitical_severity_score"))
    route = safe_float(scores.get("asset_route_confidence_score"))
    oracle = safe_float(scores.get("oracle_review_score"))
    trade = safe_float(final_decision.get("trade_emit_score", emission.get("trade_emit_score", 0.0)))

    noisy_category = any(
        term in impact_category
        for term in [
            "sports",
            "celebrity",
            "entertainment",
            "generic news",
            "daily politics",
        ]
    )
    local_or_historical = any(
        term in text
        for term in [
            "anniversary",
            "years since",
            "youtube",
            "subscriber",
            "falling trees",
            "trees on cars",
        ]
    )

    if noise >= 0.70 or noisy_category or local_or_historical:
        return False, "noise_or_non_actionable_filtered", 0

    # Antigo "emitted=true" agora significa: candidato forte a tag, precisa do Oracle.
    if bool(final_decision.get("emitted")) or bool(emission.get("emitted")):
        return True, "candidate_global_tag_local_router", 100

    if bool(final_decision.get("sent_to_oracle")) or bool(emission.get("oracle_review_requested")):
        if market >= 0.70 and route >= 0.60:
            return True, "oracle_review_high_market_clear_route", 95
        if oracle >= MIN_ORACLE_REVIEW and market >= 0.50:
            return True, "oracle_review_market_relevant", 90
        if geo >= MIN_GEO_SEVERITY:
            return True, "oracle_review_geopolitical_critical", 75
        # Economiza custo: não manda review geopolítico/humanitário retrospectivo com mercado baixo.
        if market < 0.20 and "investigation" in impact_category:
            return False, "low_market_retrospective_investigation_filtered", 0
        return True, "oracle_review_router_selected", 70

    if trade >= MIN_TRADE_EMIT:
        return True, "trade_emit_score_candidate", 90

    if market >= MIN_MARKET_IMPACT and route >= 0.65:
        return True, "high_market_impact_clear_asset_route", 85

    if geo >= MIN_GEO_SEVERITY and market >= 0.20:
        return True, "critical_geo_with_some_market_channel", 65

    # Casos semânticos fortes para petróleo/risk-off.
    if any(term in text for term in ["hormuz", "naval blockade", "oil prices", "shipping route", "oil trade"]):
        if market >= 0.45:
            return True, "strategic_oil_or_chokepoint_keyword", 80

    return False, "below_oracle_candidate_thresholds", 0


def build_oracle_request(event: dict[str, Any], reason: str, priority: int) -> dict[str, Any]:
    extra = get_extra(event)
    scores = get_scores(event)
    final_decision = get_final_decision(event)
    emission = get_global_tag_emission(event)
    directives = extract_candidate_directives(event)

    event_id = event.get("id") or event.get("event_id") or emission.get("trigger_event_id")

    return {
        "event_type": "IA_TREND_ORACLE_REQUESTED",
        "oracle_request_version": "oracle_request_v1",
        "trigger_event_id": event_id,
        "routing": {
            "send_to_oracle": True,
            "routing_reason": reason,
            "priority": priority,
            "candidate_global_tag": bool(final_decision.get("emitted")) or bool(emission.get("emitted")),
            "candidate_directives": directives,
            "local_final_decision": final_decision,
            "local_global_tag_emission_legacy": emission,
            "scores_snapshot": scores,
        },
        "enriched_event": event,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def build_oracle_user_prompt(oracle_request: dict[str, Any]) -> str:
    """
    User message enviada ao Gemini.
    O system prompt já contém o schema; aqui a gente só passa a requisição
    real do pipeline e reforça que não é pergunta manual.
    """
    return json.dumps(
        {
            "instruction": (
                "Evaluate this IA Trend Oracle request. "
                "This is an enriched pipeline event, not a manual question. "
                "Return only valid JSON following the system schema. "
                "Only create an official Global Tag if the evidence is actionable."
            ),
            "oracle_request": oracle_request,
        },
        ensure_ascii=False,
        indent=2,
    )


def build_oracle_messages(enriched_events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for index, event in enumerate(enriched_events, start=1):
        ok, reason, priority = oracle_candidate_reason(event)
        event_id = event.get("id") or event.get("event_id") or f"event_{index:04d}"
        title = str(event.get("title") or "")[:160]

        audit_record = {
            "index": index,
            "id": event_id,
            "title": title,
            "selected": ok,
            "reason": reason,
            "priority": priority,
            "scores": get_scores(event),
            "final_decision": get_final_decision(event),
        }

        if not ok:
            rejected.append(audit_record)
            continue

        oracle_request = build_oracle_request(event, reason, priority)
        selected.append(
            {
                "id": str(event_id),
                "content_type": "ia_trend_oracle_request",
                "routing_reason": reason,
                "priority": priority,
                "title": title,
                "oracle_request": oracle_request,
                "content": build_oracle_user_prompt(oracle_request),
            }
        )

    selected.sort(key=lambda msg: int(msg.get("priority", 0)), reverse=True)

    if MAX_MESSAGES > 0:
        selected = selected[:MAX_MESSAGES]

    return selected, rejected


# ──────────────────────────────────────────────────────────────────────────────
# Gemini model rotation
# ──────────────────────────────────────────────────────────────────────────────

async def descobrir_modelos_disponiveis(client: genai.Client) -> list[str]:
    print("🔍 Consultando modelos disponíveis na API...")

    response = client.models.list()
    modelos_validos: list[str] = []

    for model in response:
        supported_actions = getattr(model, "supported_actions", []) or []
        name = getattr(model, "name", "")

        if "generateContent" not in supported_actions:
            continue
        if not name.startswith("models/gemini-"):
            continue

        nome_limpo = name.replace("models/", "")

        if MODEL_ALLOWLIST and nome_limpo not in MODEL_ALLOWLIST:
            continue

        if any(deny in nome_limpo for deny in MODEL_DENYLIST):
            continue

        if not INCLUDE_ROBOTICS_MODELS and "robotics" in nome_limpo:
            continue

        if "image" in nome_limpo:
            continue

        modelos_validos.append(nome_limpo)

    modelos_validos = sorted(set(modelos_validos), reverse=True)
    print(f"✅ Modelos encontrados: {len(modelos_validos)}")
    return modelos_validos


async def process_single_message(message: dict[str, Any], semaphore: asyncio.Semaphore) -> dict[str, Any]:
    msg_id = message.get("id")
    content = message.get("content")
    oracle_request = message.get("oracle_request")

    total_modelos = len(MODELOS_ATIVOS)
    if total_modelos == 0:
        return {"id": msg_id, "status": "error", "error_message": "Nenhum modelo ativo carregado."}

    async with semaphore:
        for attempt in range(MAX_RETRIES):
            index_atual = attempt % total_modelos
            modelo_atual = MODELOS_ATIVOS[index_atual]

            print(f"[{msg_id}] Processando Oracle (Modelo: {modelo_atual}) | Tent. {attempt + 1}/{MAX_RETRIES}...")

            try:
                response = await client.aio.models.generate_content(
                    model=modelo_atual,
                    contents=content,
                    config=configuracao_playground,
                )

                if response.candidates and response.candidates[0].finish_reason in [
                    types.FinishReason.SAFETY,
                    types.FinishReason.BLOCKLIST,
                ]:
                    print(f"[{msg_id}] Erro: Bloqueado por segurança.")
                    return {
                        "id": msg_id,
                        "status": "blocked_by_safety",
                        "oracle_request": oracle_request,
                        "model_used": modelo_atual,
                    }

                parsed_json = parse_llm_json(response.text)

                print(f"[{msg_id}] ✅ Sucesso com {modelo_atual}.")
                await asyncio.sleep(1.0)

                return {
                    "id": msg_id,
                    "status": "success",
                    "model_used": modelo_atual,
                    "routing_reason": message.get("routing_reason"),
                    "priority": message.get("priority"),
                    "title": message.get("title"),
                    "oracle_request": oracle_request,
                    "oracle_result": parsed_json,
                    "raw_response": response.text,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }

            except Exception as e:
                error_msg = str(e)

                if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                    if attempt < MAX_RETRIES - 1:
                        proximo_index = (attempt + 1) % total_modelos
                        proximo_modelo = MODELOS_ATIVOS[proximo_index]

                        print(f"[{msg_id}] ⚠️ Cota do {modelo_atual} esgotada. Rotacionando para {proximo_modelo}...")

                        if proximo_index == 0:
                            print(f"[{msg_id}] 🔄 Ciclo completo! Pausa de segurança de 10s...")
                            await asyncio.sleep(10.0)
                        else:
                            await asyncio.sleep(2.0)

                        continue

                    print(f"[{msg_id}] ❌ Falha fatal: cota esgotada após {MAX_RETRIES} tentativas.")
                    return {
                        "id": msg_id,
                        "status": "error",
                        "error_message": "Rate limit esgotado em todas as rotações.",
                        "oracle_request": oracle_request,
                    }

                print(f"[{msg_id}] Erro crítico: {error_msg}")
                return {
                    "id": msg_id,
                    "status": "error",
                    "error_message": error_msg,
                    "oracle_request": oracle_request,
                }

    return {
        "id": msg_id,
        "status": "error",
        "error_message": "Fluxo de tentativas encerrado sem retorno.",
        "oracle_request": oracle_request,
    }


async def main() -> None:
    raw_payload = await load_json(INPUT_FILE)
    if not raw_payload:
        return

    if isinstance(raw_payload, dict):
        # Suporte a payloads envelopados.
        enriched_events = raw_payload.get("items") or raw_payload.get("events") or raw_payload.get("data") or []
    else:
        enriched_events = raw_payload

    if not isinstance(enriched_events, list):
        raise ValueError("Arquivo de entrada deve ser uma lista de eventos ou um objeto com items/events/data.")

    # Se ainda vier mock antigo com content livre, processa como fallback.
    if enriched_events and isinstance(enriched_events[0], dict) and "content" in enriched_events[0] and "extra" not in enriched_events[0]:
        print("⚠️ Entrada parece mock_messages antigo. Processando diretamente, sem filtro de Oracle.")
        oracle_messages = enriched_events
        rejected: list[dict[str, Any]] = []
    else:
        oracle_messages, rejected = build_oracle_messages(enriched_events)

    await save_json(
        CANDIDATES_FILE,
        {
            "input_file": str(INPUT_FILE),
            "selected_count": len(oracle_messages),
            "rejected_count": len(rejected),
            "selected": [
                {
                    "id": msg.get("id"),
                    "title": msg.get("title"),
                    "routing_reason": msg.get("routing_reason"),
                    "priority": msg.get("priority"),
                }
                for msg in oracle_messages
            ],
            "rejected": rejected,
        },
    )

    await save_json(MESSAGES_FILE, oracle_messages)

    if not oracle_messages:
        print("⚠️ Nenhuma mensagem candidata ao IA Trend Oracle.")
        return

    global MODELOS_ATIVOS
    MODELOS_ATIVOS = await descobrir_modelos_disponiveis(client)

    if not MODELOS_ATIVOS:
        print("❌ Nenhum modelo compatível encontrado!")
        return

    print(f"🚀 Modelos carregados dinamicamente: {MODELOS_ATIVOS}")
    print(f"🚀 Iniciando IA Trend Oracle. Candidatos: {len(oracle_messages)} | Concorrência={CONCURRENCY}")

    semaphore = asyncio.Semaphore(CONCURRENCY)
    tasks = [process_single_message(msg, semaphore) for msg in oracle_messages]
    results = await asyncio.gather(*tasks)

    await save_json(OUTPUT_FILE, list(results))


MODELOS_ATIVOS: list[str] = []

if __name__ == "__main__":
    asyncio.run(main())
