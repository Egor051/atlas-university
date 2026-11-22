/* Reserve-training catalogue, campaigns and private applicant records. */
(() => {
  'use strict';
  const ui = window.ATLASOperations.ui;
  const base = 'units/vuc/admission';
  const campaignStates = {
    draft: 'Черновик', awaiting_dates: 'Сроки уточняются', upcoming: 'Приём ещё не открыт',
    open: 'Приём документов открыт', documents_closed: 'Приём документов завершён',
    not_accepting: 'Набор приостановлен', program_inactive: 'Программа закрыта для набора',
    completed: 'Кампания завершена', archived: 'В архиве',
  };
  const programStates = {draft: 'Черновик', active: 'Актуальная', inactive: 'Программа закрыта для набора'};
  const actions = {
    documents_received: 'Зарегистрировать полученные документы',
    needs_documents: 'Запросить недостающие документы',
    preliminary: 'Отметить начало предварительного отбора',
    admitted: 'Зафиксировать допуск к конкурсу',
    not_admitted: 'Зафиксировать недопуск',
    selection_complete: 'Отметить завершение конкурсных мероприятий',
    recommended: 'Зафиксировать рекомендацию комиссии',
    not_selected: 'Зафиксировать решение комиссии без рекомендации',
    enrolled: 'Зафиксировать допуск приказом',
    not_enrolled: 'Отметить завершение оформления без допуска',
    inquiry_closed: 'Закрыть обращение',
  };
  let c;

  const dateLabel = new Intl.DateTimeFormat('ru-RU', {dateStyle: 'long', timeZone: 'UTC'});
  const esc = value => c.esc(value);
  const year = value => value + '/' + (value + 1);
  const day = value => value ? dateLabel.format(new Date(value)) : 'Уточняется';
  const location = (page, id) => '/app/' + page + '/admission/' + Number(id);
  const records = page => '/app/' + page + '?tab=admissions';
  const paragraph = value => value ? `<p class="user-text">${esc(value)}</p>` : '';
  const button = (action, label, id = '') => `<button type="button" class="outline-button" data-vuc-action="${action}" data-id="${esc(id)}">${esc(label)}</button>`;
  const external = (url, label) => `<a class="mini-link" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>`;
  const source = item => item.source_url ? `<div class="vuc-source">${external(item.source_url, item.source_title)}
    <small>Проверено ${esc(day(item.verified_on))}</small></div>` : '';
  const fact = (name, value) => `<div><dt>${esc(name)}</dt><dd>${esc(value)}</dd></div>`;
  const actionsBar = html => html ? `<div class="op-actions vuc-actions">${html}</div>` : '';
  const caption = (label, value, empty = 'Уточняется') => `<h4>${esc(label)}</h4>${paragraph(value || empty)}`;
  const status = (key, label) => `<span class="vuc-status" data-status="${esc(key)}">${esc(label)}</span>`;
  const list = items => `<ul class="vuc-list">${items.map(item => `<li>${esc(item)}</li>`).join('')}</ul>`;

  function programDetails(program) {
    return caption('Результат подготовки', program.outcome) +
      caption('Связь с основной программой обучения', program.academic_link) +
      caption('Требования программы', program.requirements) + caption('Порядок отбора', program.selection) + source(program);
  }

  function duration(program) {
    return program.duration_months ? program.duration_months + ' мес.' : 'Уточняется';
  }

  function programs(data) {
    const {programs: items, categories} = data.admission;
    const cards = items.map(item => `<article class="vuc-card">
      <header><div><p class="vuc-overline">${esc(categories[item.category])}</p><h3>${esc(item.title)}</h3></div>
      ${data.can_manage || item.state !== 'active' ? status(item.state, programStates[item.state]) : ''}</header>
      <dl class="vuc-facts">${fact('Длительность подготовки', duration(item))}</dl>
      <details class="vuc-detail"><summary>Условия программы</summary>${programDetails(item)}</details>
      ${data.can_manage ? actionsBar(button('edit-program', 'Изменить программу', item.id)) : ''}
    </article>`).join('');
    return ui.section('Программы подготовки', (data.can_manage ? actionsBar(button('new-program', 'Добавить программу')) : '') +
      (cards ? `<div class="vuc-layout">${cards}</div>` : ui.empty('Программ пока нет', 'Здесь появятся опубликованные программы.')));
  }

  function stageDates(stage) {
    if (stage.starts_on && stage.ends_on && stage.starts_on !== stage.ends_on) {
      return day(stage.starts_on) + ' — ' + day(stage.ends_on);
    }
    if (stage.starts_on) return day(stage.starts_on);
    return stage.ends_on ? 'До ' + day(stage.ends_on) : 'Сроки уточняются';
  }

  function steps(item, stages) {
    const dates = Object.entries(stages).map(([key, label]) => {
      const stage = item.stages[key] || {};
      return `<li><strong>${esc(label)}</strong><small>${esc(stageDates(stage))}</small>${paragraph(stage.details)}</li>`;
    }).join('');
    return `<h4>Этапы отбора</h4><ol class="vuc-timeline">${dates}</ol>`;
  }

  function campaign(page, data, item) {
    const docList = item.documents.length ? list(item.documents) : paragraph('Перечень документов уточняется.');
    let action = '';
    if (item.application_id) {
      action = ui.link(location(page, item.application_id), 'Открыть моё обращение', 'outline-button');
    } else if (data.admission.can_apply && item.status === 'open') {
      action = button('inquire', 'Создать обращение', item.id);
    } else if (data.can_manage && item.state !== 'archived') {
      action = button('edit-campaign', 'Изменить кампанию', item.id);
    }
    return `<article class="vuc-card vuc-campaign">
      <header><div><p class="vuc-overline">${esc(year(item.academic_year))} учебный год · ${esc(item.program.title)}</p>
      <h3>${esc(item.title)}</h3></div>${status(item.status, campaignStates[item.status])}</header>
      <dl class="vuc-facts">${fact('Начало приёма документов', day(item.opens_on))}
      ${fact('Последний день приёма (МСК)', day(item.closes_on))}
      ${fact('Конкурсные места', item.seats ?? 'Не опубликованы')}</dl>
      <details class="vuc-detail"><summary>Условия, документы и этапы</summary>
      ${caption('Требования кампании', item.requirements, 'Дополнительные требования уточняются.')}
      ${caption('Основная образовательная программа', item.program.academic_link)}
      ${caption('Требования программы', item.program.requirements)}
      ${caption('Порядок подачи документов', item.procedure)}
      <h4>Перечень документов</h4>${docList}${steps(item, data.admission.stages)}${source(item)}</details>
      ${actionsBar(action)}
    </article>`;
  }

  function campaigns(page, data, archive = false) {
    const items = data.admission.campaigns.filter(item => (item.state === 'archived') === archive);
    const hasActiveProgram = data.admission.programs.some(program => program.state === 'active');
    const create = data.can_manage && !archive ? actionsBar(hasActiveProgram ? button('new-campaign', 'Добавить кампанию') :
      ui.link('/app/vuc-office?tab=programs', 'К программам', 'outline-button')) : '';
    const names = archive ? ['Архив кампаний', 'Архив пока пуст', 'Здесь остаются опубликованные условия завершённых кампаний.'] :
      ['Кампании приёма', 'Подтверждённых кампаний пока нет', 'Даты и условия появятся после публикации ВУЦ.'];
    return ui.section(names[0], create + (items.length ?
      `<div class="vuc-stack">${items.map(item => campaign(page, data, item)).join('')}</div>` : ui.empty(names[1], names[2])));
  }

  function overview(page, data) {
    if (data.office) {
      return (data.can_manage ? '' : ui.section('Доступ к кабинету',
        ui.p('Работа с кампаниями и кандидатами доступна в служебной учётной записи ВУЦ.'))) + campaigns(page, data);
    }
    const {federal_requirements: requirements, law_url: law, order_url: order, stages} = data.admission;
    const hasPublishedCampaign = data.admission.campaigns.some(item => item.state === 'published');
    const generalStages = hasPublishedCampaign ? '' : `<details class="vuc-detail"><summary>Общий порядок отбора</summary>
      ${list(['Подача заявления и документов', ...Object.values(stages)])}</details>`;
    return campaigns(page, data) + programs(data) + ui.section('Федеральные требования к кандидатам',
      list(requirements) + `<div class="op-actions">${external(law, '53-ФЗ, статья 20')}
      ${external(order, 'Порядок Минобороны № 400')}</div>`) +
      ui.section('Как подать документы',
        ui.p('Сверьте условия кампании и передайте комплект указанным в ней способом. В ATLAS можно создать обращение и получать сообщения о следующих шагах.') +
        ui.p('Сведения о программах основаны на открытых источниках. Сроки, комплект документов и места определяются для каждого набора.') +
        generalStages);
  }

  function applications(page, data) {
    const {campaign_id: campaignId, admission_status: currentStatus} = c.state.routeContext;
    const items = data.applications;
    const filters = `<form class="op-inline-form vuc-filter" data-vuc-filter>
      ${ui.select('campaign_id', 'Кампания', [['', 'Все кампании'], ...data.admission.campaigns.map(item =>
        [item.id, year(item.academic_year) + ' · ' + item.title])], campaignId || '')}
      ${ui.select('admission_status', 'Статус обращения', [['', 'Все статусы'], ...Object.entries(data.admission.statuses)], currentStatus)}
      <button type="submit" class="outline-button">Показать</button></form>`;
    return ui.section(data.office ? 'Кандидаты' : 'Мои обращения по приёму', filters +
      ui.list(items.items, item => ui.row(ui.link(location(page, item.id), 'Обращение №' + item.id),
        ui.p([item.student, item.program, year(item.academic_year)].filter(Boolean).join(' · ')) + ui.p(item.status_label)),
      'Обращений пока нет', 'Здесь появятся обращения по выбранным кампаниям.') + ui.pageLinks('/app/' + page, items, 30));
  }

  function detail(page, data) {
    const item = data.admissionDetail;
    const managed = page === 'vuc-office';
    const header = ui.title('Обращение №' + item.id,
      [item.student, item.program, year(item.academic_year), item.status_label].filter(Boolean).join(' · '),
      ui.link(records(page), managed ? 'К кандидатам' : 'К моим обращениям', 'outline-button'));
    const eventList = `<ol class="op-log">${item.history.map(event => `<li>
      <strong>${esc(event.action === 'notice' ? 'Сообщение ВУЦ' : event.status)}</strong>
      <small>${esc(c.stamp(event.created_at))} МСК · ${esc(event.author)}</small>${paragraph(event.message)}
      ${event.basis_ref ? ui.p('Основание ' + event.basis_ref + ' от ' + day(event.basis_on)) : ''}
      ${event.contract_ref ? ui.p('Договор ' + event.contract_ref) : ''}</li>`).join('')}</ol>`;
    const older = item.older_before ? ui.link(ui.url(location(page, item.id), {before: item.older_before}), 'Более ранние события') : '';
    const latest = c.state.routeContext.before ? ui.link(location(page, item.id), 'К последним событиям') : '';
    const action = managed ? item.allowed.map(step => button(step, actions[step])).join('') +
      button('notice', 'Написать кандидату') : '';
    return header + ui.section('Следующие действия', paragraph(item.next_action) +
      actionsBar(action)) + ui.section('История рассмотрения', eventList + actionsBar(latest + older));
  }

  const editor = item => item ? {id: item.id, version: item.version} : {};
  const textField = (key, label, value, maxlength, required = false) =>
    ui.input(key, label, value, 'text', 'maxlength="' + maxlength + '"' + (required ? ' required' : ''));
  const sourceFields = item => `<fieldset class="unit-checklist vuc-fieldset"><legend>Официальный источник</legend>
    ${textField('source_title', 'Название документа или страницы', item?.source_title, 240)}
    ${ui.input('source_url', 'Ссылка на официальный источник', item?.source_url, 'url', 'maxlength="1000"')}
    ${ui.input('verified_on', 'Дата проверки источника', item?.verified_on, 'date')}</fieldset>`;
  const sourceValues = values => ({source_title: values.source_title, source_url: values.source_url,
    verified_on: values.verified_on || null});

  function programEditor(data, item) {
    const publishStates = Object.entries(programStates).filter(([key]) => key !== 'draft' || !item || item.state === 'draft');
    const fields = textField('title', 'Название программы', item?.title, 180, true) +
      ui.select('category', 'Категория подготовки', Object.entries(data.admission.categories), item?.category) +
      ui.input('duration_months', 'Срок освоения (месяцев)', item?.duration_months ?? '', 'number', 'min="1" max="120"') +
      ui.area('outcome', 'Результат обучения', item?.outcome, 1200) +
      ui.area('academic_link', 'Основные образовательные программы и курсы', item?.academic_link, 1800) +
      ui.area('requirements', 'Требования программы', item?.requirements, 2400) +
      ui.area('selection', 'Порядок отбора', item?.selection, 2400) +
      ui.select('state', 'Состояние программы', publishStates, item?.state || 'draft') + sourceFields(item);
    ui.modal(item ? 'Изменить программу' : 'Добавить программу', 'Опубликуйте сведения после проверки источника.', fields,
      values => ui.request(base + '/programs', 'PUT', {...values, ...sourceValues(values), ...editor(item),
        duration_months: values.duration_months ? Number(values.duration_months) : null}), undefined, 'Сохранить', true);
  }

  function stageFields(stages, item) {
    return `<details class="unit-checklist vuc-fieldset"><summary>Сроки отдельных этапов</summary>
      ${Object.entries(stages).map(([key, label]) => {
        const stage = item?.stages[key];
        return `<fieldset><legend>${esc(label)}</legend><div class="op-form-grid">
          ${ui.input(key + '_start', 'Начало · ' + label, stage?.starts_on ?? '', 'date')}
          ${ui.input(key + '_end', 'Окончание · ' + label, stage?.ends_on ?? '', 'date')}</div>
          ${ui.area(key + '_details', 'Пояснение · ' + label, stage?.details, 500)}</fieldset>`;
      }).join('')}</details>`;
  }

  function campaignEditor(data, item) {
    const published = item?.state === 'published';
    const available = data.admission.programs.filter(program => program.state === 'active' || program.id === item?.program_id);
    const program = available.find(program => program.id === item?.program_id);
    if (!available.length) return;
    const states = published ? [['published', 'Опубликована'], ['archived', 'В архив']] :
      [['draft', 'Черновик'], ['published', 'Опубликована']];
    const identity = published ? ui.p(program.title + ' · ' + year(item.academic_year)) :
      ui.select('program_id', 'Программа', available.map(program => [program.id, program.title]), item?.program_id) +
      ui.input('academic_year', 'Первый год учебного года', item?.academic_year, 'number', 'required min="2000" max="2199"');
    const fields = identity + textField('title', 'Название кампании', item?.title, 180, true) +
      ui.select('state', 'Состояние кампании', states, item?.state || 'draft') +
      `<div class="op-form-grid">${ui.input('opens_on', 'Начало приёма документов', item?.opens_on ?? '', 'date')}
      ${ui.input('closes_on', 'Последний день приёма', item?.closes_on ?? '', 'date')}</div>` +
      ui.yesNo('intake_enabled', 'Принимать обращения в опубликованные даты', item?.intake_enabled ?? true) +
      ui.input('seats', 'Подтверждённое число мест', item?.seats ?? '', 'number', 'min="1" max="100000"') +
      ui.area('requirements', 'Требования конкретного набора', item?.requirements, 2400) +
      ui.area('documents', 'Документы, по одному на строку', item?.documents.join('\n'), 6000) +
      ui.area('procedure', 'Как и куда подать документы', item?.procedure, 2400) +
      stageFields(data.admission.stages, item) + sourceFields(item);
    const save = values => ui.request(base + '/campaigns', 'PUT', {
      ...editor(item), ...sourceValues(values), title: values.title, state: values.state,
      academic_year: published ? item.academic_year : Number(values.academic_year),
      program_id: published ? item.program_id : Number(values.program_id),
      opens_on: values.opens_on || null, closes_on: values.closes_on || null,
      seats: values.seats ? Number(values.seats) : null, intake_enabled: values.intake_enabled === 'true',
      documents: values.documents.split('\n').map(value => value.trim()).filter(Boolean),
      procedure: values.procedure, requirements: values.requirements,
      stages: Object.fromEntries(Object.keys(data.admission.stages).map(key => [key, {
        starts_on: values[key + '_start'] || null, ends_on: values[key + '_end'] || null,
        details: values[key + '_details'],
      }]).filter(([, value]) => value.starts_on || value.ends_on || value.details.trim())),
    });
    ui.modal(item ? 'Изменить кампанию' : 'Добавить кампанию', 'Заполняйте даты и места по утверждённому источнику.', fields,
      save, undefined, 'Сохранить', true);
  }

  function inquiry(item) {
    const fields = ui.p(item.program.title + ' · ' + year(item.academic_year)) +
      `<label class="unit-check"><input name="confirmed" type="checkbox" required>
      <span>Порядок отдельной подачи документов мне понятен</span></label>`;
    ui.modal('Создать обращение', 'После отправки передайте комплект документов указанным в кампании способом.', fields,
      values => ui.request(base + '/applications', 'POST', {campaign_id: item.id, confirmed: values.confirmed === 'on'}),
      result => c.route('vuc', {parts: ['admission', String(result.id)]}), 'Отправить обращение');
  }

  function stepEditor(item, action) {
    const label = item.basis_labels[action];
    const fields = ui.area('message', 'Сообщение кандидату и следующие действия', '', 1200) +
      (label ? textField('basis_ref', label, '', 160, true) +
        ui.input('basis_on', 'Дата документа', '', 'date', 'required') : '') +
      (action === 'enrolled' ? textField('contract_ref', 'Реквизиты подписанного договора', '', 160, true) : '');
    const notice = action === 'notice';
    ui.modal(notice ? 'Написать кандидату' : actions[action],
      'Добавьте пояснение. Храните медицинские документы и результаты процедур в уполномоченных системах.', fields,
      values => ui.request(base + '/applications/' + item.id + '/' + (notice ? 'notice' : 'step'), 'POST', {
        ...values, version: item.version, ...(notice ? {} : {status: action}),
      }), undefined, 'Сохранить');
  }

  function init(context) {
    c = context;
    document.addEventListener('click', event => {
      const target = event.target.closest('[data-vuc-action]');
      if (!target || c.state.pending || !['vuc', 'vuc-office'].includes(c.state.page)) return;
      const data = c.state.data[c.state.page];
      if (!data) return;
      const {vucAction: action, id} = target.dataset;
      if (data.admissionDetail) return stepEditor(data.admissionDetail, action);
      if (action.endsWith('-program')) return programEditor(data, data.admission.programs.find(item => item.id === Number(id)));
      const item = data.admission.campaigns.find(item => item.id === Number(id));
      if (action === 'inquire') return inquiry(item);
      if (action.endsWith('-campaign')) return campaignEditor(data, item);
    });
    document.addEventListener('submit', event => {
      if (!event.target.hasAttribute('data-vuc-filter')) return;
      event.preventDefault();
      const filters = Object.fromEntries(new FormData(event.target));
      c.route(c.state.page, {context: {tab: 'admissions', ...filters}});
    });
  }

  window.ATLASVuc = {init, overview, programs, campaigns, applications, detail};
})();
