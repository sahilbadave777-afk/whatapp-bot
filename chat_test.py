"""Chat with the bot in your terminal - no WhatsApp needed.
Uses your real Shopify store. Free mode by default (BOT_MODE=ai uses Claude).

    python chat_test.py
"""
import config

if config.BOT_MODE == "ai":
    from agent import SalesAgent
    bot = SalesAgent()
else:
    from simple_bot import SimpleBot
    bot = SimpleBot()
print(f"RPS bot test chat ({config.BOT_MODE} mode). Type a question (or 'quit').\n")
while True:
    try:
        text = input("You: ").strip()
    except (EOFError, KeyboardInterrupt):
        break
    if text.lower() in {"quit", "exit"}:
        break
    if not text:
        continue
    reply = bot.reply("terminal-test", "Tester", text)
    print(f"\nBot: {reply.text}")
    for url, caption in reply.photos:
        print(f"[photo] {caption}: {url}")
    print()
