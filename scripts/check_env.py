"""Quick .env validation — run: venv\\Scripts\\python.exe scripts\\check_env.py"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings


async def main() -> None:
    s = get_settings()
    print("=== .env check ===")
    print("twilio:", "OK" if s.twilio_configured else "MISSING")
    print("deepgram:", "OK" if s.deepgram_key else "MISSING")
    print("groq:", "OK" if s.groq_api_key else "MISSING")
    print("mongo_uri:", "OK" if s.mongodb_uri and "mongodb" in s.mongodb_uri else "MISSING")
    print("public_url:", s.public_base_url)
    print("media_ws:", s.media_stream_ws_url)

    try:
        from motor.motor_asyncio import AsyncIOMotorClient

        client = AsyncIOMotorClient(s.mongodb_uri)
        await client.admin.command("ping")
        print("mongo_ping: OK")
        client.close()
    except Exception as e:
        print("mongo_ping: FAIL —", e)

    try:
        from app.services.media_stream import MediaStreamSession

        print("media_stream.py: OK")
    except Exception as e:
        print("media_stream.py: FAIL —", e)


if __name__ == "__main__":
    asyncio.run(main())
