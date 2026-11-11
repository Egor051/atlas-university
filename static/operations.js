/* Academic workspace and campus operations. */
(() => {
  'use strict';
  const offices=['scheduler','staff','admin'];
  const workers=[...offices,'teacher'];
  const pages=[
    {id:'teaching',label:'Группы и дисциплины',icon:'graduation',hint:'Списки, оценки, посещаемость, задания и отчёт',roles:['teacher']},
    {id:'teach-schedule',label:'Мои занятия',icon:'calendar',hint:'Расписание преподавателя по неделям',roles:['teacher']},
    {id:'teach-consultations',label:'Мои консультации',icon:'clock',hint:'Время приёма и записи студентов',roles:['teacher']},
    {id:'work-notices',label:'Рабочие уведомления',icon:'bell',hint:'Изменения расписания, заявки и новые работы',roles:[...workers,'union','vuc']},
    {id:'timetable-admin',label:'Расписание занятий',icon:'calendar',hint:'Опубликованные занятия и проекты переноса',roles:offices},
    {id:'schedule-changes',label:'Проекты расписания',icon:'plan',hint:'Подготовка, согласование и утверждение',roles:offices},
    {id:'registry',label:'Аудитории и группы',icon:'pin',hint:'Аудиторный фонд, группы, нагрузка и состав',roles:offices},
    {id:'tables',label:'Импорт и экспорт',icon:'file',hint:'CSV, XLSX, шаблоны, просмотр и журнал',roles:workers},
  ];
  const stateNames={draft:'Черновик',submitted:'На согласовании',agreed:'Согласован',returned:'Возвращён',published:'Опубликован'};
  const actionNames={create:'Новое занятие',update:'Изменение занятия',cancel:'Отмена занятия'};
  const kindNames={lecture:'Лекция',seminar:'Семинар',practice:'Практика',lab:'Лабораторная'};
  const attendanceNames={present:'Присутствовал',absent:'Отсутствовал',excused:'Уважительная причина'};
  const teachTabs={roster:'Студенты',grades:'Ведомость',attendance:'Посещаемость',works:'Задания',report:'Отчёт и история'};
  const registryTabs={rooms:'Аудитории',groups:'Группы',loads:'Нагрузка',students:'Состав групп'};
  const datasetIds=['schedule','rooms','groups','loads','students','grades','attendance'];
  const columnLabels={
    id:'ID записи',version:'Версия',building:'Корпус',code:'Код',capacity:'Мест',kind:'Тип',equipment:'Оборудование',
    accessible:'Безбарьерный доступ',available:'Доступна',program:'Программа',group_id:'ID группы',assignment_id:'ID назначения',
    student_id:'ID студента',load_id:'ID нагрузки',teacher_id:'ID преподавателя',room_id:'ID аудитории',day:'Дата',
    start:'Начало',end:'Окончание',weeks:'Недель',note:'Комментарий',status:'Отметка',score:'Балл',reason:'Основание',
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
    if(['timetable-admin','teach-schedule','registry'].includes(page)&&validDay(query.week))return {week:query.week};
    if(page==='registry'&&!parts.length&&Object.hasOwn(registryTabs,query.tab)&&!(query.tab==='students'&&role()!=='admin'))return {tab:query.tab};
    if(page==='teaching'&&parts.length===1){
      return {...(Object.hasOwn(teachTabs,query.tab)?{tab:query.tab}:{}),
              ...(validDay(query.day)?{day:query.day}:{}),...(int(query.offset)?{offset:Number(query.offset)}:{})};
    }
    if(['schedule-changes','work-notices'].includes(page)&&int(query.offset))return {offset:Number(query.offset)};
    if(page==='tables'){
      return {...(datasetIds.includes(query.dataset)?{dataset:query.dataset}:{}),
              ...(int(query.scope)?{scope:Number(query.scope)}:{}),...(validDay(query.day)?{day:query.day}:{})};
    }
    return {};
  }

  async function load(page,parts,query){
    if(page==='work-notices')return c.api(url('workspace/notices',query));
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
    const detail=await c.api(url(base,{day:query.day}));
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

  function row(heading,summary='',actions=''){
    return `<article class="card compact-row op-row"><div class="row-copy"><h3>${heading}</h3>${summary}</div>${actions?`<div class="op-actions">${actions}</div>`:''}</article>`;
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
    return `<form class="op-inline-form" data-op-filter="${name}">${input('filter-day',label,value,'date','required')}<button class="outline-button" type="submit">Показать</button></form>`;
  }

  function workDetails(data){
    const base='/app/teaching/'+data.detail.id;
    return title(data.work.title,'Срок '+c.dateFmt(data.work.due),button('edit-work','Изменить задание')+link(base+'?tab=works','К заданиям','outline-button'))+
      section('Условия',`<p class="user-text">${esc(data.work.instructions)}</p>`)+section('Отправленные работы',
        list(data.work.submissions,s=>row(esc(s.student),p(s.status==='submitted'?'Версия '+s.version+' · '+c.stamp(s.submitted_at):'Работа отозвана')+
          (s.text?`<p class="user-text">${esc(s.text)}</p>`:'')+safeReference(s.url)+
          (s.feedback.length?`<ul class="op-log">${s.feedback.map(f=>`<li>${esc(f.author)} · ${c.stamp(f.created_at)} · версия ${f.version}${f.score===null?'':' · '+Number(f.score)+' баллов'}<p>${esc(f.comment)}</p></li>`).join('')}</ul>`:''),
          s.status==='submitted'?button('feedback','Дать обратную связь',s.id):''),'Работы ещё не отправлены','После сдачи работа появится здесь.'));
  }

  function safeReference(value){
    try{const ref=new URL(value);if(ref.protocol==='https:'&&!ref.username&&!ref.password)return `<a href="${esc(ref.href)}" rel="noopener noreferrer" target="_blank">Ссылка к работе</a>`;}
    catch{/* Optional reference. */}
    return '';
  }

  function teaching(data){
    if(data.work)return workDetails(data);
    if(!data.students)return title('Группы и дисциплины','Назначения преподавателя.',
      link('/app/teach-schedule','Мои занятия','outline-button')+link('/app/work-notices','Уведомления','outline-button'))+
      list(data.items,x=>row(link('/app/teaching/'+x.id,x.discipline,'school-card-link'),p(x.group)));
    const selected=q().tab||'roster', base='/app/teaching/'+data.id;
    const heading=title(data.discipline,'Группа '+data.group)+tabs('Работа с группой',teachTabs,selected,tab=>url(base,{tab}));
    if(selected==='works'){
      return heading+section('Задания группы',`<div class="op-actions">${button('new-work','Создать задание')}</div>`+
        list(data.works.items,x=>row(link(base+'/works/'+x.id,x.title,'school-card-link'),p('Срок '+c.dateFmt(x.due)+' · сдано '+x.submitted)))+
        pageLinks(base,data.works,20));
    }
    if(selected==='report'){
      const s=data.summary, names=Object.fromEntries(data.students.map(person=>[person.id,person.name]));
      return heading+section('Показатели группы',`<dl class="op-summary"><div><dt>Студентов</dt><dd>${s.student_count}</dd></div>
        <div><dt>Средний балл</dt><dd>${s.average??'—'}</dd></div><div><dt>Сдано работ</dt><dd>${s.submitted}</dd></div>
        ${Object.entries(s.attendance).map(([key,n])=>`<div><dt>${esc(attendanceNames[key]||key)}</dt><dd>${n}</dd></div>`).join('')}</dl>`)+
        section('История операций',data.history.length?`<ol class="op-log">${data.history.map(entry=>{
          const labels={grade:'Оценка',attendance:'Посещаемость',work_created:'Задание опубликовано',work_edited:'Задание изменено',
            feedback:'Работа проверена',consultation:'Назначена консультация',consultation_completed:'Консультация проведена'};
          const value=entry.action==='grade'?`${entry.before.score??'—'} → ${entry.after.score??'—'}`:
            entry.action==='attendance'?`${entry.after.day} · ${attendanceNames[entry.after.status]}`:'';
          return `<li><b>${esc(labels[entry.action]||entry.action)}</b>${p([names[entry.after?.student_id],value].filter(Boolean).join(' · '))}<small>${esc(entry.author)} · ${c.stamp(entry.created_at)} МСК</small></li>`;
        }).join('')}</ol>`:p('Операций пока нет.'));
    }
    const dataset={roster:'students',grades:'grades',attendance:'attendance'}[selected];
    return heading+(selected==='attendance'?dateForm('attendance','День журнала',data.day):'')+
      `<div class="op-actions">${link(url('/app/tables',{dataset,scope:data.id,day:selected==='attendance'?data.day:undefined}),'Работа с таблицей','outline-button')}</div>`+
      list(data.students,person=>{
        const details=selected==='grades'?'Балл: '+(person.grade.score??'—'):selected==='attendance'?
          (attendanceNames[person.attendance.status]||'Отметки пока нет'):person.number;
        return row(esc(person.name),p(details),selected==='grades'?button('grade','Изменить балл',person.id):
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
    const tools=dispatch?button('class-create','Подготовить занятие')+link('/app/schedule-changes','Проекты','outline-button'):
      page==='timetable-admin'?link('/app/schedule-changes','Проекты','outline-button'):'';
    return title(name,'Время занятий — МСК (UTC+3).',tools)+weekControls(base,data.week)+
      list(data.items,x=>row(esc(x.discipline),p(c.dateFmt(x.day,{day:'numeric',month:'long'})+' · '+x.start+'–'+x.end)+
        p([x.kind_label,x.group,x.teacher,x.room].filter(Boolean).join(' · '))+p(x.status==='cancelled'?'Отменено. '+x.note:x.note),
        dispatch&&x.status==='active'?button('class-update','Изменить',x.id)+button('class-cancel','Отменить',x.id):''),
      'Занятий на этой неделе нет','Выберите другую неделю.');
  }

  function changeLabel(value, options){
    const details=value.change, slot=details.slot;
    if(!slot)return p('Занятие №'+value.event_id)+p(details.note);
    const load=options?.loads.find(x=>x.id===slot.load_id), teacher=options?.teachers.find(x=>x.id===slot.teacher_id),
      room=options?.rooms.find(x=>x.id===slot.room_id);
    return p([load?.discipline,load?.group,teacher?.name,room?.code,kindNames[slot.kind]].filter(Boolean).join(' · '))+
      p(c.dateFmt(slot.day)+' · '+slot.start+'–'+slot.end+' МСК'+(slot.weeks>1?' · '+slot.weeks+' недель':''))+p(details.note);
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
    const paths=format=>url('/api/tables/'+meta.id+'/export',{format,scope,day:q().day});
    const chooser=`<form class="op-inline-form" data-op-filter="tables">${select('dataset','Таблица',data.items.map(x=>[x.id,x.title]),meta.id)}
      ${meta.scoped?select('scope','Дисциплина и группа',data.loads.map(x=>[x.id,x.discipline+' · '+x.group]),selected):''}
      ${['attendance','schedule'].includes(meta.id)?input('day',meta.id==='schedule'?'Неделя':'День',q().day||c.today(),'date'):''}
      <button class="outline-button" type="submit">Выбрать</button></form>`;
    const exchange=ready?section('Выгрузка',`<div class="op-actions">${download(paths('csv'),'Скачать CSV')}${download(paths('xlsx'),'Скачать XLSX')}</div>`):
      empty('Выберите назначение','В таблицу попадают данные вашей группы и дисциплины.');
    const add=ready&&meta.editable?section('Загрузка таблицы',
      `<div class="op-actions">${['csv','xlsx'].map(format=>download(url('/api/tables/'+meta.id+'/template',{format}),'Шаблон '+format.toUpperCase())).join('')}</div>
      <div class="field"><label for="ops-file">Файл CSV или XLSX</label><input id="ops-file" type="file" accept=".csv,.xlsx" data-op-file="${meta.id}" data-scope="${scope||''}" aria-describedby="op-table-hint"></div>
      <p class="hint" id="op-table-hint">До 200 строк и 22 КБ. Используйте учебные данные.${meta.id==='schedule'?' Загрузка создаёт черновики для согласования.':''}</p>
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

  function notices(data){
    return title('Рабочие уведомления',data.unread?'Непрочитанных: '+data.unread:'Все уведомления прочитаны')+
      list(data.items,n=>row(esc(n.title),p(n.body)+`<small>${c.stamp(n.created_at)} МСК${n.is_read?'':' · Новое'}</small>`,
        button('notice','Открыть',n.id)))+pageLinks('/app/work-notices',data,30);
  }

  function render(page,data){
    const renderers={teaching,'teach-schedule':()=>timetable(data,page),'teach-consultations':consultations,
      'timetable-admin':()=>timetable(data,page),'schedule-changes':changes,registry,tables:tablePage,'work-notices':notices};
    return renderers[page](data);
  }

  function modal(name,description,fields,run,done,submitLabel='Сохранить'){
    c.modal(c.modalHead(name,description)+`<form data-op-form>${fields}
      <div class="inline-error" role="alert" data-op-error hidden></div><div class="modal-actions">
      <button class="outline-button" type="button" data-action="close-modal">Отмена</button><button class="primary-button" type="submit">${esc(submitLabel)}</button>
      </div></form>`,{label:name});
    callbacks.set(c.$('.modal [data-op-form]'),{run,done});
  }

  async function request(path,method='POST',body){
    const source=body===undefined?undefined:JSON.stringify(body);
    const deduplicate=method==='POST'&&/^(scheduling\/changes|units\/(?:union|vuc)\/cases|teaching\/(?:consultations|\d+\/works(?:\/\d+\/feedback\/\d+)?))$/.test(path);
    const prior=retries.get(path);
    const key=deduplicate?(prior?.source===source?prior.key:crypto.randomUUID()):null;
    if(key)retries.set(path,{source,key});
    const result=await c.api(path,{method,body:source,headers:key?{'Idempotency-Key':key}:{}});
    if(key&&retries.get(path)?.key===key)retries.delete(path);
    return result;
  }

  function teacherForm(action,id,data){
    const base='teaching/'+(data.detail?.id||data.id);
    if(action==='grade'||action==='attendance'){
      const student=data.students.find(x=>x.id===id);
      if(action==='grade')return modal('Оценка',student.name,
        input('score','Балл от 0 до 100',student.grade.score,'number','min="0" max="100" step="1"')+
        area('reason','Основание изменения'),v=>request(base+'/grade','PUT',{
          student_id:id,version:student.grade.version,score:v.score===''?null:Number(v.score),reason:v.reason}));
      return modal('Посещаемость',student.name+' · '+c.dateFmt(data.day),
        select('status','Отметка',Object.entries(attendanceNames),student.attendance.status||'present')+
        area('note','Комментарий',student.attendance.note),v=>request(base+'/attendance','PUT',{
          ...v,student_id:id,day:data.day,version:student.attendance.version}));
    }
    if(action==='new-work'||action==='edit-work'){
      const work=data.work;
      return modal(work?'Изменить задание':'Создать задание',data.detail?.discipline||data.discipline,
        input('title','Название',work?.title,'text','required maxlength="180"')+
        input('due','Срок сдачи',work?.due||c.addDays(c.today(),7),'date','required')+
        area('instructions','Условия задания',work?.instructions,4000),
        v=>work?request(base+'/works/'+work.id,'PATCH',{...v,version:work.version}):request(base+'/works','POST',v));
    }
    if(action==='feedback'){
      const item=data.work.submissions.find(x=>x.id===id);
      return modal('Обратная связь',item.student+' · версия '+item.version,input('score','Балл за работу (необязательно)','','number','min="0" max="100"')+
        area('comment','Комментарий студенту','',2000),v=>request(base+'/works/'+data.work.id+'/feedback/'+id,'POST',
          {submitted_version:item.version,score:v.score===''?null:Number(v.score),comment:v.comment}));
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

  function appointmentTeachers(options,load){
    const selected=options.loads.find(row=>row.id===Number(load));
    return options.teachers.filter(row=>row.discipline_id===selected?.discipline_id).map(row=>[row.id,row.name]);
  }

  function classForm(action,id,data){
    const saved=action==='edit-change'?data.change:null, event=data.items?.find(x=>x.id===id);
    const kind=saved?.action||action.replace('class-','');
    const fields=saved?.slot||event||{};
    const choice=fields.load_id??data.options.loads[0]?.id;
    const parts=kind==='cancel'?'':`<div class="op-form-grid">${select('load_id','Группа и дисциплина',
      data.options.loads.map(x=>[x.id,x.group+' · '+x.discipline]),choice,'data-op-load')}${select('teacher_id','Преподаватель',
      appointmentTeachers(data.options,choice),fields.teacher_id)}${select('room_id','Аудитория',
      data.options.rooms.map(x=>[x.id,x.code+' · '+x.capacity+' мест'+(x.available?'':' · недоступна')]),fields.room_id)}
      ${select('kind','Вид занятия',Object.entries(kindNames),fields.kind||'seminar')}
      ${input('day','Дата',fields.day||c.addDays(c.today(),1),'date','required')}${input('start','Начало',fields.start||'17:00','time','required')}
      ${input('end','Окончание',fields.end||'18:00','time','required')}${kind==='create'?input('weeks','Повторять недель',fields.weeks||1,'number','required min="1" max="16"'):''}</div>
      ${input('equipment','Оборудование через запятую',fields.equipment,'text','maxlength="160"')}`;
    const eventId=saved?.event_id||event?.id, eventVersion=saved?.event_version||event?.version;
    return modal(actionNames[kind],'Параметры проекта. Время вводится по Москве.',parts+area('note',kind==='cancel'?'Причина отмены':'Комментарий',saved?.note||event?.note),
      v=>{
        const note=v.note;delete v.note;
        const body={action:kind,note,...(eventId?{event_id:eventId,event_version:eventVersion}:{}),
          ...(kind==='cancel'?{}:{slot:numbers({...v,weeks:v.weeks||1},'load_id','teacher_id','room_id','weeks')})};
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
        select('kind','Тип помещения',Object.entries({lecture:'Лекционная',seminar:'Семинарская',lab:'Лаборатория'}),record.kind)+
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
    const epoch=c.state.sessionEpoch, values=Object.fromEntries(new FormData(form)), controls=[...form.elements], error=c.$('[data-op-error]',form);
    c.state.pending++;controls.forEach(control=>control.disabled=true);error.hidden=true;
    let result;
    try{result=await handler.run(values);}
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
    if(action.startsWith('class-')||action==='edit-change')return classForm(action,id,data);
    if(action.startsWith('step-')){
      const step=action.slice(5);
      const names={submit:'Передать на согласование',agree:'Согласовать проект',publish:'Утвердить расписание',return:'Вернуть проект'};
      return modal(names[step],data.title,area('comment',step==='return'?'Причина возврата':'Комментарий'),
        v=>request('scheduling/changes/'+data.id+'/step','POST',{...v,step,version:data.version}));
    }
    if(['new-ref','edit-ref'].includes(action))return refForm(action,id,data);
    if(action==='apply-table')return applyTable();
    if(action==='notice')return openNotice(id);
    return teacherForm(action,id,data);
  }

  async function openNotice(id){
    const epoch=c.state.sessionEpoch,href=c.state.routeHref;
    try{
      const result=await request('workspace/notices/'+id+'/read','POST');
      if(epoch!==c.state.sessionEpoch||href!==c.state.routeHref)return;
      const target=new URL(result.target,location.origin);
      const [prefix,page,...parts]=target.pathname.split('/').filter(Boolean);
      if(target.origin===location.origin&&prefix==='app')await c.route(page,{parts,context:Object.fromEntries(target.searchParams)});
    }catch(error){if(!error.stale)c.toast(error.message);}
  }

  function init(context){
    c=context;
    document.addEventListener('click',event=>{
      const el=event.target.closest('[data-op-action]');
      if(el)click(el.dataset.opAction,Number(el.dataset.id));
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
        const context=type==='tables'?{...values,scope:datasetChanged?undefined:values.scope}:type==='week'?
          {week:values['filter-day']}:{tab:'attendance',day:values['filter-day']};
        c.route(c.state.page,{parts:c.state.routeParts,context});
      }
    });
    document.addEventListener('change',event=>{
      const el=event.target;
      if(el.matches('[data-op-file]'))pickFile(el);
      if(el.matches('[data-op-load]')){
        const choices=appointmentTeachers(current().options,el.value);
        const teachers=c.$('#op-teacher_id');
        teachers.replaceChildren(...choices.map(([id,name])=>new Option(name,id)));
      }
      if(el.closest('[data-op-map]'))c.$('[data-op-action="apply-table"]')?.setAttribute('disabled','');
      const form=el.closest('[data-op-form]');if(form)form.dataset.dirty='true';
    });
    document.addEventListener('input',event=>{const form=event.target.closest('[data-op-form]');if(form)form.dataset.dirty='true';});
  }

  function reset(){upload=null;retries.clear();}
  const ui={title,section,list,row,download,input,area,select,yesNo,p,tabs,pageLinks,modal,request,msk,numbers,url,link};
  window.ATLASOperations={pages,has,validParts,cleanQuery,load,render,init,reset,ui};
})();
