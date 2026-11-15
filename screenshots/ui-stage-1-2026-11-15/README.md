# Этап 1 · 15 ноября 2026 года

Снимки сделаны в Chromium на запущенном локальном приложении с отдельной тестовой базой. Базовая ревизия `ed99703c985b44e8cef1c0cbb39279cc2cc7992e` сравнивалась с итоговой версией на тех же демонстрационных данных.

| Экран и условия | До | После |
|---|---|---|
| Главная, 1440 px, тёмная тема, обычный вид | [До](before-home-1440-dark-standard.png) | [После](after-home-1440-dark-standard.png) |
| Поиск в личных сообщениях, 1440 px, тёмная тема, обычный вид | [До](before-direct-1440-dark-standard.png) | [После](after-direct-1440-dark-standard.png) |
| Профиль Даниила Зорина, 1440 px, тёмная тема, обычный вид | [До](before-teacher-1440-dark-standard.png) | [После](after-teacher-1440-dark-standard.png) |
| Заголовок и автор материала, 1440 px, тёмная тема, обычный вид | [До](before-material-1440-dark-standard.png) | [После](after-material-1440-dark-standard.png) |
| Фильтры материалов, 1440 px, тёмная тема, компактный вид | [До](before-filters-1440-dark-compact.png) | [После](after-filters-1440-dark-compact.png) |
| Фильтры материалов, 390 px, светлая тема, компактный вид | [До](before-filters-390-light-compact.png) | [После](after-filters-390-light-compact.png) |
| «Сдать работу», 1440 px, тёмная тема, обычный вид | [До](before-modal-1440-dark-standard.png) | [После](after-modal-1440-dark-standard.png) |

На ширине 1440 px в компактном виде разница между нижними краями кнопки «Найти» и полей уменьшилась с 10 px до 0 px. При масштабе 200% Chromium уменьшил доступную ширину с 1422 до 711 CSS px, и действия перешли на следующую строку. [Снимок при 200%](after-filters-zoom200-dark-compact.png).

Клавиатурный фокус в общем поиске выделен рамкой на обеих темах. [Снимок тёмной темы](after-search-focus.png).
