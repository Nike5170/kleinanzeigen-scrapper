# KleinanzeigenBot

Бот следит за объявлениями аренды на kleinanzeigen.de и постит новые подходящие в Telegram-канал
(`@rent_germany`): фото альбомом, заголовок, цену, локацию, все характеристики (Wohnfläche, Zimmer,
Warmmiete, Kaution, Verfügbar ab и т.д.), описание и ссылку. Длинный текст и много фото делятся на несколько сообщений.

Официального API у Kleinanzeigen нет, поэтому бот читает публичные страницы поиска и объявлений.
См. раздел «Важно» ниже.

## Как работает

1. Каждые `interval_minutes` (+ случайная добавка до `jitter_minutes`) открывает страницы поиска по `search_url` из `config.json`.
2. Для каждого объявления, которого ещё нет в `seen.db`, открывает страницу объявления.
3. Отбрасывает:
   - коммерческих продавцов (`gewerblich`) и всё, что не `Angebot`;
   - объявления, где нет разрешающего упоминания Jobcenter, или оно отрицается (см. «Валидация Jobcenter»).
4. Подходящие отправляет в канал и записывает в `seen.db`, чтобы не постить дважды.

## Установка

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Telegram

- Бот `@Scrap_klein_bot` добавлен админом канала `@rent_germany` (право публикации сообщений).
- Секреты лежат в `.env` (он в `.gitignore`, в репозиторий не попадает):
  ```
  TELEGRAM_BOT_TOKEN=...
  TELEGRAM_CHAT_ID=@rent_germany
  ```
- **Токен уже был показан в переписке.** Рекомендуется перевыпустить его у `@BotFather` (`/revoke`), затем обновить `.env`.
- Проверка связи: `python main.py --test-telegram`

## Поиск (фильтры)

Фильтры задаёт сам сайт, бот использует ссылку из `config.json` → `search_url`:

```
https://www.kleinanzeigen.de/s-wohnung-mieten/sortierung:neuste/anbieter:privat/anzeige:angebote/c203
```

Категория Mietwohnungen, Deutschland, Privat, Angebot, сортировка по новизне. Чтобы сменить фильтры, поменяйте ссылку в браузере и вставьте новую.
Дополнительно бот сам проверяет тип продавца и тип объявления на странице объявления.

## Валидация Jobcenter

Файлы: `kb/filters.py` (логика), `config.json` (шаблоны), `tests/test_filters.py` (более 60 формулировок).

Считается разрешающим упоминание:
- `Jobcenter` в любом написании: `Job-Center`, `Job Center`, `JobCenter`, `Jobcentre`, `Jobcenters`, с любым дефисом (в т.ч. «–»);
- `ARGE` (старое название Jobcenter), `JC`, `SGB II` / `SGB 2`;
- формулы оплаты: «Mietübernahme / Kostenübernahme / Mietzahlung durch|vom|über das Amt|Jobcenter», «Amt zahlt / übernimmt».

Не считается: `Bürgergeld`, `ALG II`, `Hartz IV`, `Transferleistungen`, `Sozialamt`.

Отрицания (совпадение отбрасывается):
- **перед словом** в той же части предложения: `kein`, `keine`, `nicht`, `nicht an`, `ohne`, `weder`, `nie`, `nein`, `ausschluss`, `ausgeschlossen`, `verboten`, `unerwünscht`;
- **после слова** в той же части: `ausgeschlossen`, `abgelehnt`, `unerwünscht`, `nicht erwünscht`, `nicht möglich`, `nicht geeignet`, `nicht in Frage`, `nein`, `ist kein Thema`, `nicht` и т.д.

Границы частей предложения: `.` `!` `;` скобки и перенос строки — конец предложения; `,` `:` `/` `und` `oder` `sowie` `aber` `jedoch` `sondern` — конец части.
Поэтому «Haustiere verboten, Jobcenter ok» — принимается, а «Kein Jobcenter, aber Haustiere ok» — отбрасывается.

Двойные отрицания и «kein Problem» (= без проблем) нормализуются: «Jobcenter nicht ausgeschlossen» и «Jobcenter kein Problem» — принимаются.

Ограничение: эвристика, не понимание текста. Фраза, которой нет в тестах, может быть проверена неверно. Все решения сохраняются в `seen.db` (`posted` или `rejected:<причина>`).

Тесты: `python -m unittest tests.test_filters`

## Сообщения в Telegram

- Первое сообщение — альбом фото (до 10 штук, максимум `max_photos` = 20, два альбома), подпись до 1024 символов: заголовок, цена, локация, первая часть текста.
- Остальной текст (характеристики, описание, ссылка) уходит отдельными сообщениями по ≤ 3800 символов, длинные строки режутся.
- Если Telegram не смог загрузить фото, альбом не уходит, и объявление отправляется текстом.

## Запуск

```bash
python main.py --dry-run --once   # посмотреть подходящие объявления без отправки и без записи в БД
python main.py --once             # один цикл
python main.py                    # работать постоянно
```

Первый запуск: по умолчанию (`seed_on_first_run: true`) бот запоминает уже висящие объявления и **не постит их**. Публикуются только новые объявления, которые появились после первого запуска.

## Структура

```
main.py              цикл, запуск, флаги
config.json          search_url, интервалы, шаблоны Jobcenter
kb/config.py         загрузка конфига и .env
kb/scraper.py        парсинг поиска и страницы объявления
kb/filters.py        валидация Jobcenter (позитив / отрицание)
kb/telegram.py       сборка сообщений, альбомы, отправка
kb/storage.py        SQLite: какие объявления уже обработаны
tests/               тесты фильтров
```

## Важно

- **Условия использования.** Kleinanzeigen запрещает автоматический сбор данных. Бот делает запросы редко (раз в ~15 минут, пауза 3–6 с между страницами). Используйте на свой риск.
- **Селекторы могут сломаться.** Симптом: `Search returned 0 ads` при том, что на сайте объявления есть. Тогда поправить селекторы в `kb/scraper.py`.
- **Бот работает, пока запущен процесс.** Для постоянной работы нужен сервер или ПК, который не выключается.
