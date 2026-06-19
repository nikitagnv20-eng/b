name: Listing Bot

on:
  schedule:
    - cron: '0 * * * *'   # запуск каждый час (время UTC)
  workflow_dispatch:        # кнопка "Run workflow" для запуска вручную

permissions:
  contents: write   # нужно, чтобы бот мог сохранять список уже отправленных объявлений

jobs:
  run-bot:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run bot
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: python listing_bot.py

      - name: Save sent listings history
        run: |
          git config user.name "listing-bot"
          git config user.email "bot@users.noreply.github.com"
          git add sent_listings.json
          git diff --staged --quiet || git commit -m "update sent listings"
          git push
