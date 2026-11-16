/* Academic workspace and campus operations. */
(() => {
  'use strict';
  const offices=['scheduler','staff','admin'];
  const workers=[...offices,'teacher'];
  const pages=[
    {id:'teaching',label:'Группы и дисциплины',icon:'graduation',hint:'Списки, оценки, посещаемость, задания и отчёт',roles:['teacher']},
    {id:'teach-schedule',label:'Мои занятия',icon:'calendar',hint:'Расписание преподавателя по неделям',roles:['teacher']},
    {id:'teach-consultations',label:'Мои консультации',icon:'clock',hint:'Время приёма и записи студентов',roles:['teacher']},
    {id:'timetable-admin',label:'Расписание занятий',icon:'calendar',hint:'Опубликованные занятия и проекты переноса',roles:offices},
    {id:'schedule-changes',label:'Проекты расписания',icon:'plan',hint:'Подготовка, согласование и утверждение',roles:offices},
    {id:'academic-calendar',label:'Учебный календарь',icon:'calendar',hint:'Семестры, исключения и подгруппы',roles:offices},
    {id:'registry',label:'Аудитории и группы',icon:'pin',hint:'Аудиторный фонд, группы, нагрузка и состав',roles:offices},
    {id:'tables',label:'Импорт и экспорт',icon:'file',hint:'CSV, XLSX, шаблоны, просмотр и журнал',roles:workers},
  ];
  const stateNames={draft:'Черновик',submitted:'На согласовании',agreed:'Согласован',returned:'Возвращён',published:'Опубликован'};
  const actionNames={create:'Новое событие',update:'Изменение занятия',cancel:'Отмена занятия',restore:'Восстановление занятия'};
  const kindNames={lecture:'Лекция',practice:'Практическое занятие',lab:'Лабораторная работа',consultation:'Консультация',
    credit:'Зачёт',exam:'Экзамен',retake:'Пересдача',organization:'Организационное мероприятие',other:'Учебное мероприятие'};
  const periodNames={teaching:'Учебные недели',credit:'Зачётная неделя',exam:'Экзаменационная сессия',break:'Межсеместровые каникулы'};
  const ruleNames={holiday:'Государственный праздник',off:'Выходной',working:'Учебный день',summer:'Летние каникулы',
    break:'Межсеместровые каникулы',legacy:'Демонстрационный период'};
  const attendanceNames={present:'Присутствовал',absent:'Отсутствовал',excused:'Уважительная причина',late:'Опоздал'};
  const teachTabs={roster:'Студенты',grades:'Ведомость',attendance:'Посещаемость',works:'Сдача работ',report:'Отчёт и история'};
  const registryTabs={rooms:'Аудитории',groups:'Группы',loads:'Нагрузка',students:'Состав групп'};
  const datasetIds=['schedule','rooms','groups','loads','students','grades','attendance'];
  const columnLabels={
    id:'ID записи',version:'Версия',building:'Корпус',code:'Код',capacity:'Мест',kind:'Тип',equipment:'Оборудование',
    accessible:'Безбарьерный доступ',available:'Доступна',program:'Программа',group_id:'ID группы',assignment_id:'ID назначения',
    student_id:'ID студента',load_id:'ID нагрузки',teacher_id:'ID преподавателя',room_id:'ID аудитории',day:'Дата',
    start:'Начало',end:'Окончание',weeks:'Число повторений',interval:'Интервал в неделях',subgroup_id:'ID подгруппы',
    title:'Название события',calendar_exception:'Основание исключения',note:'Комментарий',status:'Отметка',score:'Итоговые баллы',reason:'Основание',class_id:'Занятие',
  };
  const callbacks=new WeakMap();
  const retries=new Map();
  let c, upload;
  const esc=x=>c.esc(x);
  const icon=x=>c.icon(x);
  const role=()=>c.state.user.role;
  const current=()=>c.state.data[c.state.page];
  const q=()=>c.state.routeContext;
  const has=page=>pages.some(p=>p.id===page);
  const int=x=>/^[1-9]\d{0,9}$/.test(x)&&Number(x)<=2147483647;
  const validDay=x=>typeof x==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(x)&&Number.isFinite(+c.asDate(x));
  const url=(base,query={})=>{
    const params=new URLSearchParams(Object.entries(query).filter(([,value])=>value!==undefined&&value!==null&&value!=='')).toString();
    return base+(params?'?'+params:'');
  };
  const link=(href,label,cls='mini-link')=>`<a class="${cls}" href="${esc(href)}" data-app-link>${esc(label)}</a>`;
  const button=(action,label,id='',extra='')=>`<button type="button" class="outline-button" data-op-action="${action}" data-id="${esc(id)}" ${extra}>${esc(label)}</button>`;
  const download=(href,label)=>`<a class="outline-button" href="${esc(href)}" download>${icon('download')} ${esc(label)}</a>`;
  const title=(name,desc='',actions='')=>c.head('',esc(name),esc(desc),actions);
  const section=(heading,html)=>`<section class="card card-pad op-section"><h2 class="card-title">${esc(heading)}</h2>${html}</section>`;
  const empty=(name,text)=>c.empty('file',name,text);
  const field=(name,label,control)=>`<div class="field"><label for="op-${name}">${esc(label)}</label>${control}</div>`;
  const input=(name,label,value='',type='text',attributes='')=>field(name,label,`<input id="op-${name}" name="${name}" type="${type}" value="${esc(value)}" ${attributes}>`);
  const area=(name,label,value='',max=300)=>field(name,label,`<textarea id="op-${name}" name="${name}" rows="3" maxlength="${max}">${esc(value)}</textarea>`);
  const select=(name,label,choices,value='',attributes='')=>field(name,label,`<select id="op-${name}" name="${name}" ${attributes}>${choices.map(([key,text])=>`<option value="${esc(key)}" ${String(key)===String(value)?'selected':''}>${esc(text)}</option>`).join('')}</select>`);
  const yesNo=(name,label,value)=>select(name,label,[[false,'Нет'],[true,'Да']],value??false);
  const numbers=(data,...keys)=>{for(const key of keys)data[key]=Number(data[key]);return data;};
  const msk=value=>value+(value.length===16?':00+03:00':'+03:00');

  function validParts(page,parts){
    return (['teaching','schedule-changes','registry'].includes(page)&&parts.length===1&&int(parts[0]))
      ||(page==='teaching'&&parts.length===3&&int(parts[0])&&parts[1]==='works'&&int(parts[2]));
  }

  function cleanQuery(page,query,parts){
    if(page==='academic-calendar')return /^(20\d\d)$/.test(query.year||'')?{year:Number(query.year)}:{};
    if(['timetable-admin','teach-schedule','registry'].includes(page)&&validDay(query.week))return {week:query.week};
    if(page==='registry'&&!parts.length&&Object.hasOwn(registryTabs,query.tab)&&!(query.tab==='students'&&role()!=='admin'))return {tab:query.tab};
    if(page==='teaching'&&parts.length===3)return {
      ...(Object.hasOwn(submissionStates,query.status)?{status:query.status}:{}),
      ...(int(query.student)?{student:Number(query.student)}:{}),
      ...(['late','on-time'].includes(query.timing)?{timing:query.timing}:{})};
    if(page==='teaching'&&parts.length===1){
      return {...(Object.hasOwn(teachTabs,query.tab)?{tab:query.tab}:{}),
              ...(validDay(query.day)?{day:query.day}:{}),...(int(query.class_id)?{class_id:Number(query.class_id)}:{}),
              ...(int(query.offset)?{offset:Number(query.offset)}:{})};
    }
    if(page==='schedule-changes'&&int(query.offset))return {offset:Number(query.offset)};
    if(page==='tables'){
      return {...(datasetIds.includes(query.dataset)?{dataset:query.dataset}:{}),
              ...(int(query.scope)?{scope:Number(query.scope)}:{}),...(validDay(query.day)?{day:query.day}:{}),
              ...(query.dataset==='attendance'&&int(query.class_id)?{class_id:Number(query.class_id)}:{})};
    }
    return {};
  }

  async function load(page,parts,query){
    if(page==='academic-calendar')return c.api('scheduling/calendar?year='+(query.year||c.today().slice(0,4)));
    if(page==='teach-schedule')return c.api(url('teaching/schedule',query));
    if(page==='teach-consultations'){
      const [data,loads]=await Promise.all([c.api('teaching/consultations'),c.api('teaching')]);
      return {...data,loads:loads.items};
    }
    if(page==='timetable-admin'){
      const [data,options]=await Promise.all([c.api(url('scheduling',query)),c.api('scheduling/options')]);
      return {...data,options};
    }
    if(page==='schedule-changes'){
      if(!parts.length)return c.api(url('scheduling/changes',query));
      const [data,options]=await Promise.all([c.api('scheduling/changes/'+parts[0]),c.api('scheduling/options')]);
      return {...data,title:'Проект №'+data.id,options};
    }
    if(page==='registry')return c.api(parts.length?url('scheduling/rooms/'+parts[0],query):'registry');
    if(page==='tables'){
      const [data,history,loads]=await Promise.all([c.api('tables'),c.api('tables/history'),role()==='teacher'?c.api('teaching'):null]);
      return {...data,history:history.items,loads:loads?.items||[]};
    }
    if(!parts.length)return c.api('teaching');
    const id=parts[0], base='teaching/'+id;
    const detail=await c.api(url(base,{day:query.day,class_id:query.class_id}));
    const parent={title:detail.discipline+' · '+detail.group,href:'/app/teaching/'+id};
    if(parts.length===3){
      const work=await c.api(base+'/works/'+parts[2]);
      return {detail,work,title:work.title,parents:[parent]};
    }
    const works=query.tab==='works'?await c.api(url(base+'/works',{offset:query.offset})):null;
    return {...detail,title:parent.title,works};
  }

  function list(rows,make,heading='Пока пусто',description='Здесь появятся записи по мере работы.'){
    return rows.length?`<div class="compact-list">${rows.map(make).join('')}</div>`:empty(heading,description);
  }

  function row(heading,summary='',actions='',className=''){
    return `<article class="card compact-row op-row ${className}"><div class="row-copy"><h3>${heading}</h3>${summary}</div>${actions?`<div class="op-actions">${actions}</div>`:''}</article>`;
  }

  const p=value=>value?`<p>${esc(value)}</p>`:'';
  function tabs(label,options,active,href){
    return `<nav class="op-tabs" aria-label="${esc(label)}">${Object.entries(options).map(([key,name])=>key===active?
      `<span aria-current="page">${esc(name)}</span>`:link(href(key),name)).join('')}</nav>`;
  }

  function pageLinks(base,data,size){
    if(!data.offset&&!data.more)return '';
    const href=offset=>url(base,{...q(),offset:offset||undefined});
    return `<nav class="op-actions" aria-label="Страницы">${data.offset?link(href(Math.max(0,data.offset-size)),'Предыдущая','outline-button'):''}${data.more?link(href(data.offset+size),'Следующая','outline-button'):''}</nav>`;
  }

  function dateForm(name,label,value){
    return `<form class="filter-bar op-inline-form" data-op-filter="${name}">${input('filter-day',label,value,'date','required')}<button class="outline-button" type="submit">Показать</button></form>`;
  }

  function teachingSessionPicker(data,selected){
    const sessions=data.sessions.filter(item=>item.started||item.id===data.class_id);
    return sessions.length?`<form class="filter-bar op-inline-form" data-op-filter="teaching-session" data-tab="${selected}">
      ${select('class_id','Занятие',[['','Без привязки к занятию'],...sessions.map(item=>[item.id,
        `${c.stamp(item.starts_at)} · ${item.kind}${item.topic?' · '+item.topic:''}`])],data.class_id||'')}
      <button class="outline-button" type="submit">Открыть</button></form>`:'';
  }

  const workStates={draft:'Черновик',scheduled:'Запланировано',published:'Опубликовано',closed:'Приём закрыт',archived:'В архиве'};
  const submissionStates={not_started:'Не сдано',submitted:'Сдано',resubmitted:'Повторно сдано',in_review:'На проверке',
    revision_required:'Требует доработки',accepted:'Принято',graded:'Оценено',completed:'Проверка завершена',withdrawn:'Отозвано'};
  const workKinds={homework:'Домашняя работа',lab:'Лабораторная работа',practice:'Практическая работа',test:'Контрольная работа',
    independent:'Самостоятельная работа',essay:'Реферат',talk:'Доклад',project:'Проектная работа',term_paper:'Курсовая работа',
    individual:'Индивидуальная работа',group:'Групповая работа',other:'Другой тип'};
  const handInMethods={text:'Текстовый ответ',url:'HTTPS-ссылка',files:'Файлы',complete:'Отметка о выполнении'};
  const acceptedFormats=['pdf','txt','md','csv','png','jpg','jpeg','docx','xlsx','pptx'];
  const reviewActions={review:'Взять на проверку',revise:'Вернуть на доработку',accept:'Принять работу',complete:'Завершить проверку',
    comment:'Дать обратную связь',grade:'Оценить работу',correct_score:'Скорректировать балл'};
  const reviewEvents={review:'Взято на проверку',revise:'Возвращено на доработку',accept:'Работа принята',complete:'Проверка завершена',
    comment:'Обратная связь',grade:'Работа оценена',correct_score:'Балл скорректирован'};
  const awaitingReview=new Set(['submitted','resubmitted','in_review']);
  const checkedStates=new Set(['accepted','completed']);
  const deadlineLabel=value=>value?c.stamp(value)+' МСК':'—';
  const submissionState=item=>item?.score!=null?'graded':item?.status==='in_progress'?'not_started':item?.status||'not_started';
  const workType=work=>work.custom_kind||workKinds[work.kind];
  const userText=value=>value?`<p class="user-text">${esc(value)}</p>`:'';
  const fileList=(files,path)=>files?.length?`<ul class="assignment-files">${files.map(file=>
    `<li>${download(path+'/'+Number(file.id),file.name)}<small>${Math.ceil(file.size/1024)} КБ</small></li>`).join('')}</ul>`:'';

  function reviewHistory(entries,path){
    return entries.length?`<ul class="op-log work-review-log">${entries.map(entry=>`<li>
      <b>${esc(reviewEvents[entry.action]||'Обратная связь')}${entry.score==null?'':
        ` · ${entry.previous_score==null?'':Number(entry.previous_score)+' → '}${Number(entry.score)} баллов`}</b>
      <small>${esc(entry.author)} · ${esc(deadlineLabel(entry.created_at))}</small>
      ${userText(entry.comment)}${entry.remarks?`<p class="user-text"><b>Замечания.</b> ${esc(entry.remarks)}</p>`:''}
      ${entry.extended_until?p('Срок доработки '+deadlineLabel(entry.extended_until)):''}
      ${fileList(entry.files,path+'/feedback-files')}</li>`).join('')}</ul>`:'';
  }

  function attemptBody(attempt,path){
    return userText(attempt.text)+safeReference(attempt.url)+(attempt.completed?p('Отмечено выполнение'):'')+
      fileList(attempt.files,path+'/files');
  }

  function attemptLabel(attempt){
    return `Попытка ${Number(attempt.number)} · ${deadlineLabel(attempt.submitted_at)}${attempt.late?' · сдано с опозданием':''}`;
  }

  function workReviewRow(item,work,scope){
    const latest=item.attempts[0], withdrawn=item.status==='withdrawn';
    const accepted=checkedStates.has(item.status), reviewOpen=['published','closed'].includes(work.state);
    const path=scope+'/submissions/'+Number(item.id);
    const older=withdrawn?item.attempts:item.attempts.slice(1);
    const history=older.length?`<details class="assignment-attempt"><summary>История версий</summary>${older.map(attempt=>
      `<details class="assignment-attempt"><summary>${esc(attemptLabel(attempt))}</summary>
      ${attemptBody(attempt,path)}${reviewHistory(attempt.feedback,path)}</details>`).join('')}</details>`:'';
    let actions='';
    if(reviewOpen&&awaitingReview.has(item.status)){
      if(item.status!=='in_review')actions+=button('review-work',reviewActions.review,item.id);
      if(work.state==='published')actions+=button('revise-work',reviewActions.revise,item.id);
      actions+=button('accept-work',reviewActions.accept,item.id)+button('feedback',reviewActions.comment,item.id);
    }
    if(reviewOpen&&accepted){
      if(item.score==null)actions+=button('grade-work',reviewActions.grade,item.id);
      if(item.status==='accepted')actions+=button('complete-work',reviewActions.complete,item.id);
      actions+=button('feedback',reviewActions.comment,item.id);
    }
    if(accepted&&item.score!=null)actions+=button('correct-score',reviewActions.correct_score,item.id);
    if(item.attempts.length>1)actions+=button('compare-work','Сравнить версии',item.id);
    const notes=item.feedback.filter(entry=>
      !item.attempts.some(attempt=>attempt.version===entry.version)||(!withdrawn&&entry.version===latest?.version));
    const score=item.score==null?'':`${Number(item.score)} из ${work.max_points} баллов`;
    return row(esc(item.student),p([submissionStates[submissionState(item)],score,item.status==='completed'&&score?'Проверка завершена':'',
      latest?attemptLabel(latest):''].filter(Boolean).join(' · '))+
      (!withdrawn&&latest?attemptBody(latest,path):'')+reviewHistory(notes,path)+history,actions,'work-review-row');
  }

  function workRecipientRow(person,work,item,team){
    const state=submissionState(item), lateStates=['not_started','withdrawn','revision_required'];
    const timing=person.deadline_passed&&lateStates.includes(state)&&work.state==='published'?
      p(person.submission_window==='late'?'Просрочено · поздняя сдача разрешена':'Просрочено · приём закрыт'):'';
    const dueTitle=person.revision_due_at?'Срок доработки':person.extended_until?'Продлённый срок':
      person.individual_due_at?'Индивидуальный срок':'Срок сдачи';
    const allowChange=work.state==='published'&&(!team||person.id===team.id);
    return row(esc(person.name),p([person.id===work.team_lead_id?'Ответственный':'',submissionStates[state],
      dueTitle+' '+deadlineLabel(person.due_at)].filter(Boolean).join(' · '))+timing,
      allowChange?button('individual-due','Индивидуальный срок',person.id)+button('extend-work','Продлить срок',person.id):'');
  }

  function workDetails(data){
    const {work,detail}=data, base='/app/teaching/'+detail.id;
    const scope='/api/teaching/'+detail.id+'/works/'+work.id;
    const actions=(['draft','scheduled','published'].includes(work.state)?button('edit-work','Изменить задание'):'')+
      (work.state==='published'?button('close-work','Закрыть приём'):'')+
      (['published','closed'].includes(work.state)?button('archive-work','В архив'):'')+link(base+'?tab=works','К сдаче работ','outline-button');
    const methods=work.methods.map(key=>handInMethods[key]);
    const required=(work.required_methods||[]).map(key=>handInMethods[key]);
    const audience=work.subgroup_id?(detail.subgroups||[]).find(group=>group.id===work.subgroup_id)?.code||'Подгруппа':
      work.recipient_ids?.length?'Отдельные студенты':'Вся группа';
    const summary=p([workType(work),work.max_points+' баллов максимум',audience].join(' · '))+
      (work.state==='scheduled'?p('Публикация '+deadlineLabel(work.publish_at)):'')+
      userText(work.description)+userText(work.instructions)+
      (work.criteria?`<details class="assignment-attempt"><summary>Критерии оценивания</summary>${userText(work.criteria)}</details>`:'')+
      p('Способы сдачи · '+methods.join(', '))+(required.length?p('Обязательные · '+required.join(', ')):'')+
      (work.allow_late?p('Поздняя сдача разрешена'):'')+
      (work.source_files?.length?`<h3 class="work-attachment-heading">Исходные файлы</h3>${fileList(work.source_files,scope+'/source-files')}`:'')+
      work.materials.map(value=>`<div>${safeReference(value,'Открыть материал')}</div>`).join('')+
      (work.course_materials||[]).map(row=>`<div>${link(window.ATLASDisciplines.materialPath(row.id),row.title,'school-card-link')}</div>`).join('');
    const viewers=Object.fromEntries(work.submissions.map(item=>[item.student_id,item]));
    const team=work.team_lead_id&&work.recipients.find(x=>x.id===work.team_lead_id);
    const recipientRows=list(work.recipients,person=>workRecipientRow(person,work,viewers[team?.id||person.id],team),
      'Получатели появятся после назначения','Укажите студентов в условиях задания.');
    const sent=work.submissions.filter(item=>item.attempts.length), filter=q(),filtered=sent.filter(item=>
      (!filter.status||filter.status===submissionState(item))&&(!filter.student||filter.student===item.student_id)&&
      (!filter.timing||(filter.timing==='late')===!!item.attempts[0]?.late));
    const states=Object.entries(submissionStates).filter(([state])=>state!=='not_started');
    const filters=sent.length?`<form class="filter-bar op-inline-form" data-op-filter="work-review">
      ${select('status','Статус проверки',[['','Все статусы'],...states],filter.status)}
      ${select('student','Студент',[['','Все студенты'],...work.recipients.map(x=>[x.id,x.name])],filter.student)}
      ${select('timing','Срок сдачи',[['','Любой срок'],['on-time','Вовремя'],['late','С опозданием']],filter.timing)}
      <button type="submit" class="outline-button">Показать</button></form>`:'';
    const submissions=list(filtered,item=>workReviewRow(item,work,scope),sent.length?'Работ по этому фильтру нет':'Работы ещё не отправлены',
      sent.length?'Выберите другие параметры.':'После сдачи работа появится здесь.');
    const generalDue=work.general_due_at||work.due_at;
    return title(work.title,workStates[work.state]+' · Общий срок '+deadlineLabel(generalDue),actions)+section('Условия задания',summary)+
      section('Отправленные работы',filters+submissions)+section('Получатели',recipientRows);
  }

  function safeReference(value,label='Ссылка к работе'){
    try{const ref=new URL(value);if(ref.protocol==='https:'&&!ref.username&&!ref.password)return `<a href="${esc(ref.href)}" rel="noopener noreferrer" target="_blank">${esc(label)}</a>`;}
    catch{/* Optional reference. */}
    return '';
  }

  function teaching(data){
    if(data.work)return workDetails(data);
    if(!data.students)return title('Группы и дисциплины','Назначения преподавателя.',
      link('/app/teach-schedule','Мои занятия','outline-button')+link('/app/notifications','Уведомления','outline-button'))+
      list(data.items,x=>row(link('/app/teaching/'+x.id,x.discipline,'school-card-link'),p(x.group)));
    const selected=q().tab||'roster', base='/app/teaching/'+data.id;
    const heading=title(data.discipline,'Группа '+data.group)+tabs('Работа с группой',teachTabs,selected,tab=>url(base,{tab}));
    if(selected==='works'){
      return heading+section('Сдача работ',`<div class="op-actions">${button('new-work','Создать задание')}</div>`+
        list(data.works.items,x=>row(link(base+'/works/'+x.id,x.title,'school-card-link'),
          p([workStates[x.state],workType(x),'до '+deadlineLabel(x.due_at),'сдано '+x.submitted].join(' · '))),
          'Пока нет заданий','Выдайте первое задание этой группе.')+
        pageLinks(base,data.works,20));
    }
    if(selected==='report'){
      const s=data.summary, names=Object.fromEntries(data.students.map(person=>[person.id,person.name]));
      return heading+section('Показатели группы',`<dl class="op-summary"><div><dt>Студентов</dt><dd>${s.student_count}</dd></div>
        <div><dt>Средний балл</dt><dd>${s.average??'—'}</dd></div><div><dt>Сдано работ</dt><dd>${s.submitted}</dd></div>
        ${Object.entries(s.attendance).map(([key,n])=>`<div><dt>${esc(attendanceNames[key]||key)}</dt><dd>${n}</dd></div>`).join('')}</dl>`)+
        section('История операций',data.history.length?`<ol class="op-log">${data.history.map(entry=>{
          const labels={grade:'Начисление баллов',attendance:'Посещаемость',work_created:'Задание создано',work_edited:'Задание изменено',
            work_extension:'Срок сдачи продлён',work_individual_due:'Индивидуальный срок изменён',work_score_corrected:'Балл за работу скорректирован',
            feedback:'Работа проверена',consultation:'Назначена консультация',consultation_completed:'Консультация проведена'};
          const value=['grade','work_score_corrected'].includes(entry.action)?`${entry.before.score??'—'} → ${entry.after.score??'—'}`:
            entry.action==='attendance'?`${entry.after.day} · ${attendanceNames[entry.after.status]}`:'';
          return `<li><b>${esc(labels[entry.action]||entry.action)}</b>${p([names[entry.after?.student_id],value,entry.after?.reason].filter(Boolean).join(' · '))}<small>${esc(entry.author)} · ${c.stamp(entry.created_at)} МСК</small></li>`;
        }).join('')}</ol>`:p('Операций пока нет.'));
    }
    const dataset={roster:'students',grades:'grades',attendance:'attendance'}[selected];
    const picker=['attendance','grades'].includes(selected)?teachingSessionPicker(data,selected):'';
    const dayFilter=selected==='attendance'&&!data.class_id?dateForm('attendance','День журнала',data.day):'';
    const tables=`<div class="op-actions">${link(url('/app/tables',{dataset,scope:data.id,
      day:selected==='attendance'?data.day:undefined,class_id:selected==='attendance'?data.class_id:undefined}),
      'Работа с таблицей','outline-button')}</div>`;
    return heading+picker+dayFilter+tables+
      list(data.students.filter(person=>!data.class_id||selected==='roster'||person.class_participant),person=>{
        const counts=person.attendance_counts;
        const details=selected==='grades'?'Накопленные баллы: '+(person.grade.score??'—'):selected==='attendance'?
          (attendanceNames[person.attendance.status]||'Отметки пока нет'):person.number+
          ` · Баллы: ${person.grade.score??'—'} · Посещено: ${(counts.present||0)+(counts.late||0)} · Пропущено: ${(counts.absent||0)+(counts.excused||0)}`;
        return row(esc(person.name),p(details),selected==='grades'?button('grade','Начислить баллы',person.id)+button('point-history','История баллов',person.id):
          selected==='attendance'?button('attendance','Поставить отметку',person.id):'');
      },'Список пуст','Состав учебной группы ведёт администратор.');
  }

  function consultations(data){
    return title('Мои консультации','Назначайте время приёма для своих групп.',data.loads.length?button('consultation','Назначить консультацию'):'')+
      list(data.items,x=>row(esc(x.subject),p(c.stamp(x.starts)+'–'+c.stamp(x.ends)+' МСК · '+x.room)+
        p('Записалось '+x.booked+' из '+x.capacity)+p(x.students.join(', ')),
        x.completed?'<span class="campus-pill">Проведена</span>':new Date(x.ends)<=new Date()?button('complete-consultation','Отметить проведённой',x.id):''),
      'Консультаций пока нет','Назначьте время по одной из своих дисциплин.');
  }

  function weekControls(base,week){
    return `<div class="op-week">${dateForm('week','Неделя с',week)}
      <nav class="op-actions" aria-label="Переключить неделю">${link(url(base,{week:c.addDays(week,-7)}),'Предыдущая','outline-button')}${link(base,'Текущая','outline-button')}${link(url(base,{week:c.addDays(week,7)}),'Следующая','outline-button')}</nav></div>`;
  }

  function timetable(data,page){
    const dispatch=page==='timetable-admin'&&role()==='scheduler';
    const name=page==='teach-schedule'?'Мои занятия':page==='registry'?'Занятость аудитории '+data.title:'Расписание занятий';
    const base=page==='registry'?'/app/registry/'+c.state.routeParts[0]:'/app/'+page;
    const tools=page==='timetable-admin'?(dispatch?button('class-create','Подготовить занятие'):'')+
      link('/app/schedule-changes','Проекты','outline-button')+link('/app/academic-calendar','Учебный календарь','outline-button'):'';
    return title(name,'Время занятий — МСК (UTC+3).',tools)+weekControls(base,data.week)+
      list(data.items,(x,i)=>row(esc(x.title||x.discipline),p(c.dateFmt(x.day,{day:'numeric',month:'long'})+' · '+x.start+'–'+x.end)+
        p([x.kind_label,x.group,x.subgroup,x.student_id&&!x.legacy_day?'Индивидуально':'',x.teacher,x.room].filter(Boolean).join(' · '))+
        p(x.status==='cancelled'?'Отменено. '+x.note:x.note),
        dispatch&&x.key?(x.status==='active'?button('class-update','Изменить',i)+button('class-cancel','Отменить',i):button('class-restore','Восстановить',i)):''),
      'Занятий на этой неделе нет','Выберите другую неделю.');
  }

  function changeLabel(value, options){
    const details=value.change, slot=details.slot;
    if(!slot)return p('Занятие №'+(value.event_id||details.legacy?.id))+p(details.note);
    const load=options?.loads.find(x=>x.id===slot.load_id), teacher=options?.teachers.find(x=>x.id===slot.teacher_id),
      room=options?.rooms.find(x=>x.id===slot.room_id);
    return p([slot.title||load?.discipline,load?.group,teacher?.name||slot.teacher,room?.code||slot.room,kindNames[slot.kind]].filter(Boolean).join(' · '))+
      p(c.dateFmt(slot.day)+' · '+slot.start+'–'+slot.end+' МСК'+(slot.weeks>1?' · повторений '+slot.weeks+' · шаг '+(slot.interval||1)+' нед.':''))+
      p(slot.calendar_exception?('Основание исключения · '+slot.calendar_exception):'')+p(details.note);
  }

  function changes(data){
    if(data.items)return title('Проекты расписания','Диспетчер готовит проект, деканат согласует, администратор утверждает.',
      link('/app/timetable-admin','К расписанию','outline-button'))+list(data.items,x=>row(
        link('/app/schedule-changes/'+x.id,'№'+x.id+' · '+actionNames[x.action],'school-card-link'),
        p(stateNames[x.state]+' · '+x.author)+changeLabel(x)))+pageLinks('/app/schedule-changes',data,30);
    const owner=data.author_id===c.state.user.id;
    const editable=role()==='scheduler'&&owner&&['draft','returned'].includes(data.state);
    const agree=role()==='staff'&&data.state==='submitted';
    const publish=role()==='admin'&&data.state==='agreed';
    const steps=(editable?button('edit-change','Редактировать')+button('step-submit','На согласование'):'')+
      (agree?button('step-agree','Согласовать'):'')+(publish?button('step-publish','Утвердить и опубликовать'):'')+
      (agree||publish?button('step-return','Вернуть на доработку'):'');
    const names={created:'Создан',edited:'Отредактирован',submit:'Передан на согласование',agree:'Согласован',publish:'Утверждён',return:'Возвращён'};
    return title(data.title,actionNames[data.action]+' · '+stateNames[data.state],steps)+section('Параметры',changeLabel(data,data.options))+
      section('Журнал согласования',`<ol class="op-log">${data.history.map(x=>`<li><b>${esc(names[x.action]||x.action)}</b><small>${esc(x.author)} · ${c.stamp(x.created_at)} МСК</small>${p(x.after?.comment)}</li>`).join('')}</ol>`);
  }

  function calendarPage(data){
    const editable=role()==='admin';
    const groupName=id=>data.groups.find(group=>group.id===id)?.code||'';
    const scope=x=>groupName(x.group_id)||x.program||'Весь вуз';
    const dates=x=>c.dateFmt(x.starts_on,{day:'numeric',month:'short',year:'numeric'})+' — '+
      c.dateFmt(x.ends_on,{day:'numeric',month:'short',year:'numeric'});
    const edit=(name,x)=>editable?button('calendar-'+name,'Изменить',x.id)+
      button('calendar-delete-'+name,'Удалить',x.id):'';
    const yearForm=`<form data-op-filter="calendar" class="op-inline-form">
      ${input('year','Первый год учебного года',data.year,'number','min="2000" max="2099" required')}
      <button class="outline-button" type="submit">Открыть</button></form>`;
    const terms=list(data.terms,x=>row(esc('Семестр '+x.number+' · '+scope(x)),p(dates(x))+
      x.periods.map(part=>p(periodNames[part.kind]+' · '+dates({starts_on:part.start,ends_on:part.end}))).join('')+
      p(x.source),edit('term',x)),'Семестры не опубликованы','Укажите даты по утверждённому учебному графику.');
    const rules=list(data.rules,x=>row(esc(ruleNames[x.kind]+' · '+scope(x)),p(dates(x))+p(x.label)+p(x.source),
      x.kind==='legacy'?'':edit('rule',x)),'Дополнительных правил нет','Федеральные праздничные даты учитываются автоматически.');
    const groups=list(data.subgroups,x=>row(esc(groupName(x.group_id)+' · '+x.code),p('Мест '+x.capacity),
      editable?button('calendar-subgroup','Изменить',x.id):''),'Подгрупп пока нет','Подгруппа нужна для занятий с частью группы.');
    const members=editable?list(data.members,x=>row(esc(x.name),
      p([groupName(x.group_id),data.subgroups.find(s=>s.id===x.subgroup_id)?.code||'Общая группа'].join(' · ')),
      button('calendar-member','Назначить подгруппу',x.id))):'';
    return title('Учебный календарь','',link('/app/timetable-admin','К расписанию','outline-button'))+yearForm+
      section('Семестры', (editable?button('calendar-term','Добавить семестр'):'')+terms)+
      section('Каникулы и исключения', (editable?button('calendar-rule','Добавить правило'):'')+rules)+
      section('Подгруппы',(editable?button('calendar-subgroup','Добавить подгруппу'):'')+groups)+
      (editable?section('Состав подгрупп',members):'');
  }

  function periodFields(part,index){
    return `<div data-calendar-period class="op-form-grid calendar-period">
      ${select('period_kind_'+index,'Период',Object.entries(periodNames),part.kind||'teaching')}
      ${input('period_start_'+index,'Начало периода',part.start,'date','required')}
      ${input('period_end_'+index,'Конец периода',part.end,'date','required')}
      ${button('calendar-remove-period','Убрать период')}</div>`;
  }

  function calendarForm(action,id,data){
    const base='scheduling/calendar/';
    const choices=data.groups.map(x=>[x.id,x.code]);
    const subgroupChoices=group=>[['','Общая группа'],...data.subgroups.filter(s=>s.group_id===group).map(x=>[x.id,x.code])];
    if(action==='member'){
      const member=data.members.find(x=>x.id===id);
      return modal('Назначить подгруппу',member.name,
        select('subgroup_id','Подгруппа',subgroupChoices(member.group_id),member.subgroup_id??''),
        v=>request(base+'members','PUT',{student_id:id,subgroup_id:Number(v.subgroup_id)||null,version:member.version}));
    }
    if(action==='subgroup'){
      const subgroup=data.subgroups.find(x=>x.id===id);
      const group=subgroup?data.groups.find(x=>x.id===subgroup.group_id):null;
      return modal(subgroup?'Изменить подгруппу':'Добавить подгруппу','',
        (group?p(group.code):select('group_id','Группа',choices))+
        input('code','Название',subgroup?.code,'text','required maxlength="60"')+
        input('capacity','Вместимость',subgroup?.capacity??'','number','min="1" max="200" required'),
        v=>request(base+'subgroups','PUT',{id:subgroup?.id,version:subgroup?.version||0,
          group_id:group?.id||Number(v.group_id),code:v.code,capacity:Number(v.capacity)}));
    }
    const isTerm=action.endsWith('term'), collection=isTerm?'terms':'rules';
    const entry=data[collection].find(x=>x.id===id);
    if(action.startsWith('delete-'))return modal('Удалить запись календаря','Укажите актуальные даты, если вы меняете границы периода.',
      p(entry.source),()=>request(base+collection+'/'+id+'?version='+entry.version,'DELETE'),undefined,'Удалить');
    const scope=[['','Весь вуз'],...choices.map(([id,name])=>['g:'+id,name]),
      ...[...new Set(data.groups.map(x=>x.program))].map(name=>['p:'+name,name])];
    const savedScope=entry?.group_id?'g:'+entry.group_id:entry?.program?'p:'+entry.program:'';
    const range=`<div class="op-form-grid">${input('starts_on',isTerm?'Начало семестра':'Первый день',entry?.starts_on,'date','required')}
      ${input('ends_on',isTerm?'Конец семестра':'Последний день',entry?.ends_on,'date','required')}</div>`;
    const dates=select('scope','Календарь для',scope,savedScope)+range+input('source','Основание или источник дат',entry?.source,'text','required minlength="3" maxlength="300"');
    const specific=isTerm?`<div class="op-form-grid">
      ${input('academic_year','Первый год учебного года',entry?.academic_year??data.year,'number','min="2000" max="2098" required')}
      ${input('number','Номер семестра',entry?.number??1,'number','min="1" max="4" required')}</div>
      ${choiceGroup('weekday','Учебные дни недели',['Пн','Вт','Ср','Чт','Пт','Сб','Вс'].map((text,i)=>[String(i),text]),
      (entry?.weekdays||'01234').split(''))}
      <div data-calendar-periods>${(entry?.periods||[{}]).map(periodFields).join('')}</div>
      ${button('calendar-add-period','Добавить период')}
      ${choiceGroup('legacy','Прежнее регулярное расписание',[['yes','Использовать прежний шаблон в учебные недели']],entry?.legacy?['yes']:[])}`:
      select('kind','Причина',Object.entries(ruleNames).filter(([name])=>name!=='legacy'),entry?.kind||'off')+
      input('label','Уточнение',entry?.label,'text','maxlength="130"');
    return modal(entry?'Изменить учебный календарь':isTerm?'Добавить семестр':'Добавить правило',
      isTerm?'Укажите точные даты по учебному графику.':'',dates+specific,(v,fd)=>{
        const detail={id:entry?.id,version:entry?.version||0,group_id:v.scope.startsWith('g:')?Number(v.scope.slice(2)):null,
          program:v.scope.startsWith('p:')?v.scope.slice(2):'',starts_on:v.starts_on,ends_on:v.ends_on,source:v.source};
        if(isTerm){
          const periods=Object.keys(v).filter(x=>x.startsWith('period_kind_')).map(x=>{
            const i=x.slice('period_kind_'.length);
            return {kind:v[x],start:v['period_start_'+i],end:v['period_end_'+i]};
          });
          Object.assign(detail,{academic_year:Number(v.academic_year),number:Number(v.number),
            weekdays:fd.getAll('weekday').join(''),periods,legacy:fd.has('legacy')});
        }else Object.assign(detail,{kind:v.kind,label:v.label});
        return request(base+collection,'PUT',detail);
      },isTerm?value=>c.route('academic-calendar',{context:{year:value.academic_year}}):undefined);
  }

  function registry(data){
    if(data.week)return timetable(data,'registry');
    const tab=q().tab||'rooms', admin=role()==='admin', editable=tab==='rooms'?['scheduler','admin'].includes(role()):admin;
    const tabsForRole={...registryTabs};
    if(!admin)delete tabsForRole.students;
    const byGroup=Object.fromEntries(data.groups.map(g=>[g.id,g.code]));
    const headings={
      rooms:x=>link('/app/registry/'+x.id,x.code,'school-card-link'),
      groups:x=>esc(x.code),loads:x=>esc(x.discipline),students:x=>esc(x.name),
    };
    const summaries={
      rooms:x=>p(x.building+' · '+x.capacity+' мест · '+kindNames[x.kind])+p(x.equipment)+p(
        [x.available?'Доступна':'Недоступна',x.accessible?'Безбарьерный доступ':'Доступ по лестнице'].join(' · ')),
      groups:x=>p(x.program+' · '+x.enrolled+' из '+x.capacity+' студентов'),
      loads:x=>p(x.teacher+' · '+x.group),students:x=>p([x.number,byGroup[x.group_id]||'Без группы'].filter(Boolean).join(' · ')),
    };
    const actions=(editable&&tab!=='students'?button('new-ref',tab==='rooms'?'Добавить аудиторию':tab==='groups'?'Добавить группу':'Добавить назначение'):'')+
      link(url('/app/tables',{dataset:tab}),'Табличный обмен','outline-button');
    return title('Аудитории и группы','Справочники учебного процесса.',actions)+tabs('Справочники',tabsForRole,tab,key=>url('/app/registry',{tab:key}))+
      list(data[tab]||[],x=>row(headings[tab](x),summaries[tab](x),editable?button('edit-ref','Изменить',x.id||x.student_id):''));
  }

  function tablePage(data){
    const meta=data.items.find(x=>x.id===q().dataset)||data.items[0];
    if(!meta)return title('Импорт и экспорт')+empty('Таблиц пока нет','Доступ к таблицам зависит от вашей роли.');
    const selected=q().scope??data.loads[0]?.id;
    const ready=!meta.scoped||data.loads.some(row=>row.id===selected);
    const scope=meta.scoped?selected:undefined;
    const key=tableKey(meta.id,scope);
    const file=upload?.key===key?upload:null;
    const paths=format=>url('/api/tables/'+meta.id+'/export',{format,scope,day:q().day,class_id:q().class_id});
    const chooser=`<form class="filter-bar op-inline-form" data-op-filter="tables">${select('dataset','Таблица',data.items.map(x=>[x.id,x.title]),meta.id)}
      ${meta.scoped?select('scope','Дисциплина и группа',data.loads.map(x=>[x.id,x.discipline+' · '+x.group]),selected):''}
      ${['attendance','schedule'].includes(meta.id)?input('day',meta.id==='schedule'?'Неделя':'День',q().day||c.today(),'date'):''}
      <button class="outline-button" type="submit">Выбрать</button></form>`;
    const exchange=ready?section('Выгрузка',`${q().class_id?p('Журнал выбранного занятия'+(q().day?' · '+c.dateFmt(q().day):'')) : ''}
      <div class="op-actions">${download(paths('csv'),'Скачать CSV')}${download(paths('xlsx'),'Скачать XLSX')}</div>`):
      empty('Выберите назначение','В таблицу попадают данные вашей группы и дисциплины.');
    const add=ready&&meta.editable?section('Загрузка таблицы',
      `<div class="op-actions">${['csv','xlsx'].map(format=>download(url('/api/tables/'+meta.id+'/template',{format}),'Шаблон '+format.toUpperCase())).join('')}</div>
      <div class="field"><label for="ops-file">Файл CSV или XLSX</label><input id="ops-file" type="file" accept=".csv,.xlsx" data-op-file="${meta.id}" data-scope="${scope||''}" aria-describedby="op-table-hint"></div>
      <p class="hint" id="op-table-hint">До 200 строк и 22 КБ.${meta.id==='schedule'?' Загрузка создаёт черновики для согласования.':
        q().class_id?' Для массового заполнения скачайте журнал выбранного занятия и сохраните колонку class_id.':''}</p>
      ${file?filePreview(meta,file):''}<div role="alert" data-op-import-error hidden></div>`):'';
    const history=data.history.length?section('Журнал моих импортов',`<ul class="op-log">${data.history.map(x=>`<li>${esc(data.items.find(i=>i.id===x.dataset)?.title||x.dataset)} · строк ${x.count} · ${c.stamp(x.created_at)} МСК</li>`).join('')}</ul>`):'';
    return title('Импорт и экспорт','Загрузите таблицу, проверьте сопоставление и подтвердите изменения.')+chooser+exchange+add+history;
  }

  function tableKey(dataset,scope){return `${c.state.sessionEpoch}:${dataset}:${scope||0}`;}

  function filePreview(meta,file){
    const r=file.preview;
    if(!r)return p(file.name);
    const map=meta.columns.map(key=>select('map-'+key,(columnLabels[key]||key)+(meta.required.includes(key)?' *':''),
      [['','Без столбца'],...r.headers.map(x=>[x,x])],r.mapping[key])).join('');
    const rows=r.rows.map(row=>`<li><b>Строка ${row.row}</b><p>${esc(Object.entries(row.values).filter(([,value])=>value!==null&&value!=='')
      .map(([key,value])=>key==='slot'?Object.values(value).join(' · '):(columnLabels[key]||key)+' — '+value).join(' · '))}</p></li>`).join('');
    return `<p>${esc(file.name)} · строк к проверке: ${r.count}</p>
      <form data-op-map class="op-map"><div class="op-form-grid">${map}</div><button class="outline-button" type="submit">Проверить сопоставление</button></form>
      ${r.missing.length?p('Сопоставьте: '+r.missing.map(x=>columnLabels[x]||x).join(', ')):''}
      ${r.errors.length?`<ul class="op-errors" role="alert">${r.errors.map(e=>`<li>Строка ${e.row} · ${esc(e.message)}</li>`).join('')}</ul>`:''}
      ${rows?`<details><summary>Предварительный просмотр строк</summary><ul class="op-log">${rows}</ul></details>`:''}
      ${r.prior?p('Эта таблица уже импортирована.') : r.fingerprint?button('apply-table','Подтвердить импорт'):''}`;
  }

  function render(page,data){
    const renderers={teaching,'teach-schedule':()=>timetable(data,page),'teach-consultations':consultations,
      'timetable-admin':()=>timetable(data,page),'schedule-changes':changes,'academic-calendar':calendarPage,registry,tables:tablePage};
    return renderers[page](data);
  }

  function modal(name,description,fields,run,done,submitLabel='Сохранить',wide=false){
    c.modal(c.modalHead(name,description)+`<form data-op-form${wide?' class="work-form"':''}>${fields}
      <div class="inline-error" role="alert" data-op-error hidden></div><div class="modal-actions">
      <button class="outline-button" type="button" data-action="close-modal">Отмена</button><button class="primary-button" type="submit">${esc(submitLabel)}</button>
      </div></form>`,{label:name,wide});
    callbacks.set(c.$('.modal [data-op-form]'),{run,done});
  }

  async function request(path,method='POST',body){
    const source=body===undefined?undefined:JSON.stringify(body);
    const deduplicate=method==='POST'&&/^(scheduling\/changes|units\/(?:union|vuc)\/cases|teaching\/(?:consultations|\d+\/(?:points|works(?:\/\d+\/(?:feedback\/\d+|submissions\/\d+\/score-corrections))?)))$/.test(path);
    const prior=retries.get(path);
    const key=deduplicate?(prior?.source===source?prior.key:crypto.randomUUID()):null;
    if(key)retries.set(path,{source,key});
    const result=await c.api(path,{method,body:source,headers:key?{'Idempotency-Key':key}:{}});
    if(key&&retries.get(path)?.key===key)retries.delete(path);
    return result;
  }

  function moscowLocal(value){
    if(!value)return '';
    return new Date(Date.parse(value)+3*3600000).toISOString().slice(0,16);
  }
  function choiceGroup(name,label,options,selected){
    return `<fieldset class="unit-checklist assignment-choices"><legend>${esc(label)}</legend>${options.map(([value,text])=>
      `<label class="unit-check"><input type="checkbox" name="${name}" value="${esc(value)}" ${selected.includes(value)?'checked':''}> ${esc(text)}</label>`).join('')}</fieldset>`;
  }

  function showWorkControl(control,show){
    if(!control)return;
    control.closest('.field').hidden=!show;
    control.disabled=!show;
  }

  function toggleWorkFields(form){
    if(!form)return;
    const {custom_kind,kind,publish_at,state,audience,subgroup_id,team_lead_id,award_mode}=form.elements;
    showWorkControl(custom_kind,kind?.value==='other');
    showWorkControl(publish_at,state?.value==='scheduled');
    showWorkControl(subgroup_id,audience?.value==='subgroup');
    const people=c.$('[data-work-recipients]',form);
    if(people){
      people.hidden=audience.value!=='students';
      people.querySelectorAll('input').forEach(control=>control.disabled=people.hidden);
      const selected=new Set([...people.querySelectorAll(':checked')].map(control=>control.value));
      const roster=Object.fromEntries((current().detail||current()).students.map(student=>[student.id,student.subgroup_id]));
      for(const option of team_lead_id.options){
        option.hidden=option.value!==''&&(
          audience.value==='students'&&!selected.has(option.value)||
          audience.value==='subgroup'&&roster[option.value]!==Number(subgroup_id.value));
        option.disabled=option.hidden;
      }
      if(team_lead_id.selectedOptions[0]?.disabled)team_lead_id.value='';
      showWorkControl(award_mode,!!team_lead_id.value);
    }
    const allowed=new Set([...form.querySelectorAll('[name="methods"]:checked')].map(control=>control.value));
    for(const option of form.querySelectorAll('[name="required_methods"]')){
      option.disabled=!allowed.has(option.value);
      option.parentElement.hidden=option.disabled;
    }
    const files=c.$('[data-work-file-policy]',form);
    if(files){
      files.hidden=!allowed.has('files');
      files.querySelectorAll('input').forEach(control=>control.disabled=files.hidden);
    }
  }

  const workUploadLimit=1024*1024;
  function fileInput(name,label){
    const formats=acceptedFormats.map(ext=>'.'+ext).join(',');
    return field(name,label,`<input id="op-${name}" name="${name}" type="file" multiple accept="${formats}" aria-describedby="hint-${name}">
      <small class="hint" id="hint-${name}">До трёх файлов, 1 МиБ суммарно.</small>`);
  }

  async function workUploads(formData,name,existing=[]){
    const epoch=c.state.sessionEpoch, picked=formData.getAll(name).filter(file=>file.name);
    const total=picked.reduce((sum,file)=>sum+file.size,existing.reduce((sum,file)=>sum+file.size,0));
    if(picked.length+existing.length>3||total>workUploadLimit)throw new Error('Можно приложить до трёх файлов размером до 1 МиБ суммарно.');
    const uploads=[];
    for(const file of picked){
      if(!file.size)throw new Error('Файл «'+file.name+'» пуст.');
      if(file.name.lastIndexOf('.')<1||!acceptedFormats.includes(file.name.split('.').at(-1).toLowerCase())){
        throw new Error('Формат файла «'+file.name+'» недоступен.');
      }
      let bytes;
      try{bytes=new Uint8Array(await file.arrayBuffer());}
      catch{throw new Error('Не удалось прочитать файл «'+file.name+'». Выберите его снова.');}
      if(epoch!==c.state.sessionEpoch)throw Object.assign(new Error('Сеанс изменился.'),{stale:true});
      let content='';
      for(let start=0;start<bytes.length;start+=16384)content+=String.fromCharCode(...bytes.subarray(start,start+16384));
      uploads.push({name:file.name,content:btoa(content)});
    }
    return uploads;
  }
  function materialOptions(items,selected){
    const options=new Map([...selected,...items.map(row=>[row.id,row.title])]);
    return choiceGroup('material_ids','Выберите до пяти материалов',Array.from(options),Array.from(selected.keys()));
  }

  async function searchWorkMaterials(control){
    const form=control.form, box=c.$('[data-work-material-options]',form), status=c.$('[data-work-material-status]',form);
    const search=c.$('[data-work-material-search]',form), load=control.dataset.load;
    control.disabled=true;
    status.textContent='Ищем материалы…';
    try{
      const result=await c.api(url('teaching/'+load+'/material-options',{q:search.value.trim()}));
      if(!box.isConnected)return;
      const selected=new Map([...box.querySelectorAll('input:checked')].map(input=>[Number(input.value),input.parentElement.textContent.trim()]));
      box.innerHTML=materialOptions(result.items,selected);
      status.textContent=result.more?'Уточните название для остальных материалов.':result.items.length?'':'Материалы не найдены.';
    }catch(error){if(!error.stale&&box.isConnected)status.textContent=error.message;}
    finally{control.disabled=false;}
  }

  async function openWorkForm(base,data){
    const {loadingId,modalId,sessionEpoch}=c.state;
    try{
      const options=await c.api(base+'/material-options');
      if(loadingId!==c.state.loadingId||modalId!==c.state.modalId||sessionEpoch!==c.state.sessionEpoch)return;
      workForm(base,data,options);
      toggleWorkFields(c.$('.modal [data-op-form]'));
    }catch(error){if(!error.stale&&loadingId===c.state.loadingId)c.toast(error.message);}
  }

  function workForm(base,data,options){
    const work=data.work, detail=data.detail||data, locked=work?.state==='published';
    const roster=detail.students.map(student=>[student.id,student.name]);
    const currentMethods=work?.methods||['text','url'];
    const methodOptions=Object.entries(handInMethods).filter(([key])=>key!=='complete'||currentMethods.includes(key));
    const currentDue=moscowLocal(work?.due_at)||c.addDays(c.today(),7)+'T23:59';
    const defaults=[['draft',workStates.draft],['scheduled',workStates.scheduled],['published',workStates.published]];
    const subgroupOptions=(detail.subgroups||[]).map(group=>[group.id,group.code]);
    const audiences=[['group','Вся группа'],...(subgroupOptions.length?[['subgroup','Подгруппа']]:[]),['students','Отдельные студенты']];
    const selectedAudience=work?.subgroup_id?'subgroup':work?.recipient_ids?.length?'students':'group';
    const titleFields=input('title','Название',work?.title,'text','required minlength="4" maxlength="180"')+
      (locked?'':`<div class="op-form-grid">${select('state','Публикация',defaults,work?.state||'published')}
      ${select('kind','Тип работы',Object.entries(workKinds),work?.kind||'homework')}${input('custom_kind','Название другого типа',work?.custom_kind,'text','maxlength="80"')}
      ${input('publish_at','Дата публикации (МСК)',moscowLocal(work?.publish_at),'datetime-local')}</div>`);
    const points=locked?'':input('max_points','Максимальный балл',work?.max_points??100,'number','required min="0" max="1000" step="1"');
    const audience=locked?'':`<details class="assignment-attempt" open><summary>Получатели</summary>
      <div class="op-form-grid">${select('audience','Кому выдать задание',audiences,selectedAudience)}
      ${select('subgroup_id','Подгруппа',[['','Выберите подгруппу'],...subgroupOptions],work?.subgroup_id??'')}</div>
      <div data-work-recipients>${choiceGroup('recipient_ids','Студенты',roster,work?.recipient_ids||[])}</div>
      ${select('team_lead_id','Ответственный за общую отправку',[['','Индивидуальная сдача'],...roster],work?.team_lead_id??'')}
      ${select('award_mode','Начисление при общей сдаче',[['all','Всем участникам'],['lead','Только ответственному']],work?.award_mode||'all')}
      ${select('class_id','Связанное занятие',[['','Без связи'],...(detail.sessions||[]).map(session=>
        [session.id,c.dateFmt(session.day)+(session.topic?' · '+session.topic:'')])],work?.class_id??'')}</details>`;
    const settings=`<details class="assignment-attempt"><summary>Способы сдачи и попытки</summary>
      ${choiceGroup('methods','Допустимые способы',methodOptions,currentMethods)}
      ${choiceGroup('required_methods','Обязательные способы',methodOptions.map(([key,label])=>[key,'Требовать · '+label]),
        work?.required_methods||[])}
      <p class="hint">Если обязательных способов нет, достаточно одного из допустимых.</p>
      <div data-work-file-policy>
      ${choiceGroup('formats','Форматы файлов',acceptedFormats.map(ext=>[ext,ext.toUpperCase()]),work?.formats||acceptedFormats)}
      <div class="op-form-grid">${input('min_files','Минимум файлов',work?.min_files??1,'number','min="1" max="3" step="1" required')}
      ${input('max_files','Максимум файлов',work?.max_files??3,'number','min="1" max="3" step="1" required')}</div></div>
      <div class="op-form-grid">${yesNo('allow_resubmission','Разрешить новую отправку после отзыва',work?.allow_resubmission??true)}
      ${yesNo('allow_late','Принимать после дедлайна',work?.allow_late??true)}
      ${input('max_attempts','Лимит попыток',work?.max_attempts??'','number','min="1" max="50" step="1"')}</div></details>`;
    const selected=new Map((work?.material_ids||[]).map(id=>[id,work.course_materials.find(row=>row.id===id)?.title||'Материал № '+id]));
    const original=work?.source_files||[];
    const sourceFiles=`<details class="assignment-attempt"><summary>Исходные файлы${original.length?' · '+original.length:''}</summary>
      ${original.length?choiceGroup('remove_source_ids','Убрать из задания',original.map(file=>[file.id,file.name]),[]):''}
      ${fileInput('source_files','Прикрепить исходные файлы')}</details>`;
    const linked=`<details class="assignment-attempt"><summary>Учебные материалы дисциплины</summary>
      <div class="field"><label for="assignment-material-search">Поиск по названию</label>
        <input id="assignment-material-search" type="search" maxlength="100" data-work-material-search></div>
      <button type="button" class="outline-button" data-work-material-find data-load="${Number(detail.id)}">Найти материалы</button>
      <p role="status" data-work-material-status>${options.more?'Уточните название для остальных материалов.':''}</p>
      <div data-work-material-options>${materialOptions(options.items,selected)}</div></details>`;
    return modal(work?'Изменить задание':'Создать задание',detail.discipline+' · '+detail.group,titleFields+
      `<div class="op-form-grid">${input('due_at','Общий срок сдачи (МСК)',currentDue,'datetime-local','required')}${points}</div>`+
      area('instructions','Условия задания',work?.instructions,4000)+audience+settings+sourceFiles+
      `<details class="assignment-attempt"><summary>Описание, критерии и ссылки</summary>${area('description','Описание',work?.description,1500)}
      ${area('criteria','Критерии оценивания',work?.criteria,2000)}
      ${area('materials','Дополнительные материалы (по одной HTTPS-ссылке в строке)',(work?.materials||[]).join('\n'),2550)}</details>`+linked,
      async (values,formData)=>{
        const methods=formData.getAll('methods');
        const minFiles=Number(values.min_files??work?.min_files??1), maxFiles=Number(values.max_files??work?.max_files??3);
        const body={title:values.title,instructions:values.instructions,description:values.description,criteria:values.criteria,
          materials:values.materials.split(/\s+/).filter(Boolean),material_ids:formData.getAll('material_ids').map(Number),
          methods,required_methods:formData.getAll('required_methods'),
          formats:methods.includes('files')?formData.getAll('formats'):work?.formats||acceptedFormats,
          min_files:minFiles,max_files:maxFiles,max_attempts:values.max_attempts?Number(values.max_attempts):null,
          allow_resubmission:values.allow_resubmission==='true',allow_late:values.allow_late==='true'};
        if(!work||values.due_at!==moscowLocal(work.due_at))body.due_at=msk(values.due_at);
        if(!locked){
          const recipients=formData.getAll('recipient_ids').map(Number), subgroupId=Number(values.subgroup_id)||null;
          if(values.audience==='students'&&!recipients.length)throw new Error('Выберите хотя бы одного студента.');
          if(values.audience==='subgroup'&&!subgroupId)throw new Error('Выберите подгруппу.');
          Object.assign(body,{state:values.state,kind:values.kind,custom_kind:values.custom_kind||'',
            publish_at:values.state==='scheduled'&&values.publish_at?msk(values.publish_at):null,
            max_points:Number(values.max_points),recipient_ids:recipients,subgroup_id:subgroupId,
            team_lead_id:Number(values.team_lead_id)||null,award_mode:values.award_mode||'all',class_id:Number(values.class_id)||null});
        }
        if(!methods.length)throw new Error('Укажите хотя бы один способ сдачи.');
        if(methods.includes('files')&&(!body.formats.length||minFiles>maxFiles))throw new Error('Проверьте допустимые форматы и количество файлов.');
        if(body.material_ids.length>5)throw new Error('К заданию можно приложить до пяти учебных материалов.');
        const removed=formData.getAll('remove_source_ids').map(Number);
        const uploads=await workUploads(formData,'source_files',original.filter(file=>!removed.includes(file.id)));
        if(uploads.length)body.source_files=uploads;
        if(removed.length)body.remove_source_ids=removed;
        return work?request(base+'/works/'+work.id,'PATCH',{...body,version:work.version}):request(base+'/works','POST',body);
      },null,'Сохранить',true);
  }

  function compareAttempts(scope,item){
    const options=item.attempts.map(attempt=>[attempt.version,attemptLabel(attempt)]);
    const heading='Сравнить версии';
    const choices=select('compare_first','Первая версия',options,item.attempts[1].version)+
      select('compare_second','Вторая версия',options,item.attempts[0].version);
    c.modal(c.modalHead(heading,item.student)+`<div class="op-form-grid" data-work-compare>${choices}</div>
      <div class="work-compare-grid" data-work-compare-body></div>`,{label:heading,wide:true});
    const panel=c.$('[data-work-compare]');
    const content=c.$('[data-work-compare-body]');
    const redraw=()=>{
      content.innerHTML=[...panel.querySelectorAll('select')].map(control=>{
        const attempt=item.attempts.find(row=>row.version===Number(control.value));
        return `<section class="assignment-attempt work-compare-version"><h3>${esc(attemptLabel(attempt))}</h3>
          ${attemptBody(attempt,scope)}${reviewHistory(attempt.feedback,scope)}</section>`;
      }).join('');
    };
    panel.addEventListener('change',redraw);
    redraw();
  }

  function teacherForm(action,id,data){
    const base='teaching/'+(data.detail?.id||data.id);
    if(action==='point-history')return openPointHistory(base,id,data);
    if(action==='grade'||action==='attendance'){
      const student=data.students.find(x=>x.id===id);
      if(action==='grade')return modal('Начислить баллы',student.name+' · накоплено '+(student.grade.score??0),
        input('points','Сколько баллов добавить','','number','required min="1" max="100" step="1"')+
        input('reason','Основание начисления','','text','required minlength="3" maxlength="300"'),v=>request(base+'/points','POST',{
          student_id:id,version:student.grade.version,points:Number(v.points),reason:v.reason,class_id:data.class_id}));
      return modal('Посещаемость',student.name+' · '+c.dateFmt(data.day),
        select('status','Отметка',Object.entries(attendanceNames),student.attendance.status||'present')+
        area('note','Комментарий',student.attendance.note),v=>request(base+'/attendance','PUT',{
          ...v,student_id:id,day:data.day,version:student.attendance.version,class_id:data.class_id}));
    }
    if(action==='new-work'||action==='edit-work')return openWorkForm(base,data);
    const work=data.work;
    if(action==='close-work'||action==='archive-work'){
      const closing=action==='close-work';
      return modal(closing?'Закрыть приём':'Архивировать задание',work.title,
        p(closing?'Студенты больше не смогут отправлять версии. Уже сданные работы можно будет проверить.':
          'Сдача и проверка закроются. Отправленные версии и результаты будут доступны в истории.'),
        ()=>request(base+'/works/'+work.id,'PATCH',{state:closing?'closed':'archived',version:work.version}));
    }
    if(action==='extend-work'||action==='individual-due'){
      const person=work.recipients.find(x=>x.id===id);
      const endpoint=base+'/works/'+work.id+'/recipients/'+id;
      const groupNote=work.team_lead_id?p('Срок применяется ко всем участникам общей работы.'):'';
      if(action==='individual-due'){
        const fields=input('individual_due_at','Персональный срок (МСК)',moscowLocal(person.individual_due_at),'datetime-local')+
          p('Общий срок '+deadlineLabel(person.general_due_at||work.due_at))+
          p('Очистите поле для возврата к общему сроку. Сохранение сбрасывает продление первой сдачи.')+
          (person.revision_due_at?p('Срок доработки '+deadlineLabel(person.revision_due_at)+' действует отдельно.'):'')+groupNote;
        return modal('Индивидуальный срок',person.name,fields,
          v=>request(endpoint,'PATCH',{version:work.version,individual_due_at:v.individual_due_at?msk(v.individual_due_at):null}));
      }
      return modal('Продлить срок',person.name+' · действующий срок '+deadlineLabel(person.due_at),
        input('extended_until',person.revision_due_at?'Новый срок доработки (МСК)':'Новый срок (МСК)','','datetime-local','required')+groupNote,
        v=>request(endpoint,'PATCH',{version:work.version,extended_until:msk(v.extended_until)}));
    }
    if(action==='compare-work'||action==='correct-score'){
      const item=work.submissions.find(row=>row.id===id);
      const scope=base+'/works/'+work.id+'/submissions/'+id;
      if(action==='compare-work')return compareAttempts('/api/'+scope,item);
      return modal(reviewActions.correct_score,item.student+' · текущий балл '+Number(item.score),
        input('score','Исправленный балл',item.score,'number','required min="0" max="'+Number(work.max_points)+'" step="1"')+
        input('reason','Причина корректировки','','text','required minlength="3" maxlength="300"')+
        p('В истории сохранятся прежний балл, новый балл и причина.'),
        v=>request(scope+'/score-corrections','POST',{score:Number(v.score),reason:v.reason.trim(),version:item.version,
          submitted_version:item.attempt_version}));
    }
    if(action==='feedback'||['review-work','revise-work','accept-work','complete-work','grade-work'].includes(action)){
      const item=work.submissions.find(x=>x.id===id);
      const step=action==='feedback'?'comment':action.replace('-work','');
      const score=step==='accept'||step==='grade'?input('score',step==='accept'?'Балл за работу (необязательно)':'Балл за работу','',
        'number',`min="0" max="${Number(work.max_points)}" step="1"${step==='grade'?' required':''}`):'';
      const revision=step==='revise'?input('extended_until','Срок доработки (МСК)','','datetime-local'):'';
      const hasFeedback=['revise','accept','comment','grade'].includes(step);
      const noteFields=hasFeedback?area('comment','Комментарий студенту','',2000)+area('remarks','Замечания к работе','',2000)+
        fileInput('files','Файлы с исправлениями'):'';
      const fields=score+revision+noteFields;
      return modal(step==='comment'?'Обратная связь':reviewActions[step],item.student+' · попытка '+item.attempts[0].number,fields,
        async (v,formData)=>{
          const comment=v.comment?.trim()||'', remarks=v.remarks?.trim()||'';
          if(step==='revise'&&Math.max(comment.length,remarks.length)<3)throw new Error('Опишите, что нужно исправить.');
          const files=hasFeedback?await workUploads(formData,'files'):[];
          if(step==='comment'&&Math.max(comment.length,remarks.length)<3&&!files.length)throw new Error('Введите комментарий, замечания или приложите файл.');
          return request(base+'/works/'+work.id+'/feedback/'+id,'POST',{action:step,submitted_version:item.attempt_version,
            version:item.version,score:v.score?Number(v.score):null,comment,remarks,files,
            extended_until:v.extended_until?msk(v.extended_until):null});
        },null,'Сохранить',hasFeedback);
    }
    if(action==='consultation'){
      const date=c.addDays(c.today(),2);
      return modal('Назначить консультацию','Время вводится по Москве.',
        select('load_id','Дисциплина и группа',data.loads.map(x=>[x.id,x.discipline+' · '+x.group]))+
        input('starts','Начало',date+'T17:00','datetime-local','required')+input('ends','Окончание',date+'T17:30','datetime-local','required')+
        input('room','Кабинет','','text','required maxlength="100"')+input('capacity','Число мест',5,'number','required min="1" max="50"'),
        v=>request('teaching/consultations','POST',numbers({...v,starts:msk(v.starts),ends:msk(v.ends)},'load_id','capacity')));
    }
    return modal('Отметить консультацию проведённой','Отметка сохранится в журнале.', '',
      ()=>request('teaching/consultations/'+id+'/complete'));
  }

  async function openPointHistory(base,id,data){
    const epoch=c.state.sessionEpoch, loadId=c.state.loadingId, modalId=c.state.modalId;
    const student=data.students.find(x=>x.id===id);
    try{
      const result=await c.api(`${base}/points/${id}`);
      if(epoch!==c.state.sessionEpoch||loadId!==c.state.loadingId||modalId!==c.state.modalId)return;
      const corrections=(result.corrections||[]).map(entry=>`<li><b>Корректировка · ${Number(entry.previous_points)} → ${Number(entry.corrected_points)}</b>
        ${entry.created_at?`<time datetime="${esc(entry.created_at)}">${esc(deadlineLabel(entry.created_at))}</time>`:''}${userText(entry.reason)}</li>`);
      c.modal(c.modalHead('История баллов',student.name)+
        (result.items.length||corrections.length?`<ol class="academic-history">${corrections.join('')}${result.items.map(window.ATLASAcademics.showAward).join('')}</ol>`:
          p('Начислений пока нет.')),
        {label:'История баллов'});
    }catch(error){if(!error.stale&&epoch===c.state.sessionEpoch&&loadId===c.state.loadingId)c.toast(error.message);}
  }

  function appointmentTeachers(options,load){
    const selected=options.loads.find(row=>row.id===Number(load));
    return options.teachers.filter(row=>row.discipline_id===selected?.discipline_id).map(row=>[row.id,row.name]);
  }

  function classAudience(options,load,field){
    const group=options.loads.find(row=>row.id===Number(load))?.group_id;
    if(field==='subgroup_id')return [['','Вся группа'],...options.subgroups.filter(x=>x.group_id===group).map(x=>[x.id,x.code])];
    return [['','Для группы или подгруппы'],...options.students.filter(x=>x.group_id===group).map(x=>[x.id,x.name])];
  }

  function classForm(action,id,data){
    const saved=action==='edit-change'?data.change:null, event=action==='class-create'?null:data.items?.[id];
    const kind=saved?.action||action.replace('class-','');
    const fields=saved?.slot||event||{};
    const legacy=saved?.legacy||(event?.legacy_day?{id:event.id,day:event.legacy_day}:null);
    const noSlot=['cancel','restore'].includes(kind);
    const choice=fields.load_id??data.options.loads[0]?.id;
    const date=fields.day||(q().week&&q().week>c.today()?q().week:c.addDays(c.today(),1));
    const timeFields=`${input('day','Дата',date,'date','required')}${input('start','Начало',fields.start||'17:00','time','required')}
      ${input('end','Окончание',fields.end||'18:00','time','required')}`;
    const exceptionField=input('calendar_exception','Основание для занятия вне учебного периода',fields.calendar_exception,'text','maxlength="300"');
    const audienceFields=kind==='create'?select('load_id','Группа и дисциплина',
      data.options.loads.map(x=>[x.id,x.group+' · '+x.discipline]),choice,'data-op-load required')+
      select('subgroup_id','Подгруппа',classAudience(data.options,choice,'subgroup_id'),fields.subgroup_id??'')+
      select('student_id','Студент для индивидуального события',classAudience(data.options,choice,'student_id'),fields.student_id??''):'';
    const parts=noSlot?'':legacy?`<div class="op-form-grid">${timeFields}
      ${input('room','Аудитория или формат',fields.room,'text','required maxlength="80"')}
      ${input('teacher','Преподаватель',fields.teacher,'text','required maxlength="120"')}</div>${exceptionField}`:
      `<div class="op-form-grid">${audienceFields}${select('teacher_id','Преподаватель',
      appointmentTeachers(data.options,choice),fields.teacher_id)}${select('room_id','Аудитория',
      data.options.rooms.map(x=>[x.id,x.code+(x.kind==='online'?' · дистанционный формат':' · '+x.capacity+' мест')+
        (x.available?'':' · недоступна')]),fields.room_id)}
      ${select('kind','Вид события',Object.entries(kindNames),fields.kind==='seminar'?'practice':fields.kind||'lecture')}${timeFields}
      ${kind==='create'?input('weeks','Число повторений с первой датой',fields.weeks||1,'number','required min="1" max="32"')+
        input('interval','Шаг между занятиями в неделях',fields.interval||1,'number','required min="1" max="4"'):''}</div>
      ${input('title','Название или тема события',fields.title,'text','maxlength="180"')}
      ${input('equipment','Оборудование через запятую',fields.equipment,'text','maxlength="160"')}${exceptionField}`;
    const eventId=saved?.event_id||event?.id, eventVersion=saved?.event_version||event?.version;
    return modal(actionNames[kind],noSlot?(event?.title||event?.discipline||''):'Время вводится по Москве.',
      parts+area('note',kind==='cancel'?'Причина отмены':'Комментарий',saved?.note??(kind==='update'?event?.note:'')),
      v=>{
        const note=v.note;delete v.note;
        const body={action:kind,note,...(legacy?{legacy,event_version:eventVersion}:eventId?{event_id:eventId,event_version:eventVersion}:{})};
        if(!noSlot)body.slot=legacy?v:numbers({...v,load_id:v.load_id??choice,
          subgroup_id:Number(v.subgroup_id??fields.subgroup_id)||null,student_id:Number(v.student_id??fields.student_id)||null,
          weeks:v.weeks||1,interval:v.interval||1},'load_id','teacher_id','room_id','weeks','interval');
        return saved?request('scheduling/changes/'+data.id,'PUT',{...body,version:data.version}):request('scheduling/changes','POST',body);
      },value=>c.route('schedule-changes',{parts:[String(value.id)]}));
  }

  function refForm(action,id,data){
    const tab=q().tab||'rooms';
    const record=action==='edit-ref'?data[tab].find(x=>(x.id||x.student_id)===id):{};
    const g=data.groups.map(x=>[x.id,x.code]);
    const code=input('code','Код',record.code,'text','required maxlength="80"');
    const capacity=input('capacity','Число мест',record.capacity||24,'number',`required min="1" max="${tab==='groups'?200:500}"`);
    const fields={
      rooms:input('building','Корпус',record.building,'text','required maxlength="100"')+code+capacity+
        select('kind','Тип помещения',Object.entries({lecture:'Лекционная',seminar:'Семинарская',lab:'Лаборатория',online:'Дистанционный формат'}),record.kind)+
        input('equipment','Оборудование через запятую',record.equipment,'text','maxlength="160"')+
        yesNo('accessible','Безбарьерный доступ',record.accessible)+yesNo('available','Помещение доступно',record.available??true),
      groups:code+input('program','Учебная программа',record.program,'text','required maxlength="180"')+capacity+yesNo('accessible','Требуется безбарьерный доступ',record.accessible),
      loads:select('group_id','Группа',g,record.group_id)+select('assignment_id','Дисциплина и преподаватель',
        (data.assignments||[]).map(x=>[x.id,x.discipline+' · '+x.teacher]),record.assignment_id),
      students:select('group_id','Группа',g,record.group_id),
    };
    return modal(action==='edit-ref'?'Изменить запись':'Добавить запись',record.name||registryTabs[tab],fields[tab],values=>{
      for(const key of ['accessible','available'])if(key in values)values[key]=values[key]==='true';
      for(const key of ['capacity','group_id','assignment_id'])if(key in values)values[key]=Number(values[key]);
      return request('registry/'+tab,'PUT',{...values,version:record.version||0,
        ...(tab==='students'?{student_id:record.student_id}:record.id?{id:record.id}:{})});
    });
  }

  async function submitModal(form){
    const handler=callbacks.get(form);
    if(!handler||c.state.pending)return;
    const epoch=c.state.sessionEpoch, formData=new FormData(form), values=Object.fromEntries(formData),
      controls=[...form.elements].filter(control=>!control.disabled), error=c.$('[data-op-error]',form);
    c.state.pending++;controls.forEach(control=>control.disabled=true);error.hidden=true;
    let result;
    try{result=await handler.run(values,formData);}
    catch(e){if(!e.stale&&form.isConnected){error.hidden=false;error.textContent=e.message;}}
    finally{if(epoch===c.state.sessionEpoch){c.state.pending--;controls.forEach(control=>control.disabled=false);}}
    if(result&&epoch===c.state.sessionEpoch){
      c.closeModal({force:true});c.toast('Изменение сохранено.');
      if(handler.done)await handler.done(result);else await c.updatePage({quiet:true});
    }
  }

  function tableError(error){
    const target=c.$('[data-op-import-error]');
    if(!target||error.stale)return;
    target.hidden=false;target.textContent=[error.message,...(error.details?.rows||[]).map(x=>`Строка ${x.row} · ${x.message}`)].join('\n');
  }

  async function previewFile(file,mapping={}){
    if(c.state.pending)return;
    const epoch=c.state.sessionEpoch, href=c.state.routeHref;
    c.state.pending++;
    try{
      const result=await request(url('tables/'+file.dataset+'/preview',{scope:file.scope}),'POST',{format:file.format,content:file.content,mapping});
      if(epoch===c.state.sessionEpoch&&href===c.state.routeHref){file.preview=result;upload=file;c.drawPage();c.$('[data-op-map] select')?.focus();}
    }catch(error){if(href===c.state.routeHref)tableError(error);}
    finally{if(epoch===c.state.sessionEpoch)c.state.pending--;}
  }

  async function pickFile(input){
    const file=input.files[0], href=c.state.routeHref, epoch=c.state.sessionEpoch;
    if(!file||c.state.pending)return;
    upload=null;c.drawPage();
    const format=file.name.split('.').at(-1)?.toLowerCase();
    if(!['csv','xlsx'].includes(format)||file.size>22000){tableError(new Error('Выберите CSV или XLSX размером до 22 КБ.'));return;}
    try{
      const bytes=new Uint8Array(await file.arrayBuffer());
      if(epoch!==c.state.sessionEpoch||href!==c.state.routeHref)return;
      const dataset=input.dataset.opFile,scope=Number(input.dataset.scope)||undefined;
      await previewFile({name:file.name,format,dataset,scope,key:tableKey(dataset,scope),content:btoa(String.fromCharCode(...bytes))});
    }catch(error){if(href===c.state.routeHref)tableError(error);}
  }

  async function applyTable(){
    if(!upload?.preview?.fingerprint||c.state.pending)return;
    const file=upload,epoch=c.state.sessionEpoch;
    c.state.pending++;
    try{
      const result=await request(url('tables/'+file.dataset+'/apply',{scope:file.scope}),'POST',{
        format:file.format,content:file.content,mapping:file.preview.mapping,fingerprint:file.preview.fingerprint});
      if(epoch===c.state.sessionEpoch){upload=null;await c.updatePage({quiet:true});c.toast('Импортировано строк: '+result.count);}
    }catch(error){tableError(error);}
    finally{if(epoch===c.state.sessionEpoch)c.state.pending--;}
  }

  function click(action,id){
    const data=current();
    if(!data||c.state.pending)return;
    if(action.startsWith('calendar-'))return calendarForm(action.slice(9),id,data);
    if(action.startsWith('class-')||action==='edit-change')return classForm(action,id,data);
    if(action.startsWith('step-')){
      const step=action.slice(5);
      const names={submit:'Передать на согласование',agree:'Согласовать проект',publish:'Утвердить расписание',return:'Вернуть проект'};
      return modal(names[step],data.title,area('comment',step==='return'?'Причина возврата':'Комментарий'),
        v=>request('scheduling/changes/'+data.id+'/step','POST',{...v,step,version:data.version}));
    }
    if(['new-ref','edit-ref'].includes(action))return refForm(action,id,data);
    if(action==='apply-table')return applyTable();
    return teacherForm(action,id,data);
  }

  function init(context){
    c=context;
    document.addEventListener('click',event=>{
      const find=event.target.closest('[data-work-material-find]');
      if(find){searchWorkMaterials(find);return;}
      const el=event.target.closest('[data-op-action]');
      if(!el)return;
      const action=el.dataset.opAction;
      if(action==='calendar-add-period'||action==='calendar-remove-period'){
        const form=el.closest('[data-op-form]');
        const periods=c.$('[data-calendar-periods]',form);
        if(action==='calendar-add-period'&&periods.children.length<32){
          const index=1+Math.max(-1,...[...periods.querySelectorAll('[name^=period_kind_]')].map(x=>Number(x.name.split('_').at(-1))));
          periods.insertAdjacentHTML('beforeend',periodFields({},index));
          periods.lastElementChild.querySelector('select').focus();
        }
        if(action==='calendar-remove-period'&&periods.children.length>1){
          el.closest('[data-calendar-period]').remove();
          form.querySelector('[data-op-action="calendar-add-period"]').focus();
        }
        form.dataset.dirty='true';
        return;
      }
      click(action,Number(el.dataset.id));
    });
    document.addEventListener('keydown',event=>{
      if(event.key==='Enter'&&!event.isComposing&&event.target.matches('[data-work-material-search]')){
        event.preventDefault();
        const control=c.$('[data-work-material-find]',event.target.form);
        if(!control.disabled)searchWorkMaterials(control);
      }
    });
    document.addEventListener('submit',event=>{
      const form=event.target;
      if(form.hasAttribute('data-op-form')){event.preventDefault();submitModal(form);}
      if(form.hasAttribute('data-op-map')&&upload){
        event.preventDefault();
        const values=Object.fromEntries([...new FormData(form)].map(([key,value])=>[key.slice(4),value]));
        previewFile(upload,values);
      }
      if(form.dataset.opFilter){
        event.preventDefault();
        const values=Object.fromEntries(new FormData(form)), type=form.dataset.opFilter;
        const datasetChanged=type==='tables'&&values.dataset!==(q().dataset||current().items[0]?.id);
        const context=['work-review','calendar'].includes(type)?values:type==='tables'?{...values,scope:datasetChanged?undefined:values.scope}:type==='week'?
          {week:values['filter-day']}:type==='teaching-session'?{tab:form.dataset.tab,class_id:values.class_id}:
          {tab:'attendance',day:values['filter-day']};
        c.route(c.state.page,{parts:c.state.routeParts,context});
      }
    });
    document.addEventListener('change',event=>{
      const el=event.target;
      if(el.matches('[data-op-file]'))pickFile(el);
      if(el.matches('[data-op-load]')){
        const options=current().options;
        const selectors={teacher_id:appointmentTeachers(options,el.value),
          subgroup_id:classAudience(options,el.value,'subgroup_id'),student_id:classAudience(options,el.value,'student_id')};
        for(const [name, choices] of Object.entries(selectors)){
          el.form.elements[name].replaceChildren(...choices.map(([id,label])=>new Option(label,id)));
        }
      }
      if(el.closest('[data-op-map]'))c.$('[data-op-action="apply-table"]')?.setAttribute('disabled','');
      const form=el.closest('[data-op-form]');
      if(form){
        form.dataset.dirty='true';
        if(form.classList.contains('work-form'))toggleWorkFields(form);
      }
    });
    document.addEventListener('invalid',event=>{
      if(!event.target.closest('.work-form'))return;
      for(let panel=event.target.closest('details');panel;panel=panel.parentElement.closest('details'))panel.open=true;
    },true);
    document.addEventListener('input',event=>{const form=event.target.closest('[data-op-form]');if(form)form.dataset.dirty='true';});
  }

  function reset(){upload=null;retries.clear();}
  const ui={title,section,list,row,download,input,area,select,yesNo,p,tabs,pageLinks,modal,request,msk,numbers,url,link};
  window.ATLASOperations={pages,has,validParts,cleanQuery,load,render,init,reset,ui};
})();
