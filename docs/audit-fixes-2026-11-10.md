# ATLAS Campus 3.2.1: исправления двух аудитов

10 ноября 2026. Все 34 исходные находки подтверждены и исправлены: **34 FIXED, 0 NOT FIXED, 0 NOT REPRODUCED**. Дополнительные ошибки проверки и исправлений также устранены. Production и реальные пользовательские данные не изменялись.

Машинный [реестр](audit-fixes-2026-11-10.json), [сводка](verification/audit-fixes-2026-11-10/verification-summary.json), [хеши источников](verification/audit-fixes-2026-11-10/source-files.json). Git-репозитория в каталоге нет; SHA сборки не выдаётся за commit.

## Каждая исходная находка

| ID | Проблема | Исправление | Подтверждение | Статус |
|---|---|---|---|---|
| B01 | Отправка прежнего сеанса под новым аккаунтом | Владелец, эпоха и жизненный цикл проверяются после каждого ожидания; устаревшая подготовка прерывает отправку. | `test_draft_lifecycle_protocol[late-owner]`<br>`test_draft_lifecycle_protocol[logout-queued]` | FIXED |
| B02 | Квадратичный рост квитанций истории | Квитанция хранит неизменный снимок родителя и границу истории вместо повторения сообщений; старые ответы восстанавливаются точно, вся история доступна страницами. | `test_compact_followup_receipts_are_linear_and_replay_historical_page`<br>`test_compact_receipts_preserve_exact_legacy_pages_and_all_history_access` | FIXED |
| B03 | Закрытие формы оставляет pending | Форма блокируется до первого ожидания, pending и управление восстанавливаются в finally, закрытие во время отправки запрещено. | `test_request_locks_before_draft_await_and_cannot_close` | FIXED |
| B04 | Отправка без сохранённой идентичности | Первичное чтение черновика и подтверждённое сохранение ключа обязательны до POST; сбой чтения/PUT прерывает отправку, потерянный ответ не создаёт дубль. | `test_failed_durable_draft_stops_primary_post_and_preserves_input`<br>`test_note_lost_response_reload_reuses_durable_key`<br>`test_failed_initial_read_then_edited_retry_preserves_committed_submission_key` | FIXED |
| B05 | Лимит черновика меньше конспекта | Лимит значения черновика согласован с конспектом: 12000 символов; превышение по-прежнему отклоняется. | `test_full_size_note_draft_and_portfolio_replay`<br>`test_valid_twelve_thousand_character_note_draft_survives_reload` | FIXED |
| B06 | Повтор портфолио создаёт дубль | Создание портфолио резервирует квитанцию и запись в одной транзакции; повтор возвращает тот же результат. | `test_full_size_note_draft_and_portfolio_replay` | FIXED |
| B07 | Конкурентное превышение количества записей | Проверка количества и вставка сериализуются по владельцу; старые записи сверх 200 сохраняются и остаются видимыми. | `test_owner_cap_is_atomic_across_concurrent_creates`<br>`scripts/improvement_deployment.py: personal_cap_races` | FIXED |
| B08 | Флажок задачи перезаписывает поля | Отдельный endpoint toggle изменяет только is_done; клиент не пересылает устаревшие поля задачи. | `test_partial_task_toggle_preserves_edits_and_aged_date`<br>`scripts/extension_browser_check.py: stale client edit + checkbox + persisted fields` | FIXED |
| B09 | Поздний ответ дедлайна меняет новый кеш | Незавершённая запись дедлайна сохраняется вне сменяемого кеша; обновление раздела не разрешает пересекающуюся запись и не принимает старый результат как новый. | `test_deadline_refresh_keeps_write_locked_until_response_settles` | FIXED |
| B10 | Пустая последняя страница после изменения total | Все сервисные загрузчики используют общий пересчёт offset при уменьшении total, включая темы сотрудника и студента. | `test_last_filtered_ticket_reloads_previous_page_after_close` | FIXED |
| B11 | Неверный timezone срока сессии | Aware timestamps переводятся в UTC, naive SQLite считаются UTC; сравнение срока, квот и ISO-ответы используют моменты времени. | `test_b11_expiry_compares_instants_not_wall_clock`<br>`test_b11_datetime_payload_is_canonical_utc`<br>`scripts/improvement_deployment.py: session_timezone` | FIXED |
| B12 | Обход create-квоты записью ID | Маршрут write-квоты сопоставляется после канонизации целого ID; +ID, ведущие нули и пробелы не обходят создание сообщения. | `test_noncanonical_integer_message_path_cannot_bypass_create_quota`<br>`test_canonical_create_quota_and_actor_affinity_before_charging` | FIXED |
| B13 | Неполный исходный ZIP | В обязательный комплект добавлен compose.improvements.yaml и проверка его связей; исходники исключают БД, секреты, кеши и зависимости. | `test_b13_source_zip_preserves_postgres_tls_entrypoint` | FIXED |
| B14 | Общий путь параллельных backup | Уникальные временные пути и имена копий, блокировка конкурирующего писателя и атомарная публикация исключают перезапись и ложную проверку. | `test_b14_backup_file_protocol_without_a_database`<br>`scripts/improvement_deployment.py: backup_restore` | FIXED |
| B15 | Переполнение минимальной даты | Минимальная и максимальная даты фильтра преобразуются без переполнения календаря. | `test_staff_replay_survives_start_time_and_boundary_dates` | FIXED |
| B16 | Временная валидация до replay | Проверка актуальности даты выполняется после поиска подтверждённого повтора; новый просроченный запрос всё ещё запрещён. | `test_b16_retake_replay_survives_moscow_midnight`<br>`test_staff_replay_survives_start_time_and_boundary_dates` | FIXED |
| B17 | Старение задачи запрещает изменение | Изменение существующей задачи с прежней датой разрешено после её старения; новая дата валидируется, отметка имеет отдельный endpoint. | `test_partial_task_toggle_preserves_edits_and_aged_date` | FIXED |
| B18 | Строковая сортировка времени календаря | Календарь сортируется по каноническому времени, подпись для человека в сортировке не участвует. | `test_calendar_orders_lesson_and_localized_consultation_by_canonical_time` | FIXED |
| B19 | UTC-дата создания в списке | Дата создания в списке и карточке вычисляется в Europe/Moscow из одного timestamp. | `test_request_list_uses_moscow_creation_day_and_rejected_contrast` | FIXED |
| B20 | Сводка активных пропускает needs_info | Сводка активных заявок учитывает needs_info вместе с submitted/review/processing. | `test_staff_summary_counts_needs_info_and_all_consultation_pages` | FIXED |
| B21 | Размер страницы вместо total слотов | Сводка консультаций использует серверный total вместо длины текущей страницы. | `test_staff_summary_counts_needs_info_and_all_consultation_pages` | FIXED |
| B22 | UTC-дата срока старой заявки | Аддитивная 0006 корректирует только сроки, совпадающие с прежним вычислением по UTC, на расчёт по московской дате. | `test_0006_upgrade_preserves_records_unbound_drafts_and_compacts_legacy_receipts` | FIXED |
| B23 | Readiness обходит обработку соединения | Создание соединения и SELECT readiness находятся внутри обработки отказа; недоступная БД даёт 503, health остаётся доступным. | `test_b23_ready_catches_connection_creation_failure`<br>`scripts/improvement_deployment.py: database outage and recovery` | FIXED |
| B24 | Конкурентный максимум сессий PostgreSQL | Удаление лишних сессий и новый вход сериализуются по строке пользователя PostgreSQL независимо от IP. | `scripts/improvement_deployment.py: session_cap_race` | FIXED |
| B25 | Уточнение после терминального решения | Ожидаемая версия должна совпасть с прочитанной; SQL дополнительно проверяет владельца, версию и нетерминальный текущий статус. | `test_predicted_followup_version_cannot_bypass_terminal_state` | FIXED |
| B26 | Поздний restore меняет ключ отправки | Restore завершается до захвата отправки; сохранённая идентичность отделена от применения полей, ключ остаётся неизменным во время await. | `test_draft_lifecycle_protocol[restore-before-submit]`<br>`test_draft_lifecycle_protocol[edited-before-restore]`<br>`test_failed_initial_read_then_edited_retry_preserves_committed_submission_key` | FIXED |
| B27 | SQLite ID reuse и чужая запись/черновик | Пять семейств личных записей получили постоянный record_token; SQL проверяет ID/владельца/токен, формы и черновики связаны с токеном. Старые черновики сохранены без опасной перепривязки. | `test_sqlite_aba_inflight_mutation_cannot_cross_owners`<br>`test_same_owner_reuse_rejects_old_token_and_draft_identity`<br>`test_0006_upgrade_preserves_records_unbound_drafts_and_compacts_legacy_receipts` | FIXED |
| B28 | Очистка удаляет следующий черновик | DELETE черновика идёт в общей очереди с PUT и проверяет ревизию; таймер отменяется, блокировка отправки держится до очистки. | `test_draft_lifecycle_protocol[delete-serialized]`<br>`test_request_locks_before_draft_await_and_cannot_close` | FIXED |
| B29 | Аккаунт другой вкладки не согласован | Клиент отправляет захваченный X-ATLAS-User, сервер отклоняет несовпадение до записи/квоты; межвкладочная проверка и скачивания используют ту же защиту. | `test_b29_actor_header_blocks_cross_account_reads_writes_and_logout`<br>`test_cross_tab_cookie_change_cannot_save_old_account_form`<br>`test_downloads_are_affinity_guarded_and_legacy_drafts_are_discoverable` | FIXED |
| P01 | Память параллельных Argon2 | Общий для PostgreSQL-процессов допуск ограничивает Argon2 двумя проверками; перегрузка возвращает 429/Retry-After, блокировки освобождаются транзакцией. | `test_p01_pg_admission_has_bounded_shared_slots_and_overload_retry`<br>`test_p01_local_admission_releases_after_verifier_exception`<br>`p01-before.json / p01-after.json: real two-worker measurement` | FIXED |
| P02 | Контраст rejected | Текст отклонённой заявки затемнён; вычисленный браузером контраст не меньше 4.5:1. | `test_request_list_uses_moscow_creation_day_and_rejected_contrast` | FIXED |
| P03 | Зависимости текущего PDF | pypdf, ReportLab и Pillow объявлены отдельно с маршрутом установки; генератор проверен изолированно, все страницы отрендерены. | `test_p03_current_report_dependencies_are_declared_and_importable`<br>`pdf-generator-check.json` | FIXED |
| P04 | REVIEW завершается exit 0 | REVIEW, неполный или подменённый инвентарь, ошибка сканера/установки завершаются ненулевым кодом; импорт не запускает аудит. | `test_p04_audit_exit_matches_actual_scanner_result`<br>`test_p04_import_has_no_scan_or_report_side_effects` | FIXED |
| P05 | 20 относительных ссылок исторического отчёта | Исправлены уровни всех 20 относительных ссылок перенесённого исторического документа; проверяется существование целей. | `test_p05_historical_document_links_resolve` | FIXED |

