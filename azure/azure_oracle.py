import os
import base64
import asyncio
from openai import AsyncAzureOpenAI
from dotenv import load_dotenv

# Path to the .env file in the same directory
load_dotenv()

async def main() -> None:
    # Map the variables to what is actually in your .env file
    AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT").rstrip("/")
    AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
    AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")
    AZURE_OPENAI_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")

    print(f"--- Azure OpenAI Debug ---")
    print(f"Endpoint: {AZURE_OPENAI_ENDPOINT}")
    print(f"Deployment: {AZURE_OPENAI_DEPLOYMENT_NAME}")
    print(f"Version: {AZURE_OPENAI_API_VERSION}")
    print(f"API Key Set: {'Yes' if AZURE_OPENAI_API_KEY else 'No'}")
    print(f"--------------------------")

    if not AZURE_OPENAI_API_KEY or not AZURE_OPENAI_ENDPOINT:
        print("Error: Missing AZURE_OPENAI_ENDPOINT or AZURE_OPENAI_ENDPOINT_Key in .env")
        return

    client = AsyncAzureOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_API_KEY,
        api_version=AZURE_OPENAI_API_VERSION or "2024-10-01-preview",
    )

    # The official Realtime pattern
    async with client.beta.realtime.connect(model=AZURE_OPENAI_DEPLOYMENT_NAME) as connection:
        await connection.session.update(session={
            "instructions": "You are a helpful assistant.",
            "modalities": ["text", "audio"],
        })

        print("Start chatting with the AI (type 'q' to quit):")
        while True:
            user_input = await asyncio.to_thread(input, "You: ")
            if user_input.lower() == "q": break

            await connection.conversation.item.create(
                item={
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": user_input}],
                }
            )
            await connection.response.create()

            async for event in connection:
                if event.type == "response.audio_transcript.delta":
                    print(event.delta, end="", flush=True)
                elif event.type == "response.done":
                    print()
                    break
                elif event.type == "error":
                    print(f"\nError: {event.error}")
                    break

if __name__ == "__main__":
    asyncio.run(main())
