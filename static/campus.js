/* ATLAS Campus learning and campus services. */
(() => {
  'use strict';
  const pages = [
    {id:'assignments',label:'Сдача работ',icon:'send',group:'study',hint:'Задания, ответ, ссылка на проект и повторная сдача'},
    {id:'exams',label:'Сессия и зачёты',icon:'graduation',group:'study',hint:'Экзамены, зачёты, допуски и результаты'},
    {id:'consultations',label:'Консультации',icon:'user',group:'services',hint:'Записаться к преподавателю и отменить запись'},
    {id:'messages',label:'Вопросы в учебный офис',icon:'send',group:'services',hint:'Переписка, вопрос деканату, ответ и история'},
    {id:'events',label:'Жизнь кампуса',icon:'calendar',group:'services',hint:'Кружки, мероприятия, запись и отмена участия'},
    {id:'finance',label:'Финансы',icon:'file',group:'services',hint:'Начисления, оплата и стипендия'},
    {id:'contacts',label:'Контакты и корпуса',icon:'pin',group:'services',hint:'Преподаватели, службы, аудитории и часы приёма'},
    {id:'knowledge',label:'Помощь и правила',icon:'info',group:'services',hint:'Частые вопросы и инструкции по сценариям'},
    {id:'settings',label:'Настройки',icon:'shield',hint:'Вид кабинета, уведомления и сеансы'},
    {id:'staffdesk',label:'Сводка учебного офиса',icon:'home',staff:true,hint:'Сводка офиса, консультации, мероприятия и объявления'},
    {id:'staffmessages',label:'Вопросы студентов',icon:'send',staff:true,hint:'Ответить на вопрос и закрыть обращение'},
  ];
  let c;
  const local = {query:{},filter:{assignments:'pending'},offset:{},scope:{},context:{},ticketOffsets:{},pendingKeys:{},catalog:'documents'};
  let serviceSearchTimer;
  const esc = v => c.esc(v);
  const icon = n => c.icon(n);
  const moscowTime=value=>new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/Moscow',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(value));
  const moscowDay = value => {const parts=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Moscow',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date(value)).map(p=>[p.type,p.value]));return `${parts.year}-${parts.month}-${parts.day}`;};
  const items = d => Array.isArray(d)?d:d?.items||[];
  const current = () => c.state.data[c.state.page];
  const match = (row,q) => !q||Object.values(row).filter(v=>typeof v==='string'||typeof v==='number').join(' ').toLocaleLowerCase('ru').includes(q.toLocaleLowerCase('ru'));
  const filtered = (d,page) => items(d).filter(x=>match(x,local.query[page]||''));
  const action = (name,label,id='',extra='') => `<button type="button" class="outline-button" data-c-action="${name}"${id!==''?` data-id="${esc(id)}"`:''} ${extra}>${esc(label)}</button>`;
  const primary = (name,label,id='',extra='') => `<button type="button" class="primary-button" data-c-action="${name}"${id!==''?` data-id="${esc(id)}"`:''} ${extra}>${icon('plus')}${esc(label)}</button>`;
  const link = (page,label) => `<button class="mini-link" data-route="${esc(page)}">${esc(label)} ${icon('arrow')}</button>`;
  const contextLink = (page,label,context={}) => `<button type="button" class="mini-link" data-route="${esc(page)}"${context.id?` data-record-id="${Number(context.id)}"`:''}${context.subject?` data-subject="${esc(context.subject)}"`:''}${context.date?` data-date="${esc(context.date)}"`:''}${context.kind?` data-kind="${esc(context.kind)}"`:''}>${esc(label)} ${icon('arrow')}</button>`;
  const servicePages=new Set(['consultations','events','messages','staffmessages','finance','staffdesk']);
  const pageSize=20;
  const pageParams=(key,extra={})=>new URLSearchParams({limit:String(pageSize),offset:String(local.offset[key]||0),...extra}).toString();
  const serviceQuery=page=>(local.query[page]||local.context[page]?.subject||'').slice(0,100);
  const recordFilter=page=>local.context[page]?.id?{record_id:String(local.context[page].id)}:{};
  function pager(d,key,label='Записи'){
    if(!d||!Number.isFinite(d.total)||d.total<=d.limit)return '';
    return `<nav class="campus-pagination" aria-label="${esc(label)} — страницы"><span role="status">${d.total?d.offset+1:0}–${Math.min(d.offset+items(d).length,d.total)} из ${d.total}</span><div>${action('service-page','Назад','',`data-page-key="${esc(key)}" data-offset="${Math.max(0,d.offset-d.limit)}" aria-label="Назад: ${esc(label)}, предыдущая страница" ${d.offset?'':'disabled'}`)}${action('service-page','Далее','',`data-page-key="${esc(key)}" data-offset="${d.offset+d.limit}" aria-label="Далее: ${esc(label)}, следующая страница" ${d.has_more?'':'disabled'}`)}</div></nav>`;
  }
  function contextNotice(page){const ctx=local.context[page];return ctx?.subject||ctx?.id?`<div class="note-callout campus-context">${icon('info')}<span>${ctx.subject?'По дисциплине: <strong>'+esc(ctx.subject)+'</strong>':'Показана выбранная запись.'}</span>${action('clear-context','Показать всё','',`data-context-page="${esc(page)}"`)}</div>`:'';}
  const scopeToolbar=page=>`<div class="filter-tabs campus-scope" aria-label="Период записей">${[['upcoming','Предстоящие'],['archive','Архив'],['all','Все даты']].map(([key,label])=>`<button data-c-scope="${page}" data-value="${key}" aria-pressed="${(local.scope[page]||'upcoming')===key}">${label}</button>`).join('')}</div>`;
  function restoreSearchFocus(position){const input=c.$('#campus-query');if(input){input.focus({preventScroll:true});if(Number.isInteger(position))input.setSelectionRange(position,position);}}
  async function refreshService(position){const page=c.state.page,epoch=c.state.sessionEpoch;const loading=c.updatePage({quiet:true});const loadingId=c.state.loadingId;await loading;if(page===c.state.page&&epoch===c.state.sessionEpoch&&loadingId===c.state.loadingId&&Number.isInteger(position))restoreSearchFocus(position);}
  async function pendingMutation(path,body){
    const source=JSON.stringify([c.state.user?.id,path,body]);
    const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(source));
    const fingerprint=[...new Uint8Array(digest)].map(x=>x.toString(16).padStart(2,'0')).join('');
    const storageKey='atlas-action-'+c.state.user.id+'-'+fingerprint;
    let key=local.pendingKeys[storageKey];try{key=key||sessionStorage.getItem(storageKey);}catch{/* Memory fallback if browser storage is blocked. */}
    if(!key){key=crypto.randomUUID();local.pendingKeys[storageKey]=key;try{sessionStorage.setItem(storageKey,key);}catch{/* Keep the key in memory until the result is known. */}}
    return {key,clear:()=>{delete local.pendingKeys[storageKey];try{sessionStorage.removeItem(storageKey);}catch{/* No persisted key was available. */}}};
  }
  const pill = (text,tone='') => `<span class="campus-pill ${tone}">${esc(text)}</span>`;
  const fold = (heading,content) => c.disclosure(esc(heading),content);
  const textDetails = (text,label='Подробнее') => text?`<details class="text-details"><summary>${esc(label)}</summary>${paragraph(text)}</details>`:'';
  const paragraph = text => `<p class="user-text campus-body">${esc(text)}</p>`;
  const info = text => `<div class="note-callout">${icon('info')}<span>${esc(text)}</span></div>`;
  const section = (title,content) => `<section class="card card-pad campus-section"><h2 class="card-title">${esc(title)}</h2>${content}</section>`;
  const grid = (rows,render,emptyTitle='Здесь пока ничего нет',emptyText='Сохраните первую запись — она останется в вашем кабинете.') => rows.length?`<div class="campus-grid" data-c-list>${rows.map(render).join('')}</div>`:`<section class="card card-pad" data-c-list>${c.empty('book',emptyTitle,emptyText)}</section>`;
  function prepareRoute(page,context={}){
    clearTimeout(serviceSearchTimer);local.query[page]='';local.filter[page]='all';local.offset[page]=0;
    const ctx={};if(Number.isInteger(Number(context.id))&&Number(context.id)>0)ctx.id=Number(context.id);
    if(typeof context.subject==='string'&&context.subject.trim())ctx.subject=context.subject.trim().slice(0,130);
    if(typeof context.date==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(context.date))ctx.date=context.date;
    if(typeof context.kind==='string')ctx.kind=context.kind.slice(0,40);
    local.context[page]=ctx;if(ctx.subject&&!ctx.id)local.query[page]=ctx.subject.slice(0,100);
    if(['consultations','events'].includes(page)&&ctx.id)local.scope[page]='all';
  }
  function focusRecord(id){
    c.$$('.campus-context-target').forEach(el=>el.classList.remove('campus-context-target'));
    const target=c.$(`[data-campus-record-id="${Number(id)}"]`);if(!target)return false;
    target.classList.add('campus-context-target');target.setAttribute('tabindex','-1');target.scrollIntoView({block:'center',behavior:'instant'});target.focus({preventScroll:true});return true;
  }
  async function openContext(page,context={}){
    const id=Number(context.id);const data=c.state.data[page];
    if(page==='assignments'&&id)return assignmentModal(id);
    if(['messages','staffmessages'].includes(page)&&id)return ticketModal(id);
    if(id&&!focusRecord(id))c.toast('Запись не найдена или больше недоступна. Можно выбрать другое действие в разделе.');
  }
  const title = (page,description,actions='') => c.head('Всё для учёбы',pages.find(p=>p.id===page)?.label||page,description,actions);
  const stats = metrics => `<div class="campus-metrics">${metrics.map(([value,label])=>`<div class="card campus-metric"><b>${esc(value)}</b><span>${esc(label)}</span></div>`).join('')}</div>`;
  const toolbar = (page,options=[]) => `<div class="filter-bar campus-toolbar">
    <label class="search-field">${icon('search')}<input data-c-query="${page}" id="campus-query" maxlength="100" value="${esc(local.query[page]||'')}" aria-label="Поиск в разделе" placeholder="Найти в разделе…" /></label>
    ${options.length?`<div class="filter-tabs" aria-label="Фильтр">${options.map(([key,label])=>`<button data-c-filter="${page}" data-value="${key}" aria-pressed="${(local.filter[page]||'all')===key}">${esc(label)}</button>`).join('')}</div>`:''}
  </div>`;
  const field = (name,label,value='',options={}) => {
    const id='campus-field-'+name;
    const extra=`${options.required?' required':''}${options.min!==undefined?` min="${options.min}"`:''}${options.max!==undefined?` max="${options.max}"`:''}${options.minlength?` minlength="${options.minlength}"`:''}${options.maxlength?` maxlength="${options.maxlength}"`:''}`;
    const control=options.choices?`<select id="${id}" name="${name}" ${extra}>${options.choices.map(([key,text])=>`<option value="${esc(key)}" ${String(key)===String(value)?'selected':''}>${esc(text)}</option>`).join('')}</select>`:options.rows?`<textarea id="${id}" name="${name}" rows="${options.rows}" ${extra}>${esc(value)}</textarea>`:`<input id="${id}" name="${name}" type="${options.type||'text'}" value="${esc(value)}" ${extra} />`;
    return `<div class="field"><label for="${id}">${esc(label)}</label>${control}${options.hint?`<span class="hint">${esc(options.hint)}</span>`:''}</div>`;
  };
  function formModal(name,heading,description,fields,{id='',submit='Сохранить',wide=false,before='',after=''}={}) {
    c.modal(c.modalHead(heading,description)+before+`<form data-c-form="${name}" data-id="${esc(id)}">${fields}<div class="inline-error" data-c-error role="alert" hidden></div>${after}<div class="modal-actions"><button class="muted-button" type="button" data-action="close-modal">Отмена</button><button class="primary-button" type="submit">${icon('check')}${esc(submit)}</button></div></form>`,{label:heading,wide});
    c.$('.modal input:not([type=hidden]),.modal textarea,.modal select')?.focus();
  }
  function external(url,label='Открыть ссылку') {
    try {const parsed=new URL(url);if(parsed.protocol!=='https:'||parsed.username||parsed.password)return '';return `<a class="mini-link" href="${esc(parsed.href)}" target="_blank" rel="noopener noreferrer">${esc(label)} ${icon('arrow')}</a>`;}catch{return '';}
  }
  function refreshPreservingInput(){const active=document.activeElement;const value=active?.value;const pos=active?.selectionStart;const id=active?.id;c.drawPage();const replacement=id?document.getElementById(id):null;if(replacement){replacement.focus({preventScroll:true});if(typeof pos==='number')try{replacement.setSelectionRange(pos,pos);}catch{/* Select and date inputs have no selection. */}if(value!==undefined&&replacement.value!==value)replacement.value=value;}}
  async function pageApi(key,path,extra={}){const epoch=c.state.sessionEpoch,loadingId=c.state.loadingId,page=c.state.page;let result=await c.api(path+'?'+pageParams(key,extra));if(epoch===c.state.sessionEpoch&&loadingId===c.state.loadingId&&page===c.state.page&&result.offset>0&&result.offset>=result.total){local.offset[key]=Math.max(0,Math.floor((result.total-1)/result.limit)*result.limit);result=await c.api(path+'?'+pageParams(key,extra));}return result;}
  async function load(page) {
    if(page==='assignments')return c.api('learning/assignments?offset='+Number(local.offset.assignments||0));
    const api=c.api;
    if(page==='exams')return api('learning/'+page);
    if(page==='settings'){const [sessions,preferences]=await Promise.all([api('account/sessions'),api('services/preferences')]);return {sessions,preferences};}
    if(page==='consultations'){const [slots,bookings]=await Promise.all([pageApi('consultations','services/consultations',{q:serviceQuery(page),scope:local.scope[page]||'upcoming',...recordFilter(page)}),pageApi('bookings','services/bookings')]);return {slots,bookings};}
    if(page==='events'){const [events,registrations]=await Promise.all([pageApi('events','services/events',{q:serviceQuery(page),filter:local.filter[page]||'all',scope:local.scope[page]||'upcoming',...recordFilter(page)}),pageApi('registrations','services/registrations')]);return {events,registrations};}
    if(page==='messages')return pageApi(page,'services/tickets',{q:local.query[page]||'',filter:local.filter[page]||'all',...recordFilter(page)});
    if(page==='staffmessages')return pageApi(page,'staff/tickets',{q:local.query[page]||'',filter:local.filter[page]||'all',...recordFilter(page)});
    if(page==='finance')return pageApi(page,'services/finance',{q:local.query[page]||''});
    if(page==='staffdesk'){const [overview,slots]=await Promise.all([api('staff/overview'),pageApi('staffslots','staff/consultations')]);return {overview,slots};}
    return api('services/'+page);
  }


  const workStatuses={not_started:'Не начато',in_progress:'В работе',submitted:'Отправлено',in_review:'На проверке',
    revision_required:'Требуется доработка',resubmitted:'Повторно отправлено',accepted:'Принято',completed:'Завершено',withdrawn:'Отозвано'};
  const workKinds={homework:'Домашняя работа',lab:'Лабораторная работа',practice:'Практическая работа',test:'Контрольная работа',
    independent:'Самостоятельная работа',essay:'Реферат',talk:'Доклад',project:'Проектная работа',term_paper:'Курсовая работа',
    individual:'Индивидуальная работа',group:'Групповая работа'};
  const pendingWork=x=>x.state!=='archived'&&['not_started','in_progress','withdrawn','revision_required'].includes(x.status);
  function assignments(d){
    const mode=local.filter.assignments||'pending',all=items(d),sent=all.filter(x=>!pendingWork(x)&&x.state!=='archived').length;
    const rows=filtered(d,'assignments').filter(x=>mode==='submitted'?(!pendingWork(x)&&x.state!=='archived'):mode==='pending'?pendingWork(x):true)
      .sort((a,b)=>a.due_date.localeCompare(b.due_date));
    const cards=rows.map(x=>{
      const actionable=pendingWork(x), label=x.state==='archived'?'В архиве':x.status==='not_started'?(x.overdue?'Просрочено':c.relative(x.due_date)):workStatuses[x.status];
      const tone=x.overdue||x.status==='revision_required'?'warning':!actionable&&x.state!=='archived'?'success':'';
      const type=x.custom_kind||workKinds[x.kind];
      return `<article class="card compact-row assignment-row" data-campus-record-id="${Number(x.id)}"><div class="row-copy">
        <h2>${esc(x.title)}</h2><p>${esc(x.subject)} · до ${c.dateFmt(x.due_date)}${x.due_at?' · '+moscowTime(x.due_at)+' МСК':''}</p>
        ${type?`<small>${esc(type)}</small>`:''}</div><div class="row-end">${pill(label||'Открыть',tone)}
        ${action('assignment',actionable&&x.can_submit?'Сдать работу':'Открыть работу',x.id)}</div></article>`;
    }).join('');
    const pages=d.offset||d.more?`<nav class="campus-pagination" aria-label="Страницы заданий"><span role="status">${d.offset+1}–${d.offset+all.length}</span><div>
      ${action('service-page','Назад','','data-page-key="assignments" data-offset="'+Math.max(0,d.offset-200)+'" '+(d.offset?'':'disabled'))}
      ${action('service-page','Далее','','data-page-key="assignments" data-offset="'+(d.offset+200)+'" '+(d.more?'':'disabled'))}</div></nav>`:'';
    return title('assignments','Откройте задание, прочитайте инструкцию и отправьте работу.')+
      stats([[all.length,pages?'заданий на странице':'всего заданий'],[sent,'отправлено'],[all.filter(x=>x.state!=='archived'&&x.overdue).length,'просрочено']])+
      contextNotice('assignments')+toolbar('assignments',[['pending','К сдаче'],['submitted','Отправлены'],['all','Все']])+
      `<div class="compact-list" data-c-list>${cards||c.empty('checkCircle','Работ по этому фильтру нет','Выберите другой фильтр, чтобы посмотреть остальные задания.')}</div>`+pages;
  }
  function exams(d){
    const rows=filtered(d,'exams');
    const actions={consultations:'Уточнить на консультации',courses:'Открыть материалы курса'};
    return title('exams','Даты, допуск и результаты промежуточной аттестации.',link('grades','Учебные результаты'))+contextNotice('exams')+toolbar('exams')+grid(rows,x=>{
      const status=x.status;
      const fields=[['Преподаватель',x.teacher],['Место',x.location],['Допуск',status.admission],['Результат',status.result],
        ['Накопленные баллы',x.current!=null?`${x.current}${x.max_grade?' / '+x.max_grade:''}`:'']];
      return `<article class="card campus-tile" data-campus-record-id="${Number(x.id)}" data-assessment-status="${esc(status.code)}">
        <div class="campus-tile-top">${pill(x.kind)}${pill(status.label,status.tone)}</div><h2>${esc(x.subject)}</h2>
        ${x.exam_date?`<p class="campus-date"><time datetime="${esc(x.exam_date)}">${c.dateFmt(x.exam_date,{day:'numeric',month:'long',year:'numeric'})}</time></p>`:''}
        <dl class="academic-exam-fields">${fields.filter(([,value])=>value).map(([label,value])=>`<div><dt>${label}</dt><dd>${esc(value)}</dd></div>`).join('')}</dl>
        ${status.explanation?paragraph(status.explanation):''}
        <div class="campus-tile-bottom">${actions[status.action]?contextLink(status.action,actions[status.action],{subject:x.subject}):''}${contextLink('grades','Посмотреть успеваемость',{subject:x.subject})}</div>
      </article>`;
    },'Аттестаций пока нет','Здесь появятся дисциплины, по которым назначена форма контроля.');
  }

  function consultations(d){
    const rows=items(d.slots);const history=items(d.bookings);const ctx=local.context.consultations;
    const historyHTML=history.length||d.bookings?.total?section('Мои записи и история',`<div class="campus-log">${history.map(x=>`<article data-campus-booking-id="${Number(x.id)}"><span class="campus-hub-icon">${icon('user')}</span><div><b>${esc(x.slot.subject)}</b><p>${esc(x.slot.teacher)} · ${c.stamp(x.slot.start_at)} МСК · ${esc(x.slot.room)}</p><small>${['active','booked'].includes(x.status)?'Запись сохранена':'Запись отменена'}</small></div>${['active','booked'].includes(x.status)?action('booking-cancel','Отменить',x.id):pill('Отменена')}</article>`).join('')}</div>`+pager(d.bookings,'bookings','История консультаций')):'';
    const alternative=ctx?.subject&&!rows.some(x=>!x.my_booking_id&&x.booked_count<x.capacity&&new Date(x.start_at)>new Date())?section('Как продолжить подготовку',`<p>По дисциплине «${esc(ctx.subject)}» сейчас нет доступного времени. Можно открыть материалы, посмотреть работы или задать вопрос учебному офису.</p><div class="campus-button-row">${contextLink('courses','Материалы',{subject:ctx.subject})}${contextLink('assignments','Работы',{subject:ctx.subject})}${contextLink('messages','Спросить о консультации',{subject:ctx.subject})}</div>`):'';
    return title('consultations','Выберите удобное время. Свободные места проверяются при записи.')+contextNotice('consultations')+historyHTML+toolbar('consultations')+scopeToolbar('consultations')+grid(rows,x=>`<article class="card campus-tile" data-campus-record-id="${Number(x.id)}"><div class="campus-tile-top">${pill(x.my_booking_id?'Вы записаны':Math.max(0,x.capacity-x.booked_count)+' мест',x.my_booking_id?'success':'')}${icon('user')}</div><h2>${esc(x.subject)}</h2><p>${esc(x.teacher)}</p><p class="campus-date">${c.stamp(x.start_at)} МСК</p><p>${esc(x.room)} · до ${new Intl.DateTimeFormat('ru-RU',{timeZone:'Europe/Moscow',hour:'2-digit',minute:'2-digit'}).format(new Date(x.end_at))}</p><div class="campus-tile-bottom">${x.my_booking_id?action('booking-cancel','Отменить запись',x.my_booking_id):action('consultation-book',new Date(x.start_at)<=new Date()?'Запись закрыта':x.booked_count>=x.capacity?'Мест нет':'Записаться',x.id,(x.booked_count>=x.capacity||new Date(x.start_at)<=new Date())?'disabled':'')}</div></article>`,'Консультаций не найдено','Измените поиск, период или спросите учебный офис.')+pager(d.slots,'consultations','Каталог консультаций')+alternative;
  }
  const categoryLabels={science:'Наука',career:'Карьера',sport:'Спорт',community:'Сообщество',academic:'Учёба',documents:'Документы',finance:'Финансы',campus:'Кампус',security:'Безопасность',study:'Учёба',support:'Поддержка'};
  const ticketTopics=[['academic','Учебный вопрос'],['technical','Техническая помощь'],['financial','Финансы'],['other','Другое']];

  function messages(d,staff=false){
    const page=staff?'staffmessages':'messages';const rows=items(d);
    return title(page,staff?'Вопросы студентов и история ответов.':'Задайте вопрос деканату. Ответ появится в этой переписке.',staff?'':primary('ticket-new','Задать вопрос'))+contextNotice(page)+toolbar(page,[['all','Все'],['open','Открыты'],['closed','Закрыты']])+`<div class="compact-list" data-c-list>${rows.map(x=>{const last=x.messages?.at(-1);const label=x.status==='closed'?'Закрыт':last?.actor_role==='staff'?(staff?'Ответ отправлен':'Есть ответ'):(staff?'Нужен ответ':'Ждёт ответа');return `<article class="card compact-row" data-campus-record-id="${Number(x.id)}"><div class="row-copy"><h2>${esc(x.title)}</h2><p>${staff?esc((x.student_name||'Студент')+' · '+(x.group||''))+' · ':''}№ ${Number(x.id)} · ${c.stamp(x.updated_at)}</p>${last?`<p class="note-preview">${esc(last.body.slice(0,120))}${last.body.length>120?'…':''}</p>`:''}</div><div class="row-end">${pill(label,x.status==='closed'||last?.actor_role==='staff'?'success':'')}${action('ticket-open','Открыть диалог',x.id)}</div></article>`;}).join('')||c.empty('send','Диалогов по этому запросу нет',staff?'Измените поиск или фильтр.':'Измените поиск или создайте вопрос — его увидит сотрудник учебного офиса.')}</div>`+pager(d,page,'Диалоги');
  }
  function events(d){
    const mode=local.filter.events||'all';const rows=items(d.events).filter(x=>mode==='mine'?x.my_registration_id:mode==='available'?x.registered_count<x.capacity&&new Date(x.start_at)>new Date():true);
    const history=items(d.registrations);const historyHTML=history.length||d.registrations?.total?section('Моё участие и история',`<div class="campus-log">${history.map(x=>`<article><span class="campus-hub-icon">${icon('calendar')}</span><div><b>${esc(x.event.title)}</b><p>${c.stamp(x.event.start_at)} МСК · ${esc(x.event.location)}</p><small>${['active','registered'].includes(x.status)?'Участие сохранено':'Участие отменено'}</small></div>${['active','registered'].includes(x.status)?contextLink('events','Открыть запись',{id:x.event_id,date:moscowDay(x.event.start_at)}):pill('Отменено')}</article>`).join('')}</div>`+pager(d.registrations,'registrations','История участия')):'';
    return title('events','Встречи, кружки и возможности за пределами пар. Записи остаются в вашем календаре.')+contextNotice('events')+historyHTML+toolbar('events',[['all','Все'],['available','Есть места'],['mine','Я участвую']])+scopeToolbar('events')+grid(rows,x=>`<article class="card campus-tile" data-campus-record-id="${Number(x.id)}"><div class="campus-tile-top">${pill(categoryLabels[x.category]||x.category)}${pill(x.my_registration_id?'Вы участвуете':Math.max(0,x.capacity-x.registered_count)+' мест',x.my_registration_id?'success':'')}</div><h2>${esc(x.title)}</h2><p class="campus-date">${c.stamp(x.start_at)} МСК</p><p>${icon('pin')} ${esc(x.location)}</p>${textDetails(x.description)}<div class="campus-tile-bottom">${x.my_registration_id?action('event-cancel','Отменить участие',x.my_registration_id):action('event-register',new Date(x.start_at)<=new Date()?'Запись закрыта':x.registered_count>=x.capacity?'Мест нет':'Участвовать',x.id,x.registered_count>=x.capacity||new Date(x.start_at)<=new Date()?'disabled':'')}</div></article>`,'Мероприятий по фильтру нет','Попробуйте все события, другую дату или другой запрос.')+pager(d.events,'events','Каталог мероприятий');
  }
  const money = v => new Intl.NumberFormat('ru-RU',{style:'currency',currency:'RUB',maximumFractionDigits:2}).format(Number(v||0)/100);
  function finance(d){
    return title('finance','Стипендии, начисления и расходы.',`<button class="outline-button" data-action="new-request" data-type="tuition">${icon('send')} Вопрос об оплате</button>`)+`<div class="campus-flow finance-flow">`+`<div class="finance-summary">${[[money(d.summary?.credits_kopecks),'Поступления'],[money(d.summary?.debits_kopecks),'Расходы'],[money(d.summary?.balance_kopecks),'Разница']].map(([value,label])=>`<div class="card"><b>${esc(value)}</b><span>${label}</span></div>`).join('')}</div>`+info('Приём платежей отключён. Банковские данные не нужны.')+toolbar('finance')+section('Операции учебного года',filtered(d,'finance').length?`<div class="campus-log">${filtered(d,'finance').map(x=>`<article><time>${c.dateFmt(x.date,{day:'numeric',month:'short'})}</time><div><b>${esc(x.description)}</b><p>${x.direction==='credit'?'Поступление':'Расход'}</p></div><strong class="campus-money ${x.direction==='credit'?'positive':''}">${x.direction==='credit'?'+':'−'}${money(x.amount_kopecks)}</strong></article>`).join('')}</div>`:c.empty('file','Операций не найдено','Проверьте поиск.'))+pager(d,'finance','Финансовые операции')+fold('Поддержка и документы',`<div class="campus-button-row"><button class="outline-button" data-action="new-request" data-type="scholarship">Справка о стипендии</button><button class="outline-button" data-action="new-request" data-type="social_support">Материальная поддержка</button><button class="outline-button" data-action="new-request" data-type="tax">Справка об оплате</button></div>`)+`</div>`;
  }

  function contacts(d){
    const rows=filtered(d,'contacts');return title('contacts','Преподаватели и службы: кабинеты и часы приёма.',link('consultations','Записаться на консультацию'))+toolbar('contacts')+`<div class="compact-list" data-c-list>${rows.map(x=>`<article class="card compact-row contact-row"><div class="row-copy"><h2>${esc(x.name)}</h2><p>${esc(x.role)}${x.subject?' · '+esc(x.subject):''}</p><p><b>${esc(x.room)}</b> · ${esc(x.hours)}</p><details class="text-details"><summary>Электронная почта</summary><p>${esc(x.email)}</p></details></div>${pill(x.department||'Кампус')}</article>`).join('')||c.empty('search','Контакт не найден','Измените название службы, предмет или имя.')}</div><div class="request-contact"><span>Не знаете, к кому обратиться?</span>${link('messages','Написать в учебный офис')}</div>`;
  }
  function knowledge(d){return title('knowledge','Ответы на частые вопросы о работе кабинета.')+toolbar('knowledge')+`<div class="campus-faq">${filtered(d,'knowledge').map(x=>`<details class="card"><summary><span>${pill(categoryLabels[x.category]||x.category)}<b>${esc(x.title)}</b></span>${icon('plus')}</summary><div>${paragraph(x.body)}</div></details>`).join('')||c.empty('search','Ответ не найден','Попробуйте поиск по разделам или задайте вопрос учебному офису.')}</div>`+section('Нужен ответ по вашей ситуации?',`<p class="campus-muted">Создайте диалог и продолжите его после ответа сотрудника.</p>${link('messages','Написать учебному офису')}`);}
  function settings(d){
    const p=d.preferences,student=c.state.user.role==='student';
    const themeMode=window.ATLASTheme.mode;
    const themes=[['light','Светлая'],['dark','Тёмная'],['system','Системная']];
    const appearance=`<fieldset class="theme-settings" aria-describedby="theme-hint">
      <legend>Тема оформления</legend>
      <div class="theme-choices">${themes.map(([value,label])=>`<label>
        <input type="radio" name="atlas-theme" value="${value}" data-theme-choice ${themeMode===value?'checked':''} />
        ${label}</label>`).join('')}</div>
      <p class="hint" id="theme-hint">Системная тема следует настройкам устройства. Выбор применяется сразу и сохраняется в этом браузере.</p>
    </fieldset>`;
    const toggles=[['compact_mode','Компактный вид']];
    if(student)toggles.push(['deadline_reminders','Напоминания о сроках'],['email_notifications','Почтовые уведомления (сохранить предпочтение)']);
    const form=`<form data-c-form="preferences"><div class="campus-checks">${toggles.map(([key,label])=>`<label><input name="${key}" type="checkbox" ${p[key]?'checked':''} />${esc(label)}</label>`).join('')}</div>
      ${student?info('Письма не отправляются. Уведомления по заявкам и сообщениям остаются в кабинете.'):''}
      <div class="inline-error" data-c-error role="alert" hidden></div>
      <div class="modal-actions"><button class="primary-button" type="submit">${icon('check')} Сохранить настройки</button></div>
    </form>`;
    const sessions=`<div class="campus-log">${items(d.sessions).map(x=>`<article><span class="campus-hub-icon">${icon('shield')}</span><div><b>${x.is_current?'Текущий сеанс':'Другой сеанс'} · № ${Number(x.id)}</b><p>Действует до ${c.stamp(x.expires_at)} МСК</p></div>${x.is_current?pill('Вы здесь','success'):''}</article>`).join('')}</div>${action('revoke-sessions','Завершить остальные сеансы')}`;
    return title('settings','Настройте вид кабинета и управляйте активными сеансами.')+section('Вид и уведомления',appearance+form)+section('Активные сеансы',sessions);
  }
  function staffdesk(d){
    const o=d.overview;const requestStats=o.requests||{};const openTickets=typeof o.tickets==='number'?o.tickets:o.tickets?.open??o.open_tickets??0;
    return title('staffdesk','Сопровождение учебной жизни: сводка, запись на консультации, события и объявления.')+stats([[Number(requestStats.submitted||0)+Number(requestStats.review||0)+Number(requestStats.processing||0)+Number(requestStats.needs_info||0),'заявок в работе'],[openTickets,'открытых диалогов'],[d.slots.total??items(d.slots).length,'слотов консультаций']])+`<div class="campus-button-row campus-spaced">${link('staff','Очередь заявлений')}${link('staffmessages','Ответить на вопросы')}${link('schedule-changes','Согласование расписания')}${link('work-notices','Рабочие уведомления')}${link('materials-admin','Публикации')}${link('university','Университет')}${primary('staff-slot','Создать консультацию')}${primary('staff-event','Новое мероприятие')}${link('announcement-admin','Управление объявлениями')}</div>`+section('Опубликованные консультации',items(d.slots).length?`<div class="campus-log">${items(d.slots).map(x=>`<article><span class="campus-hub-icon">${icon('calendar')}</span><div><b>${esc(x.subject)}</b><p>${esc(x.teacher)} · ${c.stamp(x.start_at)} МСК · ${esc(x.room)}</p></div>${pill(`${x.booked_count??0} / ${x.capacity} мест`)}</article>`).join('')}</div>`:c.empty('calendar','Слотов пока нет','Создайте первую консультацию.'))+pager(d.slots,'staffslots','Опубликованные консультации')+info('Пульт не открывает личные оценки, расписание или финансы студентов. Сотрудник видит только данные, необходимые для обращений и услуг.');
  }
  const renders={assignments,exams,consultations,messages:d=>messages(d),staffmessages:d=>messages(d,true),events,finance,contacts,knowledge,settings,staffdesk};

  async function detailLoading(heading,loader){
    c.modal(c.modalHead(heading,'Загружаем…')+'<p role="status">Загружаем данные…</p>',{wide:true,label:heading});const modalId=c.state.modalId;
    try{const html=await loader(modalId);if(modalId===c.state.modalId)c.modal(html,{wide:true,label:heading});}catch(error){if(!error.stale&&modalId===c.state.modalId)c.modal(c.modalHead(heading,'Не удалось открыть')+`<p role="alert">${esc(error.message)}</p>`,{label:heading});}
  }
  function workAttachments(id,files){
    return files.length?`<ul class="assignment-files">${files.map(file=>`<li><a download href="/api/learning/assignments/${Number(id)}/files/${Number(file.id)}">${esc(file.name)}</a><small>${Math.ceil(file.size/1024)} КБ</small></li>`).join('')}</ul>`:'';
  }
  function workNote(entry){
    return `<li><b>${esc(entry.author)} · версия ${Number(entry.version)}${entry.score===null?'':' · '+Number(entry.score)+' баллов'}</b>
      <small>${c.stamp(entry.created_at)} МСК</small>${entry.comment?paragraph(entry.comment):''}</li>`;
  }
  async function assignmentModal(id){
    const epoch=c.state.sessionEpoch,page=c.state.page,modalId=c.state.modalId;
    try{
      const x=await c.api('learning/assignments/'+Number(id));
      if(epoch!==c.state.sessionEpoch||page!==c.state.page||modalId!==c.state.modalId)return;
      const expiring=Date.parse(x.due_at)-Date.now();
      const dueLabel=x.due_at?c.stamp(x.due_at)+' МСК':c.dateFmt(x.due_date);
      const actions=x.can_withdraw?action('withdraw','Отозвать работу',x.id):'';
      const revise=x.feedback.find(f=>f.action==='revise');
      const visibleFeedback=x.feedback.filter(f=>f.comment||f.score!==null);
      const feedback=visibleFeedback.length?fold('Обратная связь преподавателя',
        `<ol class="op-log">${visibleFeedback.map(workNote).join('')}</ol>`):'';
      const versions=x.attempts.length?fold('История версий',x.attempts.map(attempt=>`<details class="assignment-attempt">
        <summary>Попытка ${Number(attempt.number)} · ${c.stamp(attempt.submitted_at)} МСК${attempt.late?' · сдано с опозданием':''}</summary>
        ${attempt.text?paragraph(attempt.text):''}${external(attempt.url,'Открыть работу')}${attempt.completed?paragraph('Отмечено выполнение'):''}
        ${workAttachments(x.id,attempt.files)}${attempt.feedback.length?`<p>${attempt.feedback.map(entry=>esc(entry.action==='accept'?'Принято':entry.action==='revise'?'Возвращено на доработку':entry.action==='complete'?'Завершено':entry.action==='review'?'Взято на проверку':'Есть комментарий')).join(' · ')}</p>`:''}</details>`).join('')):'';
      const start=x.can_submit&&x.status==='not_started'?action('assignment-start','Отметить начало работы',x.id):'';
      const deadlineId=Number(x.deadline_id||x.id),pending=c.pendingDeadline(deadlineId);
      const content=`<p class="campus-muted">${esc(x.subject)} · до ${esc(dueLabel)}</p>
        <p>${pill(x.state==='archived'?'В архиве':workStatuses[x.status],x.overdue?'warning':'')}
        ${x.max_points!==null?pill('Максимум '+x.max_points+' баллов'):''}
        ${x.overdue?pill(x.allow_late?'Просрочено · поздняя сдача открыта':'Срок сдачи истёк','warning'):expiring>=0&&expiring<86400000?pill('Срок истекает сегодня','warning'):''}</p>
        ${x.description?paragraph(x.description):''}${paragraph(x.instructions)}
        ${x.criteria?fold('Критерии оценивания',paragraph(x.criteria)):''}
        ${x.course_materials?.length?fold('Материалы дисциплины',x.course_materials.map(row=>
          `<p><a class="school-card-link" data-app-link href="${esc(row.href)}">${esc(row.title)}</a></p>`).join('')):''}
        ${x.materials.length?fold('Дополнительные материалы',x.materials.map((href,i)=>external(href,'Материал '+(i+1))).join('')):''}
        ${x.is_team?paragraph(x.team_lead?'Ответственный за общую отправку: '+x.team_lead:'Ответственный за отправку недоступен'):''}
        ${x.status==='revision_required'&&revise?info('Нужно исправить: '+revise.comment):''}
        <div class="campus-task-state"><p><label><input type="checkbox" data-deadline="${deadlineId}" ${(pending?.done??x.is_done)?'checked':''} ${pending?'disabled':''} /> Я выполнил(а) это задание</label></p>
        <div class="campus-button-row">${contextLink('courses','Материалы по предмету',{subject:x.subject})}${contextLink('consultations','Подготовиться на консультации',{subject:x.subject})}</div></div>`;
      if(!x.can_submit){
        c.modal(c.modalHead('Сдать работу',x.title)+content+actions+feedback+versions,{label:'Сдать работу',wide:true});
        return;
      }
      const methods=x.methods, files=methods.includes('files')?`<div class="field"><label for="campus-assignment-files">Файлы работы</label>
        <input id="campus-assignment-files" name="files" type="file" multiple accept="${esc(x.formats.map(ext=>'.'+ext).join(','))}">
        <span class="hint">До трёх файлов, 1 МиБ суммарно. Выбранные файлы сохраняются при отправке.</span></div>`:'';
      const completed=methods.includes('complete')?'<label class="campus-module-check"><input name="completed" type="checkbox"> Работа выполнена</label>':'';
      const inputs=`<input type="hidden" name="version" value="${Number(x.submission?.version||0)}">`+
        (methods.includes('text')?field('text','Текст ответа',x.status==='withdrawn'?x.submission.text:'',{rows:4,minlength:10,maxlength:8000}):'')+
        (methods.includes('url')?field('url','HTTPS-ссылка на работу',x.status==='withdrawn'?x.submission.url:'',{type:'url',maxlength:500}):'')+files+completed;
      const label=x.attempts.length?'Отправить новую версию':'Отправить работу';
      formModal('assignment','Сдать работу',x.title,start+inputs,{id:x.id,submit:label,wide:true,before:content,after:feedback+versions});
    }catch(error){if(!error.stale&&epoch===c.state.sessionEpoch&&page===c.state.page)c.toast(error.message);}
  }
  async function encodeWorkFiles(input){
    const files=Array.from(input?.files||[]);
    if(files.length>3||files.reduce((total,file)=>total+file.size,0)>1024*1024||files.some(file=>!file.size))
      throw new Error('Можно приложить до трёх непустых файлов размером не более 1 МиБ суммарно.');
    return Promise.all(files.map(async file=>{
      const bytes=new Uint8Array(await file.arrayBuffer());
      let binary='';
      for(let offset=0;offset<bytes.length;offset+=8192)binary+=String.fromCharCode(...bytes.subarray(offset,offset+8192));
      return {name:file.name,content:btoa(binary)};
    }));
  }
  async function ticketModal(id){
    const staff=c.state.user.role==='staff';const prefix=staff?'staff':'services';
    await detailLoading('Диалог с учебным офисом',async()=>{
      const query=new URLSearchParams({message_limit:'40'});if(Number.isInteger(local.ticketOffsets[id]))query.set('message_offset',String(local.ticketOffsets[id]));const x=await c.api(`${prefix}/tickets/${id}?${query}`);
      return c.modalHead(x.title,`Обращение № ${x.id} · ${x.status==='closed'?'закрыто':'открыто'}`)+(staff?`<p>${esc(x.student_name||'Студент')} · ${esc(x.group||'')}</p>`:'')+`<ol class="campus-conversation">${x.messages.map(m=>`<li class="${m.actor_role==='staff'?'staff':'student'}"><div><b>${esc(m.actor_name)}</b><time>${c.stamp(m.created_at)} МСК</time></div>${paragraph(m.body)}</li>`).join('')}</ol>`+(x.messages_total>x.messages_limit?`<nav class="campus-pagination" aria-label="Страницы сообщений"><span role="status">${x.messages_offset+1}–${Math.min(x.messages_offset+x.messages.length,x.messages_total)} из ${x.messages_total}</span><div>${action('ticket-messages-page','Ранее',id,`data-offset="${Math.max(0,x.messages_offset-x.messages_limit)}" ${x.messages_offset?'':'disabled'}`)}${action('ticket-messages-page','Позже',id,`data-offset="${x.messages_offset+x.messages_limit}" ${x.messages_has_more?'':'disabled'}`)}</div></nav>`:'')+(x.status!=='closed'?`<form data-c-form="ticket-reply" data-id="${x.id}">${field('message','Сообщение','',{rows:4,minlength:1,maxlength:3000,required:true})}<div class="inline-error" data-c-error role="alert" hidden></div><div class="modal-actions">${action('ticket-close','Закрыть диалог',x.id)}<button class="primary-button" type="submit">${icon('send')} Отправить</button></div></form>`:info('Обращение закрыто. История сохранена; новый вопрос можно задать в отдельном диалоге.'));
    });
  }
  function staffSlotModal(){const start=c.addDays(c.today(),2)+'T12:00';formModal('staff-slot','Новая консультация','Время вводится по Москве (UTC+3)',field('teacher','Преподаватель','',{required:true,minlength:2,maxlength:120})+field('subject','Дисциплина','',{required:true,minlength:3,maxlength:130})+field('start_at','Начало',start,{type:'datetime-local',required:true})+field('end_at','Окончание',start.replace('12:00','13:00'),{type:'datetime-local',required:true})+field('room','Аудитория / формат','А-301',{required:true,maxlength:80})+field('capacity','Число мест',5,{type:'number',min:1,max:100,required:true}));}
  function staffEventModal(){const start=c.addDays(c.today(),4)+'T16:00';formModal('staff-event','Новое мероприятие','Укажите время, место и условия записи',field('title','Название','',{required:true,minlength:5,maxlength:180})+field('category','Категория','academic',{choices:[['academic','Учёба'],['science','Наука'],['career','Карьера'],['sport','Спорт'],['community','Сообщество']]})+field('description','Описание','',{rows:5,minlength:10,maxlength:4000,required:true})+field('start_at','Начало (МСК)',start,{type:'datetime-local',required:true})+field('end_at','Окончание (МСК)',start.replace('16:00','17:00'),{type:'datetime-local',required:true})+field('location','Место','Актовый зал',{required:true,minlength:3,maxlength:150})+field('capacity','Число мест',30,{type:'number',min:1,max:500,required:true}));}
  function confirmMutation(name,id,text){if(!c.closeModal())return;const labels={withdraw:'Отозвать работу','ticket-close':'Закрыть диалог','revoke-sessions':'Завершить сеансы'};const label=labels[name]||'Подтвердить';c.modal(c.modalHead(label,text)+`<div class="modal-actions"><button class="muted-button" data-action="close-modal">Отмена</button>${action(name,label,id,'data-confirmed="true"')}</div>`,{label:'Подтверждение действия'});}
  async function mutate(path,body={},success='Сохранено',button=null){
    if(c.state.pending)return null;const epoch=c.state.sessionEpoch;const page=c.state.page;c.state.pending++;if(button)button.disabled=true;
    try{const pending=await pendingMutation(path,body);if(epoch!==c.state.sessionEpoch)return null;const result=await c.api(path,{method:'POST',body:JSON.stringify(body),headers:{'Idempotency-Key':pending.key}});pending.clear();c.state.pending=Math.max(0,c.state.pending-1);if(epoch!==c.state.sessionEpoch)return null;c.closeModal();if(page===c.state.page)await c.updatePage({quiet:true});if(epoch!==c.state.sessionEpoch||page!==c.state.page)return null;c.refreshUnread();c.toast(success);return result;}
    catch(error){if(!error.stale){c.state.pending=Math.max(0,c.state.pending-1);if(button?.isConnected)button.disabled=false;c.toast(error.message);}return null;}
  }
  async function handleAction(el){
    if(c.state.pending)return;const name=el.dataset.cAction;const id=Number(el.dataset.id);
    if(name==='service-page'){const key=el.dataset.pageKey;local.offset[key]=Math.max(0,Number(el.dataset.offset)||0);await refreshService();c.$('.page-heading h1,#page-title')?.focus({preventScroll:true});return;}
    if(name==='ticket-messages-page'){local.ticketOffsets[id]=Math.max(0,Number(el.dataset.offset)||0);return ticketModal(id);}
    if(name==='clear-context'){resetRouteContext(el.dataset.contextPage);c.replaceRouteContext();return c.updatePage();}
    if(name==='assignment')return assignmentModal(id);
    if(name==='assignment-start'){
      const result=await mutate(`learning/assignments/${id}/start`,{version:0},'Работа отмечена как начатая.',el);
      if(result&&c.state.page==='assignments')return assignmentModal(id);
      return;
    }
    if(name==='ticket-new')return formModal('ticket','Задать вопрос','Ответ сотрудника появится в этом диалоге',field('topic','Тема','academic',{choices:ticketTopics})+field('title','Короткий заголовок',local.context.messages?.subject?'Консультация: '+local.context.messages.subject:'',{required:true,minlength:5,maxlength:180})+field('message','Вопрос',local.context.messages?.subject?'Подскажите, пожалуйста, как подготовиться по дисциплине «'+local.context.messages.subject+'» и выбрать время консультации.':'',{rows:6,minlength:10,maxlength:4000,required:true}),{submit:'Отправить вопрос',wide:true});
    if(name==='ticket-open')return ticketModal(id);
    if(name==='staff-slot')return staffSlotModal();
    if(name==='staff-event')return staffEventModal();
    const mutations={withdraw:[`learning/assignments/${id}/withdraw`,'Работа отозвана. Можно отправить новую версию.'],'consultation-book':[`services/consultations/${id}/book`,'Запись на консультацию сохранена.'],'booking-cancel':[`services/bookings/${id}/cancel`,'Запись отменена.'],'event-register':[`services/events/${id}/register`,'Вы записаны на мероприятие.'],'event-cancel':[`services/registrations/${id}/cancel`,'Участие отменено.'],'ticket-close':[`${c.state.user.role==='staff'?'staff':'services'}/tickets/${id}/close`,'Диалог закрыт. История сохранена.'],'revoke-sessions':['account/sessions/revoke-others','Остальные сеансы завершены.']};
    if(mutations[name]){if(['withdraw','ticket-close','revoke-sessions'].includes(name)&&!el.dataset.confirmed)return confirmMutation(name,id,name==='revoke-sessions'?'Текущий сеанс продолжит работать. Остальные потребуют нового входа.':name==='withdraw'?'Текущая версия останется в кабинете; можно отправить работу снова.':'Переписка останется доступной, новые сообщения в этот диалог будут закрыты.');return mutate(mutations[name][0],{},mutations[name][1],el);}
  }
  async function submit(form){
    const name=form.dataset.cForm;if(c.state.pending)return;
    const epoch=c.state.sessionEpoch,uid=c.state.user?.id,page=c.state.page,modalId=c.state.modalId;
    const currentForm=()=>epoch===c.state.sessionEpoch&&uid===c.state.user?.id&&form.isConnected&&(name==='preferences'||modalId===c.state.modalId);
    let released=false;const release=()=>{if(released)return;released=true;if(epoch===c.state.sessionEpoch&&uid===c.state.user?.id)c.state.pending=Math.max(0,c.state.pending-1);};
    const controls=Array.from(form.elements),button=c.$('button[type=submit]',form),error=c.$('[data-c-error]',form);let validationFocus;error.hidden=true;c.state.pending++;controls.forEach(x=>x.disabled=true);button.textContent='Подготавливаем…';
    try{
      await c.prepareFormSubmission(form);if(!currentForm())return;
      const values=Object.fromEntries(controls.filter(x=>x.name&&!(['checkbox','radio'].includes(x.type)&&!x.checked)).map(x=>[x.name,x.value]));
      const id=Number(form.dataset.id);let path,body,success='Сохранено';
    if(name==='assignment'){
      path=`learning/assignments/${id}/submit`;
      const files=await encodeWorkFiles(form.elements.files);if(!currentForm())return;
      body={text:(values.text||'').trim(),url:(values.url||'').trim(),version:Number(values.version),completed:values.completed==='on',files};
      success='Версия работы отправлена.';
    }
    if(name==='ticket'){path='services/tickets';body={topic:values.topic,title:values.title.trim(),message:values.message.trim()};success='Вопрос сохранён. Следите за ответом в диалоге.';}
    if(name==='ticket-reply'){path=`${c.state.user.role==='staff'?'staff':'services'}/tickets/${id}/messages`;body={message:values.message.trim()};success='Сообщение отправлено.';}
    if(name==='preferences'){
      path='services/preferences';body={compact_mode:values.compact_mode==='on'};
      if(c.state.user.role==='student')Object.assign(body,{email_notifications:values.email_notifications==='on',deadline_reminders:values.deadline_reminders==='on'});
    }
    if(name==='staff-slot'){path='staff/consultations';body={...values,start_at:values.start_at+':00+03:00',end_at:values.end_at+':00+03:00',capacity:Number(values.capacity)};success='Консультация опубликована студентам.';}
    if(name==='staff-event'){path='staff/events';body={...values,start_at:values.start_at+':00+03:00',end_at:values.end_at+':00+03:00',capacity:Number(values.capacity)};success='Мероприятие опубликовано в кампусе.';}
      if(!path)return;
      const pendingKey=await c.formSubmission(form,body);if(!currentForm())return;button.textContent='Сохраняем…';
      const headers={'Idempotency-Key':pendingKey};
      const result=await c.api(path,{method:'POST',body:JSON.stringify(body),headers});if(!currentForm())return;
      form.dataset.dirty='false';try{await c.clearFormDraft(form);}catch(e){if(!e.stale)c.toast('Запись сохранена. Очистить черновик пока не удалось.');}if(!currentForm())return;
      if(name==='ticket-reply')delete local.ticketOffsets[id];release();c.closeModal();if(page===c.state.page)await c.updatePage({quiet:true});if(epoch!==c.state.sessionEpoch||page!==c.state.page)return;c.refreshUnread();
      if(name==='ticket-reply')await ticketModal(id);
      if(name==='preferences')document.body.classList.toggle('compact-campus',body.compact_mode);c.toast(success);
    }catch(e){if(!e.stale&&currentForm()){error.hidden=false;error.textContent=e.message;button.textContent='Повторить сохранение';validationFocus=c.showFieldErrors?.(e,form);}}
    finally{release();if(form._atlasDraft)form._atlasDraft.submitting=false;if(currentForm()){controls.forEach(x=>x.disabled=false);if(validationFocus?.isConnected&&!validationFocus.disabled)validationFocus.focus();}}
  }
  function afterRender(page){if(page==='settings'&&current()?.preferences)document.body.classList.toggle('compact-campus',!!current().preferences.compact_mode);}
  function clearFilters(page){clearTimeout(serviceSearchTimer);local.query[page]='';local.filter[page]='all';local.offset[page]=0;delete local.context[page];}
  function resetRouteContext(page){
    if(!Object.hasOwn(local.context,page))return;
    if(local.query[page]===local.context[page].subject?.slice(0,100))local.query[page]='';
    delete local.context[page];local.offset[page]=0;
  }
  async function prepare(){
    document.body.classList.remove('compact-campus');
    const epoch=c.state.sessionEpoch;
    try{const p=await c.api('services/preferences');if(epoch===c.state.sessionEpoch)document.body.classList.toggle('compact-campus',!!p.compact_mode);}catch{/* A preference failure must not prevent entry to the cabinet. */}
  }
  function init(context){
    c=context;
    document.addEventListener('submit',e=>{const form=e.target.closest('[data-c-form]');if(!form||form.matches('[data-announcement-editor]'))return;e.preventDefault();submit(form);});
    document.addEventListener('click',e=>{
      const el=e.target.closest('[data-c-action]');if(el){e.preventDefault();handleAction(el).catch(error=>{if(!error.stale)c.toast(error.message);});return;}
      const scope=e.target.closest('[data-c-scope]');if(scope){const page=scope.dataset.cScope;clearTimeout(serviceSearchTimer);local.scope[page]=scope.dataset.value;resetRouteContext(page);local.offset[page]=0;c.replaceRouteContext();refreshService().catch(error=>{if(!error.stale)c.toast(error.message);});return;}
      const filter=e.target.closest('[data-c-filter]');if(filter){const page=filter.dataset.cFilter;local.filter[page]=filter.dataset.value;if(servicePages.has(page)){clearTimeout(serviceSearchTimer);resetRouteContext(page);local.offset[page]=0;c.replaceRouteContext();refreshService().catch(error=>{if(!error.stale)c.toast(error.message);});}else{c.drawPage();c.$(`[data-c-filter="${page}"][data-value="${filter.dataset.value}"]`)?.focus({preventScroll:true});}return;}
      const catalog=e.target.closest('[data-catalog-category]');if(catalog){local.catalog=catalog.dataset.catalogCategory;c.drawPage();c.$(`[data-catalog-category="${local.catalog}"]`)?.focus({preventScroll:true});}
    });
    document.addEventListener('input',e=>{
      if(e.target.dataset.cQuery){const page=e.target.dataset.cQuery;resetRouteContext(page);c.replaceRouteContext();local.query[page]=e.target.value;if(servicePages.has(page)){local.offset[page]=0;c.state.loadingId++;clearTimeout(serviceSearchTimer);const position=e.target.selectionStart;const epoch=c.state.sessionEpoch;serviceSearchTimer=setTimeout(()=>{if(page===c.state.page&&epoch===c.state.sessionEpoch)refreshService(position).catch(error=>{if(!error.stale)c.toast(error.message);});},c.searchDelay);}else refreshPreservingInput();}
    });
  }
  function reset(){clearTimeout(serviceSearchTimer);local.query={};local.filter={assignments:'pending'};local.offset={};local.scope={};local.context={};local.ticketOffsets={};local.pendingKeys={};local.catalog='documents';document.body.classList.remove('compact-campus');}
  const catalogOptions=[['documents','Справки'],['academic','Учёба'],['finance','Финансы'],['campus','Кампус'],['other','Другое'],['all','Все услуги']];
  window.ATLASCampus={pages,has:page=>Object.hasOwn(renders,page),init,prepare,prepareRoute,openContext,clearFilters,resetRouteContext,load,render:(page,d)=>renders[page](d),afterRender,reset,catalogFilter:()=>`<div class="campus-catalog-head"><h2>Каталог услуг</h2><div class="filter-tabs" aria-label="Категория услуги">${catalogOptions.map(([key,label])=>`<button data-catalog-category="${key}" aria-pressed="${key===local.catalog}">${label}</button>`).join('')}</div></div>`,catalogTypes:types=>local.catalog==='all'?types:types.filter(t=>(t.category||'documents')===local.catalog)};
})();