Имена pytest проверены по фактически выполненному JUnit. Тесты: [core](../tests/test_audit_core.py), [backend](../tests/test_audit_backend_integrity.py), [браузер](../tests/test_audit_frontend_browser.py), [очереди/календарь](../tests/test_audit_frontend_callbacks.py), [упаковка и инструменты](../tests/test_audit_ops.py).

## Результаты проверок

| Проверка | Фактический результат | Доказательство |
|---|---|---|
| Полный pytest с opt-in Chromium | **270 passed, 0 failed, 0 skipped**, 194.16 s; два прежних deprecation warning Starlette/AnyIO | [JUnit](verification/audit-fixes-2026-11-10/pytest-results.xml) |
| Синтаксис | Все 3 JS; AST 65 Python-файлов | [Сводка](verification/audit-fixes-2026-11-10/verification-summary.json) |
| Ядро Chromium: студент → офис → студент | 13 сценариев, 40 геометрических проверок, 45 снимков; нет JS/CSP ошибок | [Ядро](verification/audit-fixes-2026-11-10/core-browser.json) |
| Учебный UI и все страницы Chromium | 136 проверок, 132 геометрических состояния, 133 axe-состояния, 0 нарушающих узлов; 131 снимок | [Расширение](verification/audit-fixes-2026-11-10/extension-browser.json) |
| Firefox 142.0.1 / WebKit 26.0 | 192 состояния на 360/390/1440 px; реальная подача → решение → собственный документ | [Браузеры](verification/audit-fixes-2026-11-10/crossbrowser.json) |
| PostgreSQL 17.11 / два web-процесса / HTTPS | 17 проверок; текущие app/static совпадают с образом, изменения источников во время прогона отсутствуют | [PG/TLS](verification/audit-fixes-2026-11-10/postgres-https.json) |
| Гонки и отказы PG | Сессий максимум 20 с разных IP; четыре гонки 199+2→200; прежняя 201-я запись видна; TimeZone±3; отказ БД с 503 и восстановление | [PG/TLS](verification/audit-fixes-2026-11-10/postgres-https.json) |
| Перезапуск и настоящее резервное восстановление | Числа и хеши строк всех 38 таблиц совпали после restart и pg_dump/pg_restore в новую БД | [PG/TLS](verification/audit-fixes-2026-11-10/postgres-https.json) |
| Старая PG0005 →0006 | Сохранены прежние столбцы 37 таблиц, пять старых черновиков и точный ответ квитанции; повтор миграции ничего не изменил | [PG/TLS](verification/audit-fixes-2026-11-10/postgres-https.json) |
| Копия рабочей SQLite | Две миграции; все прежние значения 385 записей 38 таблиц неизменны; исходная atlas.db не изменена | [Копия БД](verification/audit-fixes-2026-11-10/workspace-copy-migration.json) |
| Рост SQL | SELECT 4→4 для курсов, заданий и тем при увеличении данных | [SQL](verification/audit-fixes-2026-11-10/sql-growth.json) |
| Ограниченная нагрузка | 8 клиентов, 800 чтений +40 созданий/+40 повторов;0 неожиданных ответов; p95=78.81 ms | [Нагрузка](verification/audit-fixes-2026-11-10/load.json) |
| Лабораторная скорость | По 3 прогона desktop/mobile; mobile LCP p75=1316 ms, CLS p75=.06; заявленные бюджеты выполнены | [Скорость](verification/audit-fixes-2026-11-10/performance.json) |
| Linux runtime advisory | Фактические 22 пакета, PyPI и OSV: 0 advisory, 0 skipped | [Runtime](verification/audit-fixes-2026-11-10/linux-runtime/runtime-audit.json) |
| Windows runtime/test/report advisory | Фактические 38 пакетов, PyPI и OSV: 0 advisory, 0 skipped; npm audit: 0 | [Dev](verification/audit-fixes-2026-11-10/development-security-audit.json) |
| PDF | Изолированные 15 исторических входов;9 страниц процесса+1 A4, все отрендерены и осмотрены; исторические PDF не перезаписаны | [PDF](verification/audit-fixes-2026-11-10/pdf-generator-check.json) |
| Протокол файлов backup | Реальное выполнение shell с fakeDocker: прежняя ошибка воспроизведена, проверены 3 копии, отказ/конкуренция/хеши; отдельно выполнен настоящий pg_restore выше | [Backup](verification/audit-fixes-2026-11-10/backup-file-protocol.json) |
| Точный исходный ZIP | Проверяется после упаковки в новом venv с установкой, API / IDOR и перезапуском; внешний акт хранится рядом с ZIP и не входит в собственный хеш | Внешний `archive-acceptance.json` |

