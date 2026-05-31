"""Entry point for mm-agent-bridge."""

from __future__ import annotations

import logging
import signal
import sys

from dotenv import load_dotenv

from .config import Config
from .bot import AgentBridge


def main() -> None:
    """Load configuration and start the bot."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)

    load_dotenv()

    try:
        config = Config.from_env()
    except ValueError as exc:
        logger.error("Configuration error: %s", exc)
        sys.exit(1)

    logger.info("Starting mm-agent-bridge (agent=%s)", config.agent_type)
    bot = AgentBridge(config=config)

    def _handle_sigterm(signum: int, frame: object) -> None:
        logger.info("Received signal %s, shutting down...", signum)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_sigterm)

    bot.run()


if __name__ == "__main__":
    main()
