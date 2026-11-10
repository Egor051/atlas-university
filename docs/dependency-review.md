# Проверка Python-зависимостей

Дата проверки: **6 ноября 2026**. Итог для зафиксированного Linux runtime: **известных уязвимостей 0 по PyPI и 0 по OSV**, пропущенных пакетов и проигнорированных advisory ID нет. Это результат проверки известных записей на указанную дату, а не обещание отсутствия любых будущих уязвимостей.

## Что проверялось

PyPA **pip-audit 2.10.1** установлен в отдельное временное виртуальное окружение. Сканер не добавлялся в зависимости приложения, его `.venv` или Docker-образ. Проверялся инвентарь реально собранного контейнера: **21 пакет приложения и транзитивных зависимостей**, дополнительно — присутствующий в образе `pip 26.2.2`. Пакеты сканера, pytest, Playwright, PDF-инструменты и axe-core не выдаются за production-зависимости.

Полный вход сканера сохранён в [`verification/dependency-input.txt`](verification/dependency-input.txt), результаты, версии и хеши — в [`verification/dependency-report.json`](verification/dependency-report.json). Оба сервиса запрошены без `--ignore-vuln`. `--no-deps --disable-pip` применяется к уже полному списку установленных пакетов, поэтому транзитивные зависимости включены явно, без повторной установки в окружение сканера. Назначение инструмента и источники базы описаны в [официальном репозитории PyPA](https://github.com/pypa/pip-audit).

## Что найдено и исправлено

Первый прогон исходного контейнера с `Starlette 0.50.0` вернул **10 записей, соответствующих 5 уникальным advisory ID**; одинаковые IDs из разных записей не считаются отдельными уязвимостями.

| Уникальная находка | Класс upstream-проблемы | Версия исправления |
|---|---|---|
| [PYSEC-2026-161 / CVE-2026-48710](https://github.com/Kludex/starlette/security/advisories/GHSA-86qp-5c8j-p5mr) | Host влияет на восстановленный путь URL | 1.0.1 |
| [PYSEC-2026-2280 / CVE-2026-48817](https://github.com/Kludex/starlette/security/advisories/GHSA-x746-7m8f-x49c) | Нестандартный HTTP-метод вызывает атрибут HTTPEndpoint | 1.1.0 |
| [PYSEC-2026-2281 / CVE-2026-48818](https://github.com/Kludex/starlette/security/advisories/GHSA-wqp7-x3pw-xc5r) | UNC/SMB при StaticFiles на Windows | 1.1.0 |
| [PYSEC-2026-248 / CVE-2026-54282](https://github.com/Kludex/starlette/security/advisories/GHSA-jp82-jpqv-5vv3) | Некорректный путь меняет hostname восстановленного URL | 1.3.0 |
| [PYSEC-2026-249 / CVE-2026-54283](https://github.com/Kludex/starlette/security/advisories/GHSA-82w8-qh3p-5jfq) | Ограничения urlencoded-форм не применяются, возможен DoS | 1.3.1 |

Это подтверждённые advisory для версии зависимости, а не пять доказанных эксплойтов ATLAS. Приложение не использует `StaticFiles`, `HTTPEndpoint` или `request.form()`; при этом объекты URL участвуют в его защитных проверках. Исключения для находок не принимались — обновлена сама зависимость.

Сделан узкий patch: **FastAPI 0.128.2 → 0.133.0**, **Starlette 0.50.0 → 1.3.1**. Старый FastAPI запрещал Starlette 1.x; [релиз FastAPI 0.133.0](https://fastapi.tiangolo.com/release-notes/#01330) добавляет её поддержку. Starlette 1.3.1 закрывает последний из указанных advisory; исправления отражены в [официальных release notes](https://starlette.dev/release-notes/#131-june-12-2026). Прочие исходные прямые pins сохранены; backend-код и проверки прав не менялись, тестовые утверждения не ослаблялись.

При новой чистой сборке разрешился `click 8.5.1` вместо `8.5.0`. Эта фактически полученная версия тоже проверена. Чтобы следующий build не менял транзитивные версии самопроизвольно, **21 runtime pin зафиксирован в `requirements-runtime.lock`**. Docker устанавливает `-r requirements.txt -c requirements-runtime.lock`; после повторной сборки `pip freeze` совпал с lock полностью, `pip check` прошёл. Lock не содержит сканера и тестовых инструментов. Windows-запуск использует `requirements.txt` без Linux constraints; платформенные зависимости и окружение разработки не выдаются за идентичный Linux runtime.

## Повторная проверка

Финальный контейнер повторно проверен обоими сервисами: **exit code 0, advisory 0, skipped 0**. HTTPS-сценарий с двумя студентами и сотрудником, сохранение после перезапуска и восстановление PostgreSQL проверены на новом образе; доказательства — [`verification/deployment-report.json`](verification/deployment-report.json). API, браузерные сценарии и доступность имеют отдельные актуальные отчёты в `verification/`.

Для повторения установите `pip-audit==2.10.1` в отдельное временное окружение и выполните:

```sh
python -m pip_audit -r docs/verification/dependency-input.txt --no-deps --disable-pip -s pypi -f json
python -m pip_audit -r docs/verification/dependency-input.txt --no-deps --disable-pip -s osv -f json
```

При изменении образа сначала получите новый инвентарь из реально собранного контейнера. CI делает это отдельно от окружения сканера и блокирует push/PR-проверку при известных advisory; удалённый запуск CI в этой локальной итерации не утверждается. Проверка охватывает Python-пакеты, не системные пакеты ОС, неизвестные уязвимости или аудит всей цепочки поставки; lock закрепляет версии, но не содержит хеши wheel-файлов. Перед публичным размещением скан следует повторить по актуальным базам.
