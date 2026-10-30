import argparse
import logging
import os
import random
import sys
import time

from dotenv import load_dotenv

from kb.agent_api import AgentClient, AgentError, CreditsExhausted, to_listing
from kb.config import load_config
from kb.filters import KeywordFilter, is_tenant_wanted
from kb.scraper import Scraper
from kb.storage import Storage
from kb.telegram import TelegramClient, build_messages
from kb.translate import Translator

logger = logging.getLogger("kb")


def handle_listing(listing, cfg, flt, tg, translator, dry_run: bool, mark) -> bool:
    """Общая проверка и публикация для любого источника. Возвращает True, если объявление подошло."""
    if is_tenant_wanted(listing.title, listing.description):
        mark(listing, "rejected:tenant-wanted")
        return False
    if listing.is_commercial:
        mark(listing, "rejected:commercial")
        return False
    if listing.offer_type and listing.offer_type != "Angebot":
        mark(listing, "rejected:not-offer")
        return False

    verdict = flt.evaluate(f"{listing.title}\n{listing.description}")
    if not verdict.accepted:
        mark(listing, f"rejected:{verdict.reason}")
        return False

    messages = build_messages(listing, translator)
    photos = listing.photo_urls[: cfg.max_photos]
    if dry_run:
        print(f"===== {listing.ad_id} | match={verdict.matches} | photos={len(photos)} | messages={len(messages)}")
        for i, msg in enumerate(messages, 1):
            print(f"--- msg {i}\n{msg}\n")
        return True

    tg.send_listing(messages, photos)
    mark(listing, "posted")
    logger.info("Posted %s (%s)", listing.ad_id, verdict.matches)
    return True


def run_once_scraper(cfg, scraper, flt, storage, tg, translator, dry_run: bool) -> None:
    if dry_run:
        stubs = scraper.search(cfg.search_url, cfg.max_pages)
    else:
        stubs = scraper.search(cfg.search_url, cfg.max_pages, is_known=lambda s: storage.has(s.ad_id))
        candidates = [s for s in stubs if not storage.has(s.ad_id)]
        logger.info("%d new ads to check", len(candidates))
        # Первый запуск: запоминаем уже висящие объявления, но не постим — иначе канал зальётся старыми.
        if storage.is_empty() and cfg.seed_on_first_run:
            for s in candidates:
                storage.mark(s.ad_id, s.url, s.title, "seeded")
            logger.info("First run: seeded %d existing ads without posting", len(candidates))
            return
    if dry_run:
        candidates = stubs

    def mark(listing, status):
        if not dry_run:
            storage.mark(listing.ad_id, listing.url, listing.title, status)

    posted = 0
    for stub in candidates:
        try:
            listing = scraper.fetch_details(stub)
        except Exception:
            # Не помечаем — попробуем в следующем цикле.
            logger.exception("Failed to fetch %s", stub.url)
            continue
        posted += handle_listing(listing, cfg, flt, tg, translator, dry_run, mark)
    logger.info("Cycle done: %s %d", "matches (dry run)" if dry_run else "posted", posted)


def run_once_api(cfg, client, flt, storage, tg, translator, dry_run: bool) -> None:
    data = client.search(cfg.api_query, cfg.api_category_id)
    ads = data.get("ads", [])
    total = (data.get("meta") or {}).get("total", len(ads))
    if total > len(ads):
        logger.warning("API: %d matches in total, only the first %d are checked this cycle", total, len(ads))

    if dry_run:
        candidates = ads
    else:
        candidates = [a for a in ads if not storage.has(str(a["ad_id"]))]
        logger.info("API: %d matches, %d new", len(ads), len(candidates))
        if storage.is_empty() and cfg.seed_on_first_run:
            for a in candidates:
                storage.mark(str(a["ad_id"]), a.get("ad_url", ""), a.get("title", ""), "seeded")
            logger.info("First run: seeded %d existing ads without posting", len(candidates))
            return

    def mark(listing, status):
        if not dry_run:
            storage.mark(listing.ad_id, listing.url, listing.title, status)

    # В режиме предпросмотра карточки не тратим больше трёх, чтобы не сжечь кредиты.
    detail_budget = 3 if dry_run else None
    posted = 0
    for ad in candidates:
        ad_id = str(ad["ad_id"])
        if is_tenant_wanted(ad.get("title", "")):
            # Заголовок уже говорит, что это арендатор: карточку не запрашиваем, кредит не тратим.
            if not dry_run:
                storage.mark(ad_id, ad.get("ad_url", ""), ad.get("title", ""), "rejected:tenant-wanted")
            continue
        if detail_budget is not None:
            if detail_budget == 0:
                break
            detail_budget -= 1
        try:
            listing = to_listing(client.ad(ad_id))
        except CreditsExhausted:
            raise
        except (AgentError, KeyError, ValueError):
            logger.exception("Failed to load ad %s", ad_id)
            continue
        posted += handle_listing(listing, cfg, flt, tg, translator, dry_run, mark)
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
    load_dotenv()
    cfg = load_config()

    if args.test_telegram:
        TelegramClient(cfg.telegram_token, cfg.telegram_chat_id).send_text("✅ Тест: бот подключён")
        print("Test message sent")
        return 0

    if cfg.source == "scraper" and ("PASTE" in cfg.search_url or not cfg.search_url.startswith("https://www.kleinanzeigen.de/")):
        print("Заполните search_url в config.json (ссылка с нужными фильтрами).")
        return 1
    if cfg.source == "api" and not os.environ.get("KLAZ_API_KEY"):
        print("Для source=api заполните KLAZ_API_KEY в .env")
        return 1
    if not args.dry_run and (not cfg.telegram_token or not cfg.telegram_chat_id):
        print("Заполните TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID в .env")
        return 1

    flt = KeywordFilter(cfg.positive_patterns, cfg.negation_words, cfg.after_negation_words, cfg.negation_frames)
    storage = Storage(cfg.db_path)
    tg = TelegramClient(cfg.telegram_token, cfg.telegram_chat_id)
    translator = Translator(os.environ.get("DEEPL_API_KEY", ""))
    if cfg.source == "api":
        client = AgentClient(os.environ["KLAZ_API_KEY"])
        cycle = lambda: run_once_api(cfg, client, flt, storage, tg, translator, args.dry_run)  # noqa: E731
    else:
        scraper = Scraper()
        cycle = lambda: run_once_scraper(cfg, scraper, flt, storage, tg, translator, args.dry_run)  # noqa: E731

    try:
        while True:
            try:
                cycle()
            except CreditsExhausted as exc:
                logger.error("Kleinanzeigen Agent credits exhausted, stopping: %s", exc)
                break
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
