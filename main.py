import argparse
import logging
import random
import sys
import time

from kb.config import load_config
from kb.filters import KeywordFilter
from kb.scraper import Scraper
from kb.storage import Storage
from kb.telegram import TelegramClient, build_messages

logger = logging.getLogger("kb")


def run_once(cfg, scraper, flt, storage, tg, dry_run: bool) -> None:
    if dry_run:
        stubs = scraper.search(cfg.search_url, cfg.max_pages)
    else:
        stubs = scraper.search(cfg.search_url, cfg.max_pages, is_known=lambda s: storage.has(s.ad_id))

    if dry_run:
        # Предпросмотр: показываем все подходящие объявления на страницах, БД не читаем и не пишем.
        candidates = stubs
    else:
        candidates = [s for s in stubs if not storage.has(s.ad_id)]
        logger.info("%d new ads to check", len(candidates))

        # Первый запуск: запоминаем уже висящие объявления, но не постим — иначе канал зальётся старыми.
        if storage.is_empty() and cfg.seed_on_first_run:
            for s in candidates:
                storage.mark(s.ad_id, s.url, s.title, "seeded")
            logger.info("First run: seeded %d existing ads without posting", len(candidates))
            return

    def mark(stub, status):
        if not dry_run:
            storage.mark(stub.ad_id, stub.url, stub.title, status)

    posted = 0
    for stub in candidates:
        try:
            listing = scraper.fetch_details(stub)
        except Exception:
            # Не помечаем — попробуем в следующем цикле.
            logger.exception("Failed to fetch %s", stub.url)
            continue

        if listing.is_commercial:
            mark(stub, "rejected:commercial")
            continue
        if listing.offer_type and listing.offer_type != "Angebot":
            mark(stub, "rejected:not-offer")
            continue

        verdict = flt.evaluate(f"{listing.title}\n{listing.description}")
        if not verdict.accepted:
            mark(stub, f"rejected:{verdict.reason}")
            continue

        messages = build_messages(listing)
        photos = listing.photo_urls[: cfg.max_photos]
        if dry_run:
            print(f"===== {stub.ad_id} | match={verdict.matches} | photos={len(photos)} | messages={len(messages)}")
            for i, msg in enumerate(messages, 1):
                print(f"--- msg {i}\n{msg}\n")
            posted += 1
            continue

        tg.send_listing(messages, photos)
        mark(stub, "posted")
        posted += 1
        logger.info("Posted %s (%s)", stub.ad_id, verdict.matches)

    logger.info("Cycle done: %s %d", "matches (dry run)" if dry_run else "posted", posted)


def main() -> int:
    # Windows-консоль по умолчанию cp1252 — эмодзи и немецкие символы ломают print().
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Kleinanzeigen -> Telegram bot")
    parser.add_argument("--once", action="store_true", help="run a single cycle and exit")
    parser.add_argument("--dry-run", action="store_true", help="print matches instead of posting, no DB writes")
    parser.add_argument("--test-telegram", action="store_true", help="send a test message and exit")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()

    if args.test_telegram:
        TelegramClient(cfg.telegram_token, cfg.telegram_chat_id).send_text("✅ Тест: бот подключён")
        print("Test message sent")
        return 0

    if "PASTE" in cfg.search_url or not cfg.search_url.startswith("https://www.kleinanzeigen.de/"):
        print("Заполните search_url в config.json (ссылка с нужными фильтрами).")
        return 1
    if not args.dry_run and (not cfg.telegram_token or not cfg.telegram_chat_id):
        print("Заполните TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID в .env")
        return 1

    scraper = Scraper()
    flt = KeywordFilter(
        cfg.positive_patterns, cfg.negation_words, cfg.after_negation_words, cfg.negation_frames
    )
    storage = Storage(cfg.db_path)
    tg = TelegramClient(cfg.telegram_token, cfg.telegram_chat_id)

    try:
        while True:
            try:
                run_once(cfg, scraper, flt, storage, tg, args.dry_run)
            except Exception:
                logger.exception("Cycle failed, will retry next interval")
            if args.once:
                break
            wait = cfg.interval_minutes * 60 + random.uniform(0, cfg.jitter_minutes * 60)
            logger.info("Sleeping %.0f s", wait)
            time.sleep(wait)
    except KeyboardInterrupt:
        logger.info("Stopped")
    finally:
        storage.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
