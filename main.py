"""
main.py
Entry point for crypto-compound-bot.
Paper trading mode only.
"""

from bot.runner import BotRunner


def main():
    bot = BotRunner()
    bot.run()


if __name__ == "__main__":
    main()
