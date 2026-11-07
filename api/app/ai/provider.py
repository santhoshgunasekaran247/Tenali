import logging
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING

from openai import APIConnectionError, APIStatusError, OpenAI
from pydantic import ValidationError

from app.ai.schemas import AssistantOutput, ReadAssistantOutput, ReadLookup

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderResult:
    output: AssistantOutput | None
    input_tokens: int | None
    cached_tokens: int | None
    output_tokens: int | None
    reference: str | None
    error: str | None = None
    lookups: tuple[ReadLookup, ...] = ()


def estimated_cost(input_tokens: int, output_tokens: int, input_rate: Decimal, output_rate: Decimal) -> Decimal:
    # Charge cached input at the full rate conservatively; actual provider billing may be lower.
    return ((input_tokens * input_rate + output_tokens * output_rate) / Decimal(1000000)).quantize(Decimal("0.00000001"), rounding=ROUND_CEILING)


class OpenAIProvider:
    def respond(self, context: str, content: str, config: dict) -> ProviderResult:
        read_enabled = bool(config.get("_read_capabilities"))
        output_schema = ReadAssistantOutput if read_enabled else AssistantOutput
        try:
            with OpenAI(base_url="https://api.openai.com/v1", timeout=config["timeout_seconds"], max_retries=0) as client:
                response = client.responses.create(
                    model=config["routine_model"], store=False,
                    instructions=context, input=content,
                    max_output_tokens=config["max_output_tokens"],
                    text={"format": {"type": "json_schema", "name": "tenali_reply",
                                     "schema": output_schema.model_json_schema(), "strict": True}},
                )
        except APIConnectionError:
            logger.warning("AI provider transport outcome unknown")
            return ProviderResult(None, None, None, None, None, "provider_unknown")
        except APIStatusError as error:
            logger.warning("AI provider rejected request: HTTP %s", error.status_code)
            return ProviderResult(None, None, None, None, error.request_id, "provider_rejected")
        usage = response.usage
        if not usage:
            logger.warning("AI response missing usage metadata")
            return ProviderResult(None, None, None, None, response.id, "usage_unknown")
        output = None
        lookups = ()
        error_code = None
        if response.status != "completed":
            error_code = "response_incomplete"
        else:
            try:
                parsed = output_schema.model_validate_json(response.output_text)
                output = AssistantOutput(reply=parsed.reply, clarification=parsed.clarification)
                if isinstance(parsed, ReadAssistantOutput):
                    lookups = tuple(parsed.lookups)
                length = len(output.reply) + (len(output.clarification) + 2 if output.clarification else 0)
                if not output.reply.strip() or length > (4000 if read_enabled else 12000):
                    output = None
                    error_code = "invalid_response"
            except ValidationError:
                error_code = "invalid_response"
            if error_code:
                logger.warning("AI response was not a usable structured reply (%s)", error_code)
        return ProviderResult(output, usage.input_tokens, usage.input_tokens_details.cached_tokens,
                              usage.output_tokens, response.id, error_code, lookups if not error_code else ())
