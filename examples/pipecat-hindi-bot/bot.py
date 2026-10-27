# Synthetic example for voice-doctor tests: a Hindi COD-confirmation bot on Pipecat 1.x over a
# telephony websocket. Parameter names follow pipecat-ai 1.14.0; the mistakes are on purpose.
import os

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair, LLMUserAggregatorParams
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.sarvam.stt import SarvamSTTService
from pipecat.services.sarvam.tts import SarvamTTSService
from pipecat.transcriptions.language import Language
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport
from pipecat.turns.user_start import TranscriptionUserTurnStartStrategy, VADUserTurnStartStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies

SYSTEM = (
    "You are Neha from Acme Bazaar. Confirm the customer's cash on delivery order. "
    "Read out the order number #AB-20931 and the amount ₹1,499. Customers may speak Hindi or Kannada; "
    "always reply in the language the customer uses. Give complete information about the order."
)


async def run_bot(websocket, serializer):
    transport = FastAPIWebsocketTransport(
        websocket, FastAPIWebsocketParams(audio_in_enabled=True, audio_out_enabled=True, serializer=serializer)
    )
    stt = SarvamSTTService(
        api_key=os.environ["SARVAM_API_KEY"],
        settings=SarvamSTTService.Settings(model="saaras:v4", language=Language.HI_IN),
    )
    tts = SarvamTTSService(
        api_key=os.environ["SARVAM_API_KEY"],
        settings=SarvamTTSService.Settings(model="bulbul:v3", voice="shubh"),
    )
    llm = OpenAILLMService(
        api_key=os.environ["OPENAI_API_KEY"],
        settings=OpenAILLMService.Settings(model="gpt-5.4-mini", extra={"reasoning_effort": "high"}),
    )
    context = LLMContext(messages=[{"role": "system", "content": SYSTEM}])
    user_agg, assistant_agg = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.8)),
            user_turn_strategies=UserTurnStrategies(
                start=[VADUserTurnStartStrategy(enable_interruptions=False),
                       TranscriptionUserTurnStartStrategy(enable_interruptions=False)]
            ),
        ),
    )
    pipeline = Pipeline([transport.input(), stt, user_agg, llm, tts, transport.output(), assistant_agg])
    task = PipelineTask(pipeline, params=PipelineParams(allow_interruptions=True), idle_timeout_secs=None)

    @transport.event_handler("on_client_connected")
    async def on_connected(transport, client):
        await task.queue_frames([LLMRunFrame()])
