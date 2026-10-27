# Synthetic example for voice-doctor tests: a Hindi insurance-renewal agent on LiveKit Agents 1.x
# taking SIP calls. Parameter names follow livekit-agents 1.8.9; the mistakes are on purpose.
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, cli, room_io
from livekit.plugins import openai, sarvam, silero
from livekit.plugins.turn_detector.english import EnglishModel


class RenewalAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=(
                "## Role\n"
                "You are Priya from **Acme Insurance**. You call customers whose policy expires this month.\n"
                "## Steps\n"
                "1. Tell them the premium is ₹12,500 and the policy number is AI-2026-77831.\n"
                "2. Explain all the plan benefits in detail.\n"
                "3. Send them to https://acme-insurance.example/renew to pay.\n"
            )
        )

    async def on_enter(self) -> None:
        self.session.say(
            "Namaste! Main Priya bol rahi hoon Acme Insurance se. Aapki policy is mahine expire ho rahi hai, "
            "premium ₹12,500 hai. Kya aap renew karna chahenge? Aur kya aapka address same hai?"
        )


server = AgentServer()


@server.rtc_session(agent_name="hindi-renewals-sip")
async def entrypoint(ctx: JobContext):
    session = AgentSession(
        stt=sarvam.STT(language="hi-IN", model="saarika:v2.5"),
        llm=openai.LLM(model="gpt-5.4-mini", reasoning_effort="high"),
        tts=sarvam.TTS(model="bulbul:v3", speaker="shubh"),
        vad=silero.VAD.load(min_silence_duration=0.55),
        turn_detection=EnglishModel(),
        min_endpointing_delay=0.2,
        max_endpointing_delay=3.0,
        allow_interruptions=False,
        user_away_timeout=None,
    )
    await session.start(agent=RenewalAgent(), room=ctx.room, room_options=room_io.RoomOptions())


if __name__ == "__main__":
    cli.run_app(server)
