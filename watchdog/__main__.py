import asyncio
from watchdog.llm_watchdog import main, cleanup

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        cleanup()
