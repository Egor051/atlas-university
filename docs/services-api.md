# Контракты сервисов кампуса 3.2.1 · 10 ноября 2026

Только вымышленные данные конкурсного концепта. Не подключены настоящий университет, библиотечная система, банковские операции, отправка e-mail или push. Общие правила сессии, CSRF, защиты источника, максимального размера тела и безопасных ошибок наследуются от основного API.

Все студенческие пути ниже доступны только роли `student`; роль `staff` получает 403. Без сессии — 401. Владелец берётся исключительно из сессии. Подмена `student_id` в query не меняет выборку, в JSON — 422. Чужая или отсутствующая личная запись — 404. Все перечисленные POST требуют `X-Requested-With: ATLAS`, допустимый Origin и JSON; для действий без полей передаётся `{}`. Лишние поля запрещены.

## Каталоги и личные сервисы

| Метод / путь | Вход и результат |
|---|---|
| GET `/api/services/contacts?q=` | `{items,concept:true}`; каждый контакт: `id,name,role,department,subject,room,hours,email`. Адреса `.example` вымышленные |
| GET `/api/services/knowledge?q=` | `{items,concept:true}`; `id,category,title,body` |
| GET `/api/services/consultations` | `{items}`; слоты: `id,teacher,subject,start_at,end_at,room,capacity,booked_count,my_booking_id` |
| GET `/api/services/bookings` | `{items}` только своих записей: `id,slot_id,status,created_at,slot` |
| POST `/api/services/consultations/{id}/book` | `{}` → 201, личная запись. Начавшийся слот, отсутствие мест или повторная активная запись → 409 |
| POST `/api/services/bookings/{id}/cancel` | `{}` → отменённая запись; повторная отмена → 409 |
| GET `/api/services/tickets` | `{items}` только своих тем: `id,topic,title,status,created_at,updated_at` |
| POST `/api/services/tickets` | `{topic,title,message}` → 201, тема с перепиской. `topic`: academic/technical/financial/other; title после trim 5–180, message 10–4000 символов |
| GET `/api/services/tickets/{id}` | Своя тема + `messages:[{id,body,actor_role,actor_name,created_at}]` |
| POST `/api/services/tickets/{id}/messages` | `{message}` от 1 до 4000 символов; ответ добавляется в открытую тему |
| POST `/api/services/tickets/{id}/close` | `{}` закрывает открытую тему. Закрытую тему нельзя дополнить или закрыть повторно: 409 |
| GET `/api/services/events` | `{items}`; `id,title,category,description,start_at,end_at,location,capacity,registered_count,my_registration_id` |
| GET `/api/services/registrations` | `{items}` только своих регистраций: `id,event_id,status,created_at,event` |
| POST `/api/services/events/{id}/register` | `{}` → 201, регистрация; начавшееся событие, нет мест или активный дубль → 409 |
| POST `/api/services/registrations/{id}/cancel` | `{}` → отменённая регистрация; повтор → 409 |
| GET `/api/services/library?q=` | `{items}`; `id,title,author,subject,description,total,available,my_loan_id` |
| GET `/api/services/loans` | `{items}` только своих выдач: `id,book_id,status,borrowed_at,due_date,returned_at,book` |
| POST `/api/services/library/{id}/borrow` | `{}` → 201, личная выдача на 14 календарных дней. Нет экземпляра или книга уже выдана этому студенту → 409 |
| POST `/api/services/loans/{id}/return` | `{}` → возвращённая книга; повтор → 409 |
| GET `/api/services/finance` | `{items,summary,notice}`; только свой вымышленный журнал. Записи: `id,date,description,direction,amount_kopecks`, direction credit/debit. Суммы — целые копейки |
| GET `/api/services/preferences` | Собственные настройки; при отсутствии строки возвращает значения по умолчанию без записи в БД |
| POST `/api/services/preferences` | `{email_notifications,deadline_reminders,compact_mode,weekly_goal}`; три строгих bool и строгий int 1–40. Сохраняет только свои настройки |

Финансовая `summary`: `credits_kopecks,debits_kopecks,balance_kopecks,concept:true`. Баланс — разность вымышленных записей; настоящая задолженность, право на стипендию и проведение платежа не определяются.

Список контактов и справка поддерживают поиск без учёта регистра; библиотека — по названию, автору и предмету. Поиск до 100 символов; управляющие символы отвергаются. Каталоги и персональные списки поддерживают `limit` 1–300 (default 300), `offset` 0–2147483647 и возвращают `total,limit,offset,has_more` вместе с `items`. Поиск/фильтр применяется до LIMIT. Каталоги консультаций/событий принимают `scope=upcoming|archive|all`, точный `record_id` сохраняет ограничения владельца. Счётчики мест и финансовые итоги считаются по всем записям. У темы максимум 500 сообщений: дальнейшее добавление возвращает 409 с предложением создать новую тему. В библиотеке нет скачивания выдуманных полных текстов книг.