## Дополнительные исправления и честность проверок

- **N01 FIXED:** свежий scan выявил три затронутых пакета в локальных инструментах: pytest 9.0.2, Pillow 11.3.0 и pip 26.0.1. Установлены pytest 9.0.3 / Pillow 13.0.0 / pip 26.2.2; bootstrap новых окружений закреплён. Повторные PyPI/OSV полные и чистые. Количество записей advisory до обновления включает aliases и не выдаётся за число независимых уязвимостей.
- **N02 FIXED:** первая полная suite обнаружила потерю фокуса после 422. Порядок разблокировки исправлен; прежний тест не ослаблен, добавлены два реальных сценария для заявки/уточнения.
- **N03 FIXED:** слишком большой ID токенизированного черновика теперь отклоняется 422 до SQL вместо 500. Есть граничные регрессии.
- Приёмочный сценарий checkbox обновлён под новый toggle endpoint и усилен: реальное изменение другой вкладки остаётся после отметки, тело содержит только is_done. Прежний таймаут ожидания старого endpoint сохранён в промежуточном отчёте.
- Исходные неуспешные отчёты сохранены с именами first-pass/interim/old-toggle-contract. Они не засчитаны как PASS; итоговая сводка ссылается только на завершённые успешные прогоны.

## Ограничение Argon2: что именно измерено

