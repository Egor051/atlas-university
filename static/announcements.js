/* Campus feed, publication details, and study-office editing. */
(() => {
  'use strict';
  const categories = {announcement: 'Общие', deadline: 'Сроки', academic: 'Учёба', campus: 'Жизнь кампуса'};
  const priorities = {normal: 'Обычные', important: 'Важные', critical: 'Срочные'};
  const priorityLabels = {normal: 'Обычное', important: 'Важное', critical: 'Срочное'};
  const statuses = {draft: 'Черновик', published: 'Опубликовано', archived: 'В архиве'};
  const audiences = {all: 'Весь кампус', students: 'Все студенты', employees: 'Сотрудники', group: 'Учебная группа'};
  const actionLabels = {created: 'Создан черновик', edited: 'Изменено', published: 'Опубликовано',
    archived: 'Перенесено в архив', withdrawn: 'Снято с публикации'};
  const sorts = {featured: 'Закреплённые вверху', newest: 'Сначала новые', oldest: 'Сначала ранние'};
  const pages = [
    {id: 'announcements', label: 'Объявления', icon: 'megaphone', hint: 'Публикации учебного офиса',
      roles: ['student', 'staff', 'teacher', 'scheduler', 'admin', 'union', 'vuc']},
    {id: 'announcement-admin', label: 'Управление объявлениями', icon: 'megaphone', hint: 'Черновики и публикации учебного офиса', roles: ['staff']},
  ];
  let c;
  let timelinePriority = '';
  const has = page => pages.some(item => item.id === page);
  const isOffice = page => page === 'announcement-admin';
  const esc = value => c.esc(value);
  const isId = value => /^[1-9]\d{0,9}$/.test(value) && Number(value) <= 2147483647;
  const validParts = (_page, parts) => parts.length === 1 && isId(parts[0]);
  const path = page => isOffice(page) ? 'staff/announcements' : 'announcements';
  const pageUrl = (page, {id, query = {}} = {}) => {
    const params = new URLSearchParams(query).toString();
    return `/app/${page}${id ? '/' + Number(id) : ''}${params ? '?' + params : ''}`;
  };
  const link = (url, text, className = 'mini-link') => `<a class="${className}" data-app-link href="${esc(url)}">${esc(text)}</a>`;
  const shortDate = value => value ? c.stamp(value) + ' МСК' : '';
  const publicationDate = new Intl.DateTimeFormat('ru-RU', {dateStyle: 'long', timeStyle: 'short', timeZone: 'Europe/Moscow'});
  const date = (value, full = false) => value ? `<time datetime="${esc(value)}">${esc(full ? publicationDate.format(new Date(value)) + ' МСК' : shortDate(value))}</time>` : '';

  function cleanQuery(page, query, parts) {
    const result = {};
    if (parts.length) {
      if (isOffice(page) && isId(query.history_offset)) result.history_offset = query.history_offset;
      return result;
    }
    if (Object.hasOwn(categories, query.category)) result.category = query.category;
    if (Object.hasOwn(priorities, query.priority)) result.priority = query.priority;
    if (Object.hasOwn(statuses, query.status) && (isOffice(page) || query.status !== 'draft')) result.status = query.status;
    if (Object.hasOwn(sorts, query.sort)) result.sort = query.sort;
    if (query.q?.trim()) result.q = query.q.trim().slice(0, 100);
    if (isId(query.offset)) result.offset = query.offset;
    return result;
  }

  function load(page, parts, query) {
    return c.api(path(page) + (parts.length ? '/' + Number(parts[0]) : '') + '?' + new URLSearchParams(query));
  }

  async function homeFeed() {
    try {
      return await c.api('announcements?limit=10&sort=newest');
    } catch (error) {
      if (error.stale) throw error;
      return {error: true};
    }
  }

  const options = (choices, selected) => Object.entries(choices).map(([value, text]) =>
    `<option value="${esc(value)}"${String(selected ?? '') === value ? ' selected' : ''}>${esc(text)}</option>`).join('');
  const filter = (name, label, choices, selected) =>
    `<label class="announcement-field"><span>${esc(label)}</span><select name="${name}">${options(choices, selected)}</select></label>`;
  const priority = row => `<span class="announcement-priority" data-priority="${esc(row.priority)}">${esc(priorityLabels[row.priority])}</span>`;
  const metadata = (row, full = false) => `<p class="announcement-meta">${priority(row)}<span>${esc(categories[row.category])}</span>${date(row.published_at || row.created_at, full)}${row.pinned ? '<span>Закреплено</span>' : ''}</p>`;

  function timelineItems(data) {
    if (data.error) return '<p class="compact-empty" role="status">Объявления не загрузились. <button type="button" class="mini-link" data-announcement-action="retry">Повторить</button></p>';
    const rows = data.items.filter(row => !timelinePriority || row.priority === timelinePriority);
    if (!rows.length) return `<p class="compact-empty">${timelinePriority ? 'В последних публикациях таких объявлений нет.' : 'Опубликованных объявлений пока нет.'}</p>`;
    return `<ol class="announcement-track">${rows.map(row => `
      <li data-priority="${esc(row.priority)}">
        <span class="announcement-marker" aria-hidden="true"></span>
        <article class="announcement-event">
          ${metadata(row)}
          <h3>${link(pageUrl('announcements', {id: row.id}), row.title, 'announcement-title-link')}</h3>
          <details class="announcement-expansion">
            <summary>
              <span class="announcement-expand-label">Прочитать анонс</span>
              <span class="announcement-collapse-label">Свернуть анонс</span>
              <span class="sr-only"> — ${esc(row.title)}</span>
            </summary>
            <p class="announcement-excerpt">${esc(row.excerpt)}</p>
          </details>
        </article>
      </li>`).join('')}</ol>`;
  }

  function timeline(data) {
    if (!data) return '';
    const choices = [['', 'Все'], ...Object.entries(priorities)];
    return `<section class="card card-pad announcement-timeline" aria-labelledby="announcement-timeline-title">
      <header class="card-titlebar"><h2 class="card-title" id="announcement-timeline-title">Объявления</h2>${link(pageUrl('announcements'), 'Все объявления')}</header>
      ${data.items?.length ? `<div class="announcement-legend" role="group" aria-label="Приоритет последних объявлений">${choices.map(([value, label]) => `<button type="button" class="outline-button" data-announcement-priority="${value}" aria-pressed="${timelinePriority === value}">${value ? `<span class="announcement-legend-dot" data-priority="${value}" aria-hidden="true"></span>` : ''}${label}</button>`).join('')}</div>` : ''}
      <div id="announcement-timeline-items" role="region" tabindex="0" aria-label="Лента последних объявлений" aria-live="polite">${timelineItems(data)}</div>
    </section>`;
  }

  function pager(page, data) {
    const query = c.state.routeContext;
    if (!data.offset && !data.more) return '';
    return `<nav class="announcement-pager" aria-label="Страницы объявлений">${data.offset ? link(pageUrl(page, {query: {...query, offset: Math.max(0, data.offset - data.limit)}}), 'Назад', 'outline-button') : ''}${data.more ? link(pageUrl(page, {query: {...query, offset: data.offset + data.limit}}), 'Далее', 'outline-button') : ''}</nav>`;
  }

  function listPage(page, data) {
    const editor = isOffice(page);
    const query = c.state.routeContext;
    const listStatuses = editor ? {'': 'Все статусы', ...statuses} : {published: 'Опубликованные', archived: 'Архив'};
    const tools = `<form class="card card-pad announcement-filters" data-announcement-filters role="search" aria-label="Поиск и фильтры объявлений">
      <label class="announcement-field"><span>Поиск</span><input name="q" type="search" value="${esc(query.q || '')}" maxlength="100" placeholder="Заголовок или текст"></label>
      ${filter('status', 'Статус', listStatuses, query.status || (editor ? '' : 'published'))}
      ${filter('category', 'Категория', {'': 'Все категории', ...categories}, query.category)}
      ${filter('priority', 'Приоритет', {'': 'Любой', ...priorities}, query.priority)}
      ${filter('sort', 'Порядок', sorts, query.sort || (editor ? 'newest' : 'featured'))}
      <button type="submit" class="outline-button">Применить</button>
    </form>`;
    const actions = editor ? '<button type="button" class="primary-button" data-announcement-action="new">Создать объявление</button>' : '';
    const filtered = query.q || query.category || query.priority;
    const emptyHint = filtered ? 'Измените фильтры или поисковый запрос.' : query.status === 'archived' ? 'Архивных публикаций пока нет.' : 'После публикации объявления появятся здесь.';
    return c.head('', editor ? 'Управление объявлениями' : 'Объявления', editor ? '' : 'Публикации учебного офиса', actions) + tools +
      `<section class="announcement-list" aria-label="Список объявлений">${data.items.length ? data.items.map(row =>
        `<article class="card card-pad announcement-list-item"><h2>${link(pageUrl(page, {id: row.id}), row.title, 'announcement-title-link')}</h2>${metadata(row)}<p class="announcement-excerpt">${esc(row.excerpt)}</p><p class="announcement-meta"><span>${esc(row.unit)}</span><span>${esc(audiences[row.audience])}${row.group ? ' · ' + esc(row.group) : ''}</span><span>${esc(statuses[row.status])}</span></p></article>`).join('') :
        c.empty('megaphone', 'Объявлений не найдено', emptyHint)}${pager(page, data)}</section>`;
  }

  function bodyContent(body, headingLevel = 2) {
    const blocks = body.trim().split(/\r?\n[ \t]*\r?\n/);
    return `<div class="announcement-body">${blocks.map(block =>
      /^## [^\r\n]+$/.test(block) ? `<h${headingLevel}>${esc(block.slice(3))}</h${headingLevel}>` : `<p>${esc(block)}</p>`
    ).join('')}</div>`;
  }

  function detailContent(row, headingLevel) {
    return `${metadata(row, true)}<p class="announcement-meta"><span>${esc(row.unit)} · ${esc(row.author)}</span><span>${esc(audiences[row.audience])}${row.group ? ' · ' + esc(row.group) : ''}</span><span>${esc(statuses[row.status])}</span></p>${bodyContent(row.body, headingLevel)}`;
  }

  function history(data) {
    const id = data.id;
    return `<section class="card card-pad announcement-history" aria-labelledby="announcement-history-title"><h2 id="announcement-history-title">История изменений</h2>
      ${data.revisions.length ? `<ol>${data.revisions.map(event => `<li><details><summary><b>${esc(actionLabels[event.action] || event.action)}</b> <span>${esc(event.author)} · ${date(event.created_at, true)}</span></summary><p><b>${esc(event.after.title)}</b></p>${detailContent(event.after, 3)}</details></li>`).join('')}</ol>` : '<p class="compact-empty">Изменений пока нет.</p>'}
      <nav class="announcement-pager" aria-label="Страницы истории">${data.revision_offset ? link(pageUrl('announcement-admin', {id, query: {history_offset: Math.max(0, data.revision_offset - 20)}}), 'Более новые', 'outline-button') : ''}${data.more_revisions ? link(pageUrl('announcement-admin', {id, query: {history_offset: data.revision_offset + 20}}), 'Более ранние', 'outline-button') : ''}</nav>
    </section>`;
  }

  function render(page, data) {
    if (!data.id) return listPage(page, data);
    const editor = isOffice(page);
    const actions = link(pageUrl(page, {query: !editor && data.status === 'archived' ? {status: 'archived'} : {}}), 'К объявлениям', 'outline-button') +
      (editor && data.status !== 'archived' ? '<button type="button" class="primary-button" data-announcement-action="edit">Редактировать</button>' : '');
    return c.head('', esc(data.title), '', actions) + `<article class="card card-pad announcement-detail">${detailContent(data)}</article>` + (editor ? history(data) : '');
  }

  function syncAudience(form) {
    const group = form.elements.group_id;
    const active = form.elements.audience.value === 'group';
    group.closest('label').hidden = !active;
    group.required = active && !group.disabled;
  }

  async function openEditor(trigger, row = {}) {
    const epoch = c.state.sessionEpoch;
    const loading = c.state.loadingId;
    if (c.state.pending || trigger.disabled) return;
    trigger.disabled = true;
    let groups;
    try {
      groups = await c.api('staff/announcements/groups');
    } finally {
      trigger.disabled = false;
    }
    if (epoch !== c.state.sessionEpoch || loading !== c.state.loadingId || !trigger.isConnected) return;
    const heading = row.id ? 'Редактировать объявление' : 'Создать объявление';
    const groupChoices = {'': 'Выберите группу', ...Object.fromEntries(groups.items.map(item => [item.id, item.name]))};
    const audienceDisabled = row.published_at ? ' disabled' : '';
    c.modal(c.modalHead(heading, '') + `<form class="announcement-editor" data-announcement-editor data-c-form="announcement" data-id="${row.id || ''}" data-version="${row.version || ''}">
      <div class="field"><label for="announcement-title">Заголовок</label><input id="announcement-title" name="title" required minlength="5" maxlength="180" value="${esc(row.title || '')}" autofocus></div>
      <div class="field"><label for="announcement-summary">Анонс</label><textarea id="announcement-summary" name="summary" maxlength="700" rows="3" aria-describedby="announcement-summary-hint">${esc(row.summary || '')}</textarea><p class="hint" id="announcement-summary-hint">Если оставить поле пустым, в ленте появится первый абзац.</p></div>
      <div class="field"><label for="announcement-body">Текст объявления</label><textarea id="announcement-body" name="body" required minlength="10" maxlength="4000" rows="7" aria-describedby="announcement-body-hint">${esc(row.body || '')}</textarea><p class="hint" id="announcement-body-hint">Разделяйте абзацы пустой строкой. Подзаголовок начните с «## ».</p></div>
      <div class="announcement-editor-fields">
        ${filter('category', 'Категория', categories, row.category || 'announcement')}
        ${filter('priority', 'Приоритет', priorityLabels, row.priority || 'normal')}
        <label class="announcement-field"><span>Аудитория</span><select name="audience"${audienceDisabled}>${options(audiences, row.audience || 'students')}</select></label>
        <label class="announcement-field"${row.audience === 'group' ? '' : ' hidden'}><span>Учебная группа</span><select name="group_id"${audienceDisabled}>${options(groupChoices, row.group_id)}</select></label>
        ${row.id ? filter('status', 'Статус', {...statuses, draft: row.published_at ? 'Снять с публикации' : 'Черновик'}, row.status) : ''}
      </div>
      ${row.published_at ? '<p class="announcement-meta">Аудитория сохраняется после первой публикации.</p>' : ''}
      <label class="announcement-pinned"><input type="checkbox" name="pinned"${row.pinned ? ' checked' : ''}> Закрепить в списке</label>
      <div class="inline-error" role="alert" data-announcement-error hidden></div>
      <div class="modal-actions">
        <button type="button" class="outline-button" data-announcement-action="preview">Предпросмотр</button>
        ${row.id ? '<button class="primary-button" type="submit">Сохранить</button>' : '<button class="outline-button" type="submit" value="draft">Сохранить черновик</button><button class="primary-button" type="submit" value="published">Опубликовать</button>'}
      </div>
      <section class="announcement-preview" data-announcement-preview hidden aria-label="Предпросмотр объявления"></section>
    </form>`, {label: heading, wide: true});
    const form = c.$('[data-announcement-editor]');
    if (!form) return;
    try {
      await c.restoreFormDraft(form);
    } finally {
      if (form.isConnected) {
        if (row.published_at) {
          form.elements.audience.value = row.audience;
          form.elements.group_id.value = row.group_id || '';
        }
        syncAudience(form);
      }
    }
  }

  function formValues(form, submitter) {
    const controls = form.elements;
    const values = {title: controls.title.value.trim(), summary: controls.summary.value.trim(),
      body: controls.body.value.trim(), category: controls.category.value,
      priority: controls.priority.value, audience: controls.audience.value, pinned: controls.pinned.checked,
      group_id: controls.audience.value === 'group' ? Number(controls.group_id.value) || null : null,
      status: controls.status?.value || submitter?.value || 'draft'};
    if (form.dataset.id) values.version = Number(form.dataset.version);
    return values;
  }

  function preview(form) {
    syncAudience(form);
    if (!form.reportValidity()) return;
    const values = formValues(form);
    const preview = c.$('[data-announcement-preview]', form);
    preview.innerHTML = `<h3 tabindex="-1">${esc(values.title)}</h3>${metadata(values)}<p class="announcement-meta"><span>Учебный офис</span><span>${esc(audiences[values.audience])}${values.group_id ? ' · ' + esc(form.elements.group_id.selectedOptions[0].textContent) : ''}</span></p>${bodyContent(values.body, 4)}`;
    preview.hidden = false;
    preview.querySelector('h3').focus();
  }

  async function submit(form, submitter) {
    if (c.state.pending) return;
    const epoch = c.state.sessionEpoch;
    const modalId = c.state.modalId;
    const live = () => epoch === c.state.sessionEpoch && modalId === c.state.modalId && form.isConnected;
    const errorBox = c.$('[data-announcement-error]', form);
    const controls = Array.from(form.elements).filter(control => !control.disabled);
    const id = Number(form.dataset.id);
    let result, focus;
    c.state.pending++;
    errorBox.hidden = true;
    controls.forEach(control => control.disabled = true);
    try {
      await c.prepareFormSubmission(form);
      if (!live()) return;
      const values = formValues(form, submitter);
      const key = await c.formSubmission(form, values);
      if (!live()) return;
      result = await c.api('staff/announcements' + (id ? '/' + id : ''), {
        method: id ? 'PATCH' : 'POST', body: JSON.stringify(values), headers: {'Idempotency-Key': key},
      });
      if (!live()) return;
      form.dataset.dirty = 'false';
      try { await c.clearFormDraft(form); } catch (error) { if (!error.stale) c.toast('Объявление сохранено. Черновик пока не удалён.'); }
    } catch (error) {
      if (live() && !error.stale) {
        errorBox.textContent = error.message;
        errorBox.hidden = false;
        focus = c.showFieldErrors(error, form);
      }
    } finally {
      if (epoch === c.state.sessionEpoch) c.state.pending--;
      controls.forEach(control => control.disabled = false);
      if (form._atlasDraft) form._atlasDraft.submitting = false;
      if (live()) syncAudience(form);
      focus?.focus();
    }
    if (!result || !live()) return;
    c.closeModal();
    c.toast(result.status === 'published' ? 'Объявление опубликовано.' : result.status === 'archived' ? 'Объявление перенесено в архив.' : 'Черновик сохранён.');
    if (result.id) await c.route('announcement-admin', {parts: [String(result.id)]});
    else await c.updatePage({quiet: true});
  }

  function init(context) {
    c = context;
    document.addEventListener('submit', event => {
      if (event.target.matches('[data-announcement-filters]')) {
        event.preventDefault();
        c.route(c.state.page, {context: Object.fromEntries(new FormData(event.target))});
      }
      if (event.target.matches('[data-announcement-editor]')) {
        event.preventDefault();
        submit(event.target, event.submitter);
      }
    });
    document.addEventListener('change', event => {
      if (event.target.matches('[data-announcement-editor] [name="audience"]')) syncAudience(event.target.form);
    });
    document.addEventListener('input', event => {
      const editor = event.target.closest('[data-announcement-editor]');
      if (editor) c.$('[data-announcement-preview]', editor).hidden = true;
    });
    document.addEventListener('click', event => {
      const card = event.target.closest('.announcement-event');
      if (card && !event.target.closest('a, summary, .announcement-expansion') && !getSelection()?.toString()) {
        const expansion = card.querySelector('details');
        expansion.open = !expansion.open;
      }
      const button = event.target.closest('[data-announcement-action]');
      if (button) {
        const action = button.dataset.announcementAction;
        if (action === 'preview') preview(button.form);
        else if (action === 'retry') c.updatePage({quiet: true});
        else openEditor(button, action === 'edit' ? c.state.data[c.state.page] : undefined).catch(error => {
          if (!error.stale) c.toast(error.message);
        });
      }
      const priorityButton = event.target.closest('[data-announcement-priority]');
      if (!priorityButton) return;
      timelinePriority = priorityButton.dataset.announcementPriority;
      c.$$('[data-announcement-priority]').forEach(item => item.setAttribute('aria-pressed', String(item === priorityButton)));
      const viewport = c.$('#announcement-timeline-items');
      viewport.innerHTML = timelineItems(c.state.data.home.announcements);
      viewport.scrollTop = 0;
    });
  }

  window.ATLASAnnouncements = {pages, has, validParts, cleanQuery, load, render, init, homeFeed, timeline,
    reset: () => { timelinePriority = ''; }};
})();