Детали студенческой и служебной темы принимают `message_limit` 1–100 (default 100), необязательный `message_offset` и возвращают `messages_total,messages_limit,messages_offset,messages_has_more`. Без offset показываются последние 100 сообщений, по времени и ID; явный offset 0 открывает начало. Вся переписка сохраняется и доступна страницами. Фильтры записей на консультации/мероприятия принимают `date_from/date_to` по московскому дню; обратный диапазон, `date_from=0001-01-01` и `date_to=9999-12-31` дают безопасный 422 вместо переполнения UTC-даты.

## Работа сотрудника

| Метод / путь | Контракт |
|---|---|
| GET `/api/staff/overview` | `requests:{status:count},requests_total,open_tickets,consultations,events,concept:true`. Только операционные итоги, без оценок, личных конспектов и финансов студентов |
| GET `/api/staff/consultations` | `{items}` общих слотов без чужих личных ID бронирований |
| POST `/api/staff/consultations` | `{teacher,subject,start_at,end_at,room,capacity}` → 201. Capacity строгий int 1–100; начало в будущем до 365 дней; продолжительность 10 минут – 8 часов |
| GET `/api/staff/events` | `{items}` общих мероприятий |
| POST `/api/staff/events` | `{title,category,description,start_at,end_at,location,capacity}` → 201. Capacity строгий int 1–1000; начало до 365 дней; продолжительность 10 минут – 7 дней. Category science/career/sport/community/academic |
| GET `/api/staff/tickets?filter=all&q=` | `{items}` темы с `student_name,group`. Filter all/open/closed, поиск в заголовках |
| GET `/api/staff/tickets/{id}` | Тема + сообщения + имя/группа заявителя |
| POST `/api/staff/tickets/{id}/messages` | `{message}` → сохранённая переписка; ответ и уведомление студента записываются одной транзакцией |
| POST `/api/staff/tickets/{id}/close` | `{}` → закрытая тема и уведомление владельцу, одна транзакция |
| POST `/api/staff/announcements` | `{title,body,category}` → 201 `{sent,concept:true}`. Title 5–180, body 10–4000; category announcement/deadline. По одному внутреннему уведомлению каждому вымышленному студенту, без email |

Для создания слотов/событий обязательны ISO timestamps с часовым поясом. Перед сохранением они преобразуются в UTC, поэтому SQLite и PostgreSQL возвращают один и тот же момент времени. Клиент отображает МСК. В строках текстовых форм обрезаются пробелы, запрещены недопустимые управляющие символы. Даты, неизвестные категории, нестрогие bool/int и лишние поля дают 422.

Необязательный `Idempotency-Key` сохраняет actor + operation + fingerprint и первоначальный ответ одной транзакцией с изменением ресурса. Повтор завершённого создания слота/события проверяется до ограничения будущей даты и остаётся успешным после начала события; новый ключ проходит обычную валидацию. Квитанции переписки хранят компактную границу истории вместо повторения 100 текстов в каждом снимке, возвращая при повторе ту же историческую страницу. Преобразование старых квитанций допускается только при полном совпадении исходных сообщений; невосстановимые снимки сохраняются целиком.

## Сохранение и конкурентные действия

Новые таблицы аддитивны. `seed_services(db)` вызывается под существующей startup-блокировкой, добавляет демонстрационные каталоги по уникальному seed_key и личные финансовые данные/настройки только двум публичным демоаккаунтам. Повторный запуск не сбрасывает занятые места, выданные книги, переписку и настройки. GET ничего не создаёт и не подтверждает автоматически.

Бронирование, регистрация и выдача выполняют условный SQL UPDATE ресурса, одновременно проверяющий остаток и блокирующий строку. Проверка собственного активного дубля выполняется после захвата этой блокировки; конфликт откатывает изменение счётчика. Конкурентные студенты не могут занять последнее место дважды. Отмена/возврат используют compare-and-swap статуса active; повтор не освобождает место или экземпляр второй раз. Списки ресурсов показывают общие обезличенные счётчики и только ID собственных активных записей.

Переписка сериализует закрытие/ответ условным UPDATE статуса open. Закрытие терминально. Студент закрывает только свою тему, сотрудник — тему из своего административного контура. Права на чужие оценки, расписание, финансы и личные учебные записи у сотрудника не появляются.

Проверки функциональности, IDOR, ролей, CSRF, повторной отмены/возврата, конкуренции за последнее место/книгу, строгих значений, временных зон и сохранения после startup находятся в `tests/test_services.py`. Фактический итог общего запуска отражается в актуальном приёмочном листе, а не предполагается этим документом.