На изолированном сохранённом исходном стенде при ограниченных всплесках 8/12/16 клиентов наблюдалось 13 одновременныхKDF; пик памяти 536899584 байт, cgroup max=465, OOM=0. С изменённым блоком допуска — максимум 2 KDF, пик 411201536 байт, max=0 / OOM=0, ожидаемые 429 и последующий успешный вход. Это измерение давления на память, не воспроизведённый OOM. Инструментирование отмечало границы настоящих вызовов без искусственной задержки. Теоретические 570 MiB относятся к пулу без допуска, а не к новому ограничению. [До](verification/audit-fixes-2026-11-10/p01-before.json), [после](verification/audit-fixes-2026-11-10/p01-after.json). Финальный текущий образ проверен отдельно в PG/TLS.

## Данные, совместимость и развёртывание

Рабочая SQLite не мигрировалась и не очищалась. Её SHA256: `91ad8fae65489acd94ec9dc71ac38d90b72a51c549bec97dc35a287600913683`. Миграция 0006 проверена на её копии и на реальном PostgreSQL 0005. Она добавляет record_token в пять семейств личных записей и индексы, исправляет вычисленный по UTC срок только при точном совпадении старого расчёта, уплотняет лишь точно восстанавливаемые избыточные квитанции. Непроверяемые старые снимки остаются целиком. Существующие номера, даты, тексты, владельцы, статусы и история сохраняются.

