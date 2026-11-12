/* The university directory, teaching library and private messages use authenticated APIs. */
(() => {
  'use strict';
  const everyone=['student','staff','teacher'];
  const publishers=['staff','teacher'];
  const pages=[
    {id:'university',label:'Университет',icon:'pin',hint:'Институты, кафедры и преподаватели',roles:everyone},
    {id:'materials',label:'Учебные материалы',icon:'book',hint:'Лекции, презентации, задания и скачивание',roles:everyone},
    {id:'materials-admin',label:'Публикации',icon:'file',hint:'Добавить, изменить или удалить материал',roles:publishers},
    {id:'direct',label:'Личные сообщения',icon:'send',hint:'Переписка с преподавателями и учебным офисом',roles:everyone},
    {id:'teacher',label:'Кабинет преподавателя',icon:'home',hint:'Занятия, консультации, публикации и диалоги',roles:['teacher']},
  ];
  const kinds=['lecture','guide','slides','practice','lab','extra'];
  const directoryKinds=[['faculty','Институты и факультеты'],['department','Кафедры'],['teacher','Преподаватели']];
  const weekdays=['Понедельник','Вторник','Среда','Четверг','Пятница','Суббота','Воскресенье'];
  const roleLabels={student:'Студент',teacher:'Преподаватель',staff:'Учебный офис'};
  const drafts=new Map(), receipts=new Map(), reading=new Set();
  const dayFormat=new Intl.DateTimeFormat('ru-RU',{timeZone:'Europe/Moscow',day:'numeric',month:'long',year:'numeric'});
  const timeFormat=new Intl.DateTimeFormat('ru-RU',{timeZone:'Europe/Moscow',hour:'2-digit',minute:'2-digit'});
  let c, unread=0, poll, historyPoll;
  const esc=value=>c.esc(value);
  const icon=name=>c.icon(name);
  const isStudent=()=>c.state.user.role==='student';
  const has=page=>pages.some(item=>item.id===page);
  const id=value=>/^[1-9]\d{0,9}$/.test(value)&&Number(value)<=2147483647;
  const path=(base,query={})=>{
    const params=new URLSearchParams(Object.entries(query).filter(([,value])=>value!==undefined&&value!==null&&value!=='')).toString();
    return base+(params?'?'+params:'');
  };
  const appLink=(href,label,cls='mini-link')=>`<a class="${cls}" href="${esc(href)}" data-app-link>${esc(label)}</a>`;
  const title=(name,description='',actions='')=>c.head('',esc(name),esc(description),actions);
  const section=(name,content)=>`<section class="card card-pad school-section"><h2>${esc(name)}</h2>${content}</section>`;
  const empty=(name,description)=>c.empty('book',name,description);
  const safeSearch=value=>String(value??'').replace(/[\x00-\x1f]/g,'').trim().slice(0,100);

  function validParts(page,parts){
    if(!parts.length)return false;
    if(page==='university')return parts.length<=3&&parts.every(part=>/^[a-z0-9-]{1,60}$/.test(part));
    return ['materials','direct'].includes(page)&&parts.length===1&&id(parts[0]);
  }

  function cleanQuery(page,query,parts){
    const q=safeSearch(query.q), rq=safeSearch(query.rq);
    if(page==='university'&&!parts.length){
      return {
        ...(q?{q}:{}),
        ...(/^[a-z0-9-]{1,60}$/.test(query.faculty||'')?{faculty:query.faculty}:{}),
        ...(directoryKinds.some(([value])=>value===query.kind)?{kind:query.kind}:{}),
      };
    }
    if((page==='materials'&&!parts.length)||page==='materials-admin'){
      return {
        ...(q?{q}:{}),
        ...(kinds.includes(query.kind)?{kind:query.kind}:{}),
        ...Object.fromEntries(['discipline','teacher','offset'].filter(key=>id(query[key])).map(key=>[key,Number(query[key])])),
      };
    }
    if(page==='direct'){
      return {
        ...(parts.length&&id(query.before)?{before:Number(query.before)}:{}),
        ...(!parts.length&&isStudent()&&id(query.recipient)?{recipient:Number(query.recipient)}:{}),
        ...(q?{q}:{}),
        ...(!parts.length&&isStudent()&&rq?{rq}:{}),
        ...(id(query.offset)?{offset:Number(query.offset)}:{}),
      };
    }
    return {};
  }

  async function load(page,parts,query){
    if(page==='university')return c.api(path(['university',...parts].join('/'),query));
    if(page==='teacher')return c.api('university/me');
    if(page==='materials')return c.api(path(['materials',...parts].join('/'),query));
    if(page==='materials-admin'){
      const [catalog,assignments]=await Promise.all([c.api(path('materials',{...query,mine:true})),c.api('materials/assignments')]);
      return {...catalog,assignments:assignments.items};
    }
    const [inbox,contacts,thread]=await Promise.all([
      c.api(path('direct/dialogs',{q:query.q,offset:query.offset})),
      isStudent()&&!parts.length&&!query.recipient?c.api(path('direct/recipients',{q:query.rq})):null,
      loadThread(parts,query),
    ]);
    return {...thread,inbox,contacts:contacts?.items};
  }

  async function loadThread(parts,query){
    let dialogId=parts[0];
    if(query.recipient){
      const person=await c.api('direct/recipients/'+query.recipient);
      dialogId=person.dialog_id;
      if(!dialogId)return {mode:'compose',person};
    }
    if(!dialogId)return {mode:'list'};
    const dialog=await c.api(path('direct/dialogs/'+dialogId,{before:query.before}));
    return {...dialog,mode:'dialog',title:dialog.person.name};
  }

  function input(name,label,value='',options={}){
    return `<div class="field"><label for="school-${name}">${esc(label)}</label><input id="school-${name}" type="${options.type||'text'}" name="${name}" value="${esc(value)}" maxlength="${options.max||100}" ${options.required?'required':''}></div>`;
  }

  function select(name,label,choices,value,required=false){
    return `<div class="field"><label for="school-${name}">${esc(label)}</label><select id="school-${name}" name="${name}" ${required?'required':''}>${choices.map(([key,text])=>`<option value="${esc(key)}" ${String(key)===String(value??'')?'selected':''}>${esc(text)}</option>`).join('')}</select></div>`;
  }

  function searchForm(page,fields,reset=false){
    return `<form class="school-filter" data-school-filter="${page}">${fields}<div class="school-actions"><button class="outline-button" type="submit">${icon('search')} Найти</button>${reset?appLink('/app/'+page,'Сбросить'):''}</div></form>`;
  }

  function pager(page,data,query=c.state.routeContext){
    const hasNext=data.offset+data.limit<data.total;
    if(!data.offset&&!hasNext)return '';
    const url=offset=>path('/app/'+page,{...query,offset:offset||undefined});
    return `<nav class="campus-pagination" aria-label="Страницы результатов"><span>${data.total?`${data.offset+1}–${Math.min(data.offset+data.limit,data.total)} из ${data.total}`:'Нет результатов'}</span><div>${data.offset?appLink(url(Math.max(0,data.offset-data.limit)),'Предыдущая','outline-button'):''}${hasNext?appLink(url(data.offset+data.limit),'Следующая','outline-button'):''}</div></nav>`;
  }

  function directoryCards(items){
    if(!items.length)return empty('Ничего не найдено','Попробуйте изменить запрос или фильтры.');
    return `<div class="campus-grid">${items.map(row=>`<article class="card campus-tile school-tile"><h2>${appLink(row.href,row.title,'school-card-link')}</h2>${row.position?`<p class="school-meta">${esc(row.position)} · ${esc(row.department)}</p>`:''}<p>${esc(row.description)}</p>${row.subjects?.length?`<p>${esc(row.subjects.join(', '))}</p>`:''}</article>`).join('')}</div>`;
  }

  function disciplineList(rows){
    if(!rows.length)return '<p class="compact-empty">Дисциплины пока не добавлены.</p>';
    return `<ul class="school-list">${rows.map(row=>`<li><strong>${esc(row.title)}</strong><p>${esc(row.description)}</p>${appLink(path('/app/materials',{discipline:row.id}),'Материалы дисциплины')}</li>`).join('')}</ul>`;
  }

  function teachingSchedule(rows,kind){
    const matching=rows.filter(row=>row.kind===kind);
    if(!matching.length)return '<p class="compact-empty">В расписании пока нет записей.</p>';
    return `<ul class="school-list school-schedule">${matching.map(row=>`<li><strong>${weekdays[row.weekday]} · ${esc(row.starts)}–${esc(row.ends)}</strong><p>${esc(row.discipline)} · ${esc(row.room)}</p></li>`).join('')}</ul>`;
  }

  function profile(data,own=false){
    const actions=own?appLink('/app/teaching','Группы и дисциплины','primary-button')+appLink('/app/materials-admin','Публикации','outline-button')+appLink('/app/direct','Личные сообщения','outline-button')+appLink('/app/notifications','Уведомления','outline-button')+appLink('/app/university','Каталог университета','outline-button')
      :data.can_message?appLink(path('/app/direct',{recipient:data.recipient_id}),'Написать преподавателю','primary-button')+
        appLink(path('/app/consultations',{subject:data.disciplines[0]?.title}),'Запись на консультацию','outline-button'):'';
    return title(own?'Кабинет преподавателя':data.title,[own?data.title:'',data.position,data.department].filter(Boolean).join(' · '),actions)+
      `<div class="school-detail-grid">${section('Академическая информация',`<p>${esc(data.description)}</p>`)}${section('Дисциплины',disciplineList(data.disciplines))}
      ${section('Занятия · МСК',teachingSchedule(data.schedule,'lesson'))}${section('Консультации · МСК',teachingSchedule(data.schedule,'consultation'))}</div>`+
      section('Учебные материалы',data.materials.length?materialCards(data.materials)+appLink(path('/app/materials',{teacher:data.id}),'Все материалы преподавателя')
        :'<p class="compact-empty">У преподавателя пока нет публикаций.</p>');
  }

  function directory(data){
    if(data.kind==='teacher')return profile(data);
    if(data.kind!=='directory'){
      return title(data.title,data.description)+section('Направления работы',`<p>${esc(data.directions)}</p>`)+
        section(data.kind==='faculty'?'Кафедры':'Преподаватели',directoryCards(data.items))+
        section('Связанные дисциплины',disciplineList(data.disciplines));
    }
    const q=c.state.routeContext;
    const related=isStudent()?appLink('/app/contacts','Контакты и корпуса','outline-button')+
      appLink('/app/union','Профсоюз','outline-button')+appLink('/app/vuc','ВУЦ','outline-button'):'';
    return title('Университет','Институты, кафедры и преподаватели.',related)+
      searchForm('university',input('q','Поиск по каталогу',q.q)+select('faculty','Подразделение',[['','Все подразделения'],...data.faculties.map(row=>[row.slug,row.title])],q.faculty)+
        select('kind','Показывать',[['','Всё'],...directoryKinds],q.kind),Object.keys(q).length>0)+directoryCards(data.items);
  }

  function fileLink(row){
    return `<a class="outline-button" href="${esc(row.file_url)}" download>${icon('download')} Скачать HTML</a>`;
  }

  function materialCards(items){
    return `<div class="campus-grid">${items.map(row=>`<article class="card campus-tile school-tile"><p class="school-meta">${esc(row.kind_label)} · ${c.dateFmt(row.created_at,{day:'numeric',month:'short',year:'numeric'})}</p><h2>${appLink('/app/materials/'+row.id,row.title,'school-card-link')}</h2><p>${esc(row.discipline.title)} · ${esc(row.author.title)}</p><p>${esc(row.description)}</p></article>`).join('')}</div>`;
  }

  function materialFilters(page,data){
    const query=c.state.routeContext;
    return searchForm(page,input('q','Название, дисциплина или автор',query.q)+
      select('kind','Тип материала',[['','Все типы'],...Object.entries(data.kinds)],query.kind)+
      select('discipline','Дисциплина',[['','Все дисциплины'],...data.disciplines.map(row=>[row.id,row.title])],query.discipline)+
      (query.teacher?`<input type="hidden" name="teacher" value="${Number(query.teacher)}">`:''),Object.keys(query).length>0);
  }

  function library(data){
    if(!data.sections){
      return title('Учебные материалы','Лекции, презентации и задания по дисциплинам.',
        isStudent()?appLink('/app/library','Книги и формуляр','outline-button'):appLink('/app/materials-admin','Публикации','outline-button'))+
        materialFilters('materials',data)+(data.items.length?materialCards(data.items):empty('Материалы не найдены','Измените поиск или фильтры.'))+pager('materials',data);
    }
    const slides=data.kind==='slides';
    return title(data.title,data.description,fileLink(data)+(data.can_edit?editButton(data,'edit','Изменить'):''))+
      `<div class="school-material-meta"><span>${esc(data.kind_label)} · ${esc(data.discipline.title)} · ${c.dateFmt(data.created_at,{day:'numeric',month:'long',year:'numeric'})}</span>${appLink(data.author.href,data.author.title)}</div>
      ${slides?`<nav class="school-slide-nav" aria-label="Слайды">${data.sections.map((row,i)=>`<button type="button" class="mini-link" data-school-slide="${i}">${esc(row.heading)}</button>`).join('')}</nav>`:''}
      <article class="card card-pad school-reader ${slides?'school-slides':''}">${data.sections.map((row,i)=>`<section id="material-part-${i}" tabindex="-1">${row.heading?`<h2>${esc(row.heading)}</h2>`:''}${row.paragraphs.map(text=>`<p>${esc(text)}</p>`).join('')}</section>`).join('')}</article>`;
  }

  function editButton(row,action,label){
    return `<button type="button" class="outline-button" data-school-material="${action}" data-id="${Number(row.id)}" aria-label="${esc(label+': '+row.title)}">${esc(label)}</button>`;
  }

  function manage(data){
    return title('Публикации',c.state.user.role==='teacher'?'Материалы ваших дисциплин.':'Учебные материалы по всем дисциплинам.',
      data.assignments.length?`<button type="button" class="primary-button" data-school-material="new">${icon('plus')} Опубликовать материал</button>`:'')+
      materialFilters('materials-admin',data)+
      (data.items.length?`<div class="compact-list">${data.items.map(row=>`<article class="card compact-row"><div class="row-copy"><h2>${appLink('/app/materials/'+row.id,row.title,'school-card-link')}</h2><p>${esc(row.discipline.title)} · ${esc(row.kind_label)}</p></div><div class="school-actions">${editButton(row,'edit','Изменить')}${editButton(row,'delete','Удалить')}</div></article>`).join('')}</div>`
        :empty('Материалов по фильтру нет',data.assignments.length?'Измените фильтр или опубликуйте материал.':'Для публикации нужна назначенная дисциплина.'))+pager('materials-admin',data);
  }

  function compose(target,type){
    const key=type+':'+target;
    return `<form class="school-compose" data-school-form="message" data-target="${target}" data-mode="${type}">
      <div class="field"><label class="sr-only" for="direct-message">Сообщение</label><textarea id="direct-message" name="message" placeholder="Напишите сообщение" maxlength="3000" rows="2" required>${esc(drafts.get(key)||'')}</textarea></div>
      <div class="inline-error" role="alert" data-school-error hidden></div>
      <button type="submit" class="primary-button">${icon('send')} Отправить</button></form>`;
  }

  function dialogRows(data){
    const {q,offset}=c.state.routeContext;
    return data.inbox.items.length?data.inbox.items.map(row=>{
      const current=row.id===data.id;
      return `<a class="messenger-item" href="${esc(path('/app/direct/'+row.id,{q,offset}))}" data-app-link ${current?'aria-current="page"':''}>
        <span class="messenger-avatar" aria-hidden="true">${esc(row.person.initials)}</span><span class="messenger-person"><b>${esc(row.person.name)}</b><small>${esc(row.preview)}</small></span>
        <span class="messenger-meta"><time datetime="${esc(row.updated_at)}">${c.stamp(row.updated_at)}</time>
        ${row.unread_count?`<span class="campus-pill" aria-label="Непрочитанных: ${Number(row.unread_count)}">${Number(row.unread_count)}</span>`:''}</span></a>`;
    }).join(''):`<p class="compact-empty">${q?'Собеседники по запросу не найдены.':'Диалогов пока нет.'}</p>`;
  }

  function messages(data){
    if(!data.messages.length)return '<p class="compact-empty">В переписке пока нет сообщений.</p>';
    let previous;
    const rows=data.messages.map(row=>{
      const when=new Date(row.created_at), day=dayFormat.format(when);
      const heading=day!==previous?`<li class="messenger-day"><time datetime="${esc(row.created_at)}">${day}</time></li>`:'';
      previous=day;
      return `${heading}<li class="messenger-bubble ${row.mine?'mine':'received'}" data-message-id="${Number(row.id)}"><span class="sr-only">${esc(row.mine?'Вы':data.person.name)}</span>
        <p>${esc(row.body)}</p><footer><time datetime="${esc(row.created_at)}">${timeFormat.format(when)} МСК</time>${row.mine?`<span>${row.is_read?'Прочитано':'Отправлено'}</span>`:''}</footer></li>`;
    });
    return `<ol class="messenger-messages school-conversation" aria-label="Сообщения">${rows.join('')}</ol>`;
  }

  function direct(data){
    const query=c.state.routeContext, {q,rq,offset}=query;
    const listUrl=path('/app/direct',{q,offset});
    const contacts=data.contacts?`<details class="messenger-contacts" ${rq||!data.inbox.total?'open':''}><summary>Новый диалог</summary>
      ${searchForm('direct',input('rq','Поиск адресата',rq)+(q?`<input type="hidden" name="q" value="${esc(q)}">`:''))}
      ${data.contacts.length?`<ul class="school-list school-contacts">${data.contacts.map(row=>`<li>${appLink(path('/app/direct',{recipient:row.id,q,offset}),row.name,'school-card-link')}<p>${esc(row.label)}</p></li>`).join('')}</ul>`:'<p class="compact-empty">Адресаты по запросу не найдены.</p>'}</details>`:'';
    const sidebar=`<nav class="messenger-inbox" aria-label="Диалоги">${searchForm('direct',input('q','Поиск диалога',q),Boolean(q))}${contacts}
      <div class="messenger-items" data-messenger-items>${dialogRows(data)}</div>${pager('direct',data.inbox)}</nav>`;
    const back=appLink(listUrl,'К списку диалогов','mini-link messenger-back');
    let panel='<div class="messenger-placeholder compact-empty">Выберите диалог, чтобы открыть переписку.</div>';
    if(data.mode!=='list'){
      const other=data.person;
      const history=data.mode==='dialog'?`<div class="messenger-history" tabindex="0" aria-label="История переписки" data-messenger-history>
        ${data.older_before?'<button type="button" class="mini-link messenger-older" data-messenger-older>Более ранние сообщения</button>':''}
        <div data-messenger-messages>${messages(data)}</div></div>`:'<div class="messenger-placeholder compact-empty">Здесь начнётся переписка.</div>';
      const footer=data.mode==='compose'?compose(other.id,'recipient'):query.before?appLink(path('/app/direct/'+data.id,{q,offset}),'К последним сообщениям','outline-button')+compose(data.id,'dialog'):compose(data.id,'dialog');
      panel=`<section class="messenger-thread" aria-labelledby="messenger-name"><header class="messenger-header">${back}<span class="messenger-avatar" aria-hidden="true">${esc(other.initials)}</span>
        <div><h2 id="messenger-name">${esc(other.name)}</h2><p>${esc(other.label||roleLabels[other.role]||'')}</p></div></header>${history}${footer}</section>`;
    }
    return title('Личные сообщения')+`<div class="card messenger ${data.mode==='list'?'messenger-list-view':'messenger-thread-view'}">${sidebar}${panel}</div><p class="sr-only" role="status" data-messenger-update></p>`;
  }

  const renderers={university:directory,teacher:data=>profile(data,true),materials:library,'materials-admin':manage,direct};

  async function materialModal(button){
    const action=button.dataset.schoolMaterial, materialId=Number(button.dataset.id);
    const epoch=c.state.sessionEpoch, loadId=c.state.loadingId, modalId=c.state.modalId;
    button.disabled=true;
    try{
      const [row,options]=await Promise.all([
        materialId?c.api('materials/'+materialId):Promise.resolve(null),
        action!=='delete'?c.api('materials/assignments'):Promise.resolve(null),
      ]);
      if(epoch!==c.state.sessionEpoch||loadId!==c.state.loadingId||modalId!==c.state.modalId||!button.isConnected)return;
      if(action==='delete'){
        c.modal(c.modalHead('Удалить материал',row.title)+
          `<form data-school-form="delete" data-id="${row.id}" data-version="${row.version}">
          <p>Материал исчезнет из каталога, профиля преподавателя и по прямой ссылке.</p>
          <div class="inline-error" data-school-error role="alert" hidden></div><div class="modal-actions">
          <button type="button" class="outline-button" data-action="close-modal">Отмена</button><button type="submit" class="danger-button">Удалить</button></div></form>`,{label:'Удалить материал'});
        return;
      }
      const name=row?'Изменить материал':'Опубликовать материал';
      const assignments=options.items.map(item=>[item.id,item.discipline+' · '+item.author]);
      c.modal(c.modalHead(name,'Файл для просмотра и скачивания будет создан из текста.')+
        `<form data-school-form="material" data-id="${row?.id||''}" data-version="${row?.version||''}">
        ${select('assignment_id','Дисциплина и автор',assignments,row?.assignment_id??assignments[0]?.[0],true)}
        ${select('kind','Тип материала',Object.entries(options.kinds),row?.kind??'lecture',true)}
        ${input('title','Название',row?.title,{max:180,required:true})}
        <div class="field"><label for="school-description">Описание</label><textarea id="school-description" name="description" rows="2" minlength="10" maxlength="600" required>${esc(row?.description||'')}</textarea></div>
        <div class="field"><label for="school-file">Загрузить текст из файла</label><input id="school-file" type="file" accept=".txt,.md" aria-describedby="school-file-hint"><p class="hint" id="school-file-hint">TXT или MD в UTF-8. Текст появится в редакторе.</p></div>
        <div class="field"><label for="school-body">Текст материала</label><textarea id="school-body" name="body" rows="8" minlength="20" maxlength="6000" required aria-describedby="school-body-hint">${esc(row?.body||'')}</textarea><p class="hint" id="school-body-hint">Начните заголовок с «## » и разделяйте абзацы пустой строкой. Для презентации добавьте минимум два слайда с заголовками и текстом.</p></div>
        <div class="inline-error" data-school-error role="alert" hidden></div><div class="modal-actions">
        <button type="button" class="outline-button" data-action="close-modal">Отмена</button><button class="primary-button" type="submit">${row?'Сохранить изменения':'Опубликовать'}</button></div></form>`,{label:name});
    }catch(error){if(!error.stale)c.toast(error.message);}
    finally{button.disabled=false;}
  }

  function mutation(form){
    const type=form.dataset.schoolForm, values=Object.fromEntries(new FormData(form));
    if(type==='delete')return {endpoint:`materials/${Number(form.dataset.id)}?version=${Number(form.dataset.version)}`,method:'DELETE'};
    if(type==='material'){
      values.assignment_id=Number(values.assignment_id);
      if(form.dataset.id)return {endpoint:'materials/'+Number(form.dataset.id),method:'PATCH',
        body:JSON.stringify({...values,version:Number(form.dataset.version)})};
      return {endpoint:'materials',method:'POST',body:JSON.stringify(values)};
    }
    const target=Number(form.dataset.target), message=values.message.trim();
    return form.dataset.mode==='recipient'?{endpoint:'direct/dialogs',method:'POST',body:JSON.stringify({recipient_id:target,message})}
      :{endpoint:`direct/dialogs/${target}/messages`,method:'POST',body:JSON.stringify({message})};
  }

  async function submit(form){
    if(c.state.pending)return;
    const epoch=c.state.sessionEpoch, type=form.dataset.schoolForm, errorBox=c.$('[data-school-error]',form);
    const {endpoint,method,body}=mutation(form);
    let headers;
    if(method==='POST'){
      const saved=receipts.get(endpoint);
      const key=saved?.body===body?saved.key:crypto.randomUUID();
      receipts.set(endpoint,{body,key});
      headers={'Idempotency-Key':key};
    }
    c.state.pending++;errorBox.hidden=true;
    const controls=Array.from(form.elements).filter(control=>type!=='message'||control.type==='submit');
    const messageInput=type==='message'?form.elements.message:null;
    if(messageInput)messageInput.readOnly=true;
    controls.forEach(control=>{control.disabled=true;});
    let result;
    try{result=await c.api(endpoint,{method,body,headers});}
    catch(error){
      if(!error.stale&&form.isConnected){errorBox.hidden=false;errorBox.textContent=error.message;}
      if(!error.stale&&epoch===c.state.sessionEpoch){controls.forEach(control=>{control.disabled=false;});c.showFieldErrors(error,form);}
    }finally{
      if(epoch===c.state.sessionEpoch){
        c.state.pending=Math.max(0,c.state.pending-1);
        controls.forEach(control=>{control.disabled=false;});
        if(messageInput)messageInput.readOnly=false;
      }
    }
    if(!result||epoch!==c.state.sessionEpoch)return;
    receipts.delete(endpoint);
    if(type==='message'){
      drafts.delete(form.dataset.mode+':'+form.dataset.target);
      c.toast('Сообщение отправлено.');
      if(c.state.routeParts[0]!==String(result.dialog_id)||c.state.routeContext.before){
        const {q,offset}=c.state.routeContext;
        await c.route('direct',{parts:[String(result.dialog_id)],context:{q,offset},replace:form.dataset.mode==='recipient'||Boolean(c.state.routeContext.before)});
      }
      else await c.updatePage({quiet:true});
      if(epoch===c.state.sessionEpoch&&c.state.page==='direct')c.$('#direct-message')?.focus({preventScroll:true});
      return;
    }
    c.closeModal({force:true});
    c.toast(type==='delete'?'Материал удалён.':method==='POST'?'Материал опубликован.':'Изменения сохранены.');
    await c.updatePage({quiet:true});
  }

  function unreadBadge(dot=false){
    return `<span class="${dot?'dot':'direct-count'}" data-direct-unread ${unread?'':'hidden'}>${dot?'':`<span class="sr-only">Непрочитанных: </span><span data-direct-count>${unread}</span>`}</span>`;
  }

  function pollUnread(){
    if(!c.state.user||document.hidden||poll)return poll;
    const epoch=c.state.sessionEpoch;
    const request=c.api('direct/unread',{quietAuth:true}).then(data=>{
      if(epoch!==c.state.sessionEpoch)return;
      unread=data.unread_count;
      for(const badge of c.$$('[data-direct-unread]')){
        badge.hidden=!unread;
        const count=c.$('[data-direct-count]',badge);
        if(count)count.textContent=unread>99?'99+':unread;
        else badge.parentElement.setAttribute('aria-label',unread?`Личные сообщения, непрочитанных: ${unread}`:'Личные сообщения');
      }
      pollConversation();
    }).catch(()=>{}).finally(()=>{if(poll===request)poll=null;});
    poll=request;
    return poll;
  }

  const atEnd=history=>history.scrollHeight-history.scrollTop-history.clientHeight<48;

  function afterRender(page,data){
    if(page!=='direct'||data.mode!=='dialog')return;
    const history=c.$('[data-messenger-history]');
    if(history&&!c.state.routeContext.before)history.scrollTop=history.scrollHeight;
    markThreadRead(data);
  }

  async function markThreadRead(data){
    if(!data?.read_through||!data.unread_count)return;
    const epoch=c.state.sessionEpoch, through=data.read_through, key=[epoch,data.id,through].join(':');
    if(reading.has(key))return;
    reading.add(key);
    try{
      await c.api(`direct/dialogs/${data.id}/read`,{method:'POST',body:JSON.stringify({through_id:through})});
      if(epoch===c.state.sessionEpoch&&data.read_through===through){
        data.unread_count=0;
        const row=data.inbox.items.find(item=>item.id===data.id);
        if(row)row.unread_count=0;
        const badge=c.$('[data-messenger-items] [aria-current="page"] .campus-pill');
        if(c.state.data.direct===data)badge?.remove();
        pollUnread();c.refreshUnread();
      }
    }catch(error){if(!error.stale&&c.state.data.direct===data)c.toast(error.message);}
    finally{reading.delete(key);}
  }

  async function olderMessages(button){
    const data=c.state.data.direct, history=c.$('[data-messenger-history]');
    if(button.disabled||!data?.older_before||!history)return;
    button.disabled=true;
    try{
      const older=await c.api(path('direct/dialogs/'+data.id,{before:data.older_before}));
      if(c.state.page!=='direct'||c.state.data.direct!==data)return;
      const top=history.scrollTop, height=history.scrollHeight;
      data.messages=[...older.messages,...data.messages];
      data.older_before=older.older_before;
      c.$('[data-messenger-messages]',history).innerHTML=messages(data);
      if(!data.older_before){button.remove();history.focus({preventScroll:true});}
      history.scrollTop=top+history.scrollHeight-height;
    }catch(error){if(!error.stale)c.toast(error.message);}
    finally{button.disabled=false;}
  }

  function pollConversation(){
    const data=c.state.data.direct;
    if(c.state.page!=='direct'||!data||historyPoll||c.state.pending||c.state.routeContext.before)return;
    const epoch=c.state.sessionEpoch, href=c.state.routeHref;
    const current=()=>epoch===c.state.sessionEpoch&&href===c.state.routeHref&&c.state.data.direct===data&&!c.state.pending;
    const {q,offset}=c.state.routeContext;
    const request=Promise.all([
      c.api(path('direct/dialogs',{q,offset}),{quietAuth:true}),
      data.mode==='dialog'?c.api('direct/dialogs/'+data.id,{quietAuth:true}):null,
    ]).then(([inbox,latest])=>{
      if(!current())return;
      const list=c.$('[data-messenger-items]');
      if(list&&!list.contains(document.activeElement)&&JSON.stringify(data.inbox.items)!==JSON.stringify(inbox.items)){
        data.inbox=inbox;list.innerHTML=dialogRows(data);
      }
      const history=c.$('[data-messenger-history]');
      if(!history||!latest)return;
      const bottom=atEnd(history), through=data.read_through;
      const previousFirst=data.messages[0]?.id, latestFirst=latest.messages[0]?.id;
      const older=data.messages.filter(row=>row.id<latestFirst);
      const next=[...older,...latest.messages];
      const changed=next.length!==data.messages.length||next.some((row,index)=>row.id!==data.messages[index]?.id||row.is_read!==data.messages[index]?.is_read);
      data.read_through=latest.read_through;data.unread_count=latest.unread_count;
      if(changed){
        data.messages=next;
        if(previousFirst===undefined||!older.length)data.older_before=latest.older_before;
        c.$('[data-messenger-messages]',history).innerHTML=messages(data);
        if(bottom)history.scrollTop=history.scrollHeight;
        if(through!==latest.read_through)c.$('[data-messenger-update]').textContent='В переписке появились новые сообщения.';
      }
      if(bottom)markThreadRead(data);
    }).catch(()=>{}).finally(()=>{if(historyPoll===request)historyPoll=null;});
    historyPoll=request;
  }

  function init(context){
    c=context;
    document.addEventListener('click',event=>{
      const older=event.target.closest('[data-messenger-older]');
      if(older){olderMessages(older);return;}
      const material=event.target.closest('[data-school-material]');
      if(material){if(!c.state.pending)materialModal(material);return;}
      const slide=event.target.closest('[data-school-slide]');
      if(slide){
        const section=c.$('#material-part-'+Number(slide.dataset.schoolSlide));
        section?.focus();
      }
    });
    document.addEventListener('submit',event=>{
      const form=event.target;
      if(form.dataset.schoolFilter){
        event.preventDefault();
        const context=Object.fromEntries(new FormData(form));
        const parts=form.dataset.schoolFilter==='direct'&&form.elements.q&&!form.elements.rq?c.state.routeParts:[];
        if(form.dataset.schoolFilter==='direct'&&form.elements.q&&!form.elements.rq&&c.state.routeContext.recipient)context.recipient=c.state.routeContext.recipient;
        c.route(form.dataset.schoolFilter,{context,parts});
      }else if(form.dataset.schoolForm){
        event.preventDefault();submit(form);
      }
    });
    document.addEventListener('scroll',event=>{
      if(event.target.matches?.('[data-messenger-history]')&&atEnd(event.target))markThreadRead(c.state.data.direct);
    },true);
    document.addEventListener('input',event=>{
      const form=event.target.closest('form[data-school-form]');
      if(!form)return;
      if(form.dataset.schoolForm==='message')drafts.set(form.dataset.mode+':'+form.dataset.target,event.target.value);
      if(form.dataset.schoolForm==='material')form.dataset.dirty='true';
    });
    document.addEventListener('change',async event=>{
      const form=event.target.closest('form[data-school-form="material"]');
      if(form)form.dataset.dirty='true';
      if(!form||event.target.id!=='school-file'||!event.target.files[0])return;
      const file=event.target.files[0], epoch=c.state.sessionEpoch;
      const error=c.$('[data-school-error]',form);
      try{
        if(file.size>24000||!/\.(?:txt|md)$/i.test(file.name))throw new Error('Выберите файл TXT или MD до 24 КБ.');
        const body=new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer()).trim();
        if(body.length>6000||body.length<20)throw new Error('В файле должно быть от 20 до 6000 символов.');
        if(epoch===c.state.sessionEpoch&&form.isConnected){
          const field=c.$('#school-body',form);field.value=body;field.focus();error.hidden=true;
        }
      }catch(e){
        if(form.isConnected){error.hidden=false;error.textContent=e instanceof TypeError?'Сохраните файл в UTF-8.':e.message;}
      }
    });
  }

  function reset(){drafts.clear();receipts.clear();reading.clear();unread=0;poll=null;historyPoll=null;}
  window.ATLASUniversity={pages,has,validParts,cleanQuery,load,render:(page,data)=>renderers[page](data),
    init,reset,pollUnread,unreadBadge,afterRender};
})();