Перед обновлением сделайте штатную резервную копию. Для Docker: собрать новый образ, остановить web на время обновления, выполнить `docker compose run --rm web python -m app.db migrate`, затем `docker compose up -d web caddy`; **не удалять том/БД**. При обычном локальном запуске миграция выполняется в startup. Подробности: [миграции](../migrations/README.md), [эксплуатация](operations.md). После обновления перезагрузите открытые вкладки: shell revalidate и assets 3.2.1 загружают текущую защиту сеанса.

X-ATLAS-User и X-ATLAS-Record — дополнительные проверки контекста, не выбор владельца и не источник прав. Старые клиенты без заголовков поддерживаются; сервер всё равно назначает владельца по cookie и проверяет его в SQL. Новые формы передают токены и привязывают к ним черновики. Старые `тип:номер` намеренно не привязываются к потенциально заменённой записи: владелец может скачать их через «Настройки → Мои черновики» и перенести нужный текст вручную. История доступна страницами; устаревшие квитанции повторяются точно.

Временные контейнеры и 11 томов пяти собственных тестовых проектов удалены после проверки точных labels; чужие проекты не изменялись. [Очистка](verification/audit-fixes-2026-11-10/docker-test-cleanup.json). Проверенный runtime image оставлен как артефакт сборки.

## Границы результата

Результат относится к локальным исходникам, временным вымышленным данным и указанным стендам. Публичный production, ACME/DNS, подключение из России, физические Android/iPhone, ручной скринридер, реальные интервью, будущий uptime и удалённый запуск GitHub Actions не проверялись и не объявляются выполненными. Viewport и WebKit не заменяют физическое устройство. Лабораторные числа не являются полевым INP или обещанием ёмкости production. Проверка advisory проверяет известные Python/npm advisories, не все пакеты ОС и неизвестные уязвимости.

Публичное предупреждение о конкурсном концепте и вымышленных данных сохранено во всех сценариях. [Процесс](process.md), [снимки](../screenshots/README.md), [приёмка](release-checklist.md).
