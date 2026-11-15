/* The university directory, teaching library and private messages use authenticated APIs. */
(() => {
  'use strict';
  const everyone=['student','staff','teacher'];
  const disciplines=window.ATLASDisciplines;
  const pages=[
    {id:'university',label:'Университет',icon:'pin',hint:'Институты, кафедры и преподаватели',
      roles:[...everyone,'coordinator','department','admin','scheduler']},
    {id:'direct',label:'Личные сообщения',icon:'send',hint:'Переписка с преподавателями и учебным офисом',roles:everyone},
    {id:'teacher',label:'Кабинет преподавателя',icon:'home',hint:'Занятия, консультации, публикации и диалоги',roles:['teacher']},
  ];
  const directoryKinds=[['faculty','Институты и факультеты'],['department','Кафедры'],['teacher','Преподаватели']];
  const weekdays=['Понедельник','Вторник','Среда','Четверг','Пятница','Суббота','Воскресенье'];
  const roleLabels={student:'Студент',teacher:'Преподаватель',staff:'Учебный офис'};
  const drafts=new Map(), receipts=new Map(), reading=new Set();
  const messengerSearches=new WeakMap();
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
  const appLink=(href,label,cls='mini-link',attributes='')=>`<a class="${cls}" href="${esc(href)}" data-app-link ${attributes}>${esc(label)}</a>`;
  const title=(name,description='',actions='',meta='')=>c.head('',esc(name),esc(description),actions,meta);
  const section=(name,content)=>`<section class="card card-pad school-section"><h2>${esc(name)}</h2>${content}</section>`;
  const empty=(name,description)=>c.empty('book',name,description);
  const safeSearch=value=>String(value??'').replace(/[\x00-\x1f]/g,'').trim().slice(0,100);

  function validParts(page,parts){
    if(!parts.length)return false;
    if(page==='university')return parts.length<=3&&parts.every(part=>/^[a-z0-9-]{1,60}$/.test(part));
    return (page==='direct')&&parts.length===1&&id(parts[0]);
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
    if(page==='direct'){
      return {
        ...(parts.length&&id(query.before)?{before:Number(query.before)}:{}),
        ...(!parts.length&&isStudent()&&id(query.recipient)?{recipient:Number(query.recipient)}:{}),
        ...(q?{q}:{}),
        ...(isStudent()&&rq?{rq}:{}),
        ...(id(query.offset)?{offset:Number(query.offset)}:{}),
      };
    }
    return {};
  }

  async function load(page,parts,query){
    if(page==='university')return c.api(path(['university',...parts].join('/'),query));
    if(page==='teacher'){
      const [profile,work,calendar,consultations,direct]=await Promise.all([c.api('university/me'),c.api('teaching/workbench'),
        c.api('teaching/schedule'),c.api('teaching/consultations'),c.api('direct/unread')]);
      return {...profile,...work,calendar:calendar.items,consultations:consultations.items,direct};
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

  /** @param {{type?: string, query?: boolean, max?: number, required?: boolean}} options */
  function input(name,label,value='',options={}){
    return `<div class="field ${options.query?'filter-query':''}"><label for="school-${name}">${esc(label)}</label><input id="school-${name}" type="${options.type||'text'}" name="${name}" value="${esc(value)}" maxlength="${options.max||100}" ${options.required?'required':''}></div>`;
  }

  function select(name,label,choices,value,required=false){
    return `<div class="field"><label for="school-${name}">${esc(label)}</label><select id="school-${name}" name="${name}" ${required?'required':''}>${choices.map(([key,text])=>`<option value="${esc(key)}" ${String(key)===String(value??'')?'selected':''}>${esc(text)}</option>`).join('')}</select></div>`;
  }

  function searchForm(page,fields,reset=false){
    return `<form class="filter-bar school-filter" role="search" aria-label="Поиск и фильтры" data-school-filter="${page}">${fields}<div class="filter-actions"><button class="outline-button" type="submit">${icon('search')} Найти</button>${reset?appLink('/app/'+page,'Сбросить'):''}</div></form>`;
  }

  function pager(page,data,query=c.state.routeContext){
    const hasNext=data.offset+data.limit<data.total;
    if(!data.offset&&!hasNext)return '';
    const url=offset=>path('/app/'+page,{...query,offset:offset||undefined});
    const attributes=page==='direct'?'data-messenger-link="page"':'';
    return `<nav class="campus-pagination" aria-label="Страницы результатов"><span>${data.total?`${data.offset+1}–${Math.min(data.offset+data.limit,data.total)} из ${data.total}`:'Нет результатов'}</span><div>${data.offset?appLink(url(Math.max(0,data.offset-data.limit)),'Предыдущая','outline-button',attributes):''}${hasNext?appLink(url(data.offset+data.limit),'Следующая','outline-button',attributes):''}</div></nav>`;
  }

  function directoryCards(items){
    if(!items.length)return empty('Ничего не найдено','Попробуйте изменить запрос или фильтры.');
    return `<div class="campus-grid">${items.map(row=>`<article class="card campus-tile school-tile"><h2>${appLink(row.href,row.title,'school-card-link')}</h2>${row.position?`<p class="school-meta">${esc(row.position)} · ${esc(row.department)}</p>`:''}<p>${esc(row.description)}</p>${row.subjects?.length?`<p>${esc(row.subjects.join(', '))}</p>`:''}</article>`).join('')}</div>`;
  }

  function disciplineList(rows){
    if(!rows.length)return '<p class="compact-empty">Дисциплины пока не добавлены.</p>';
    return `<ul class="school-list">${rows.map(row=>`<li><strong>${esc(row.title)}</strong><p>${esc(row.description)}</p>${appLink(disciplines.coursePath(row.id),'Материалы дисциплины')}</li>`).join('')}</ul>`;
  }

  function teachingSchedule(rows,kind){
    const matching=rows.filter(row=>row.kind===kind);
    if(!matching.length)return '<p class="compact-empty">В расписании пока нет записей.</p>';
    return `<ul class="school-list school-schedule">${matching.map(row=>`<li><strong>${weekdays[row.weekday]} · ${esc(row.starts)}–${esc(row.ends)}</strong><p>${esc(row.discipline)} · ${esc(row.room)}</p></li>`).join('')}</ul>`;
  }

  function recentMaterials(data){
    if(!data.materials.length)return '<p class="compact-empty">У преподавателя пока нет публикаций.</p>';
    return `<ul class="school-list school-material-preview">${data.materials.map(row=>`<li><h3>${appLink(disciplines.materialPath(row.id),row.title,'school-card-link')}</h3>
      <p class="school-meta">${esc(row.kind_label)} · ${esc(row.discipline.title)} · ${c.dateFmt(row.updated_at,{day:'numeric',month:'short',year:'numeric'})}</p><p>${esc(row.description)}</p></li>`).join('')}</ul>
      <div class="school-section-footer">${appLink(path('/app/courses',{teacher:data.id}),'Все материалы преподавателя')}</div>`;
  }

  function profile(data){
    const actions=data.can_message?appLink(path('/app/direct',{recipient:data.recipient_id}),'Написать преподавателю','primary-button')+
        appLink(path('/app/consultations',{subject:data.disciplines[0]?.title}),'Запись на консультацию','outline-button'):'';
    return title(data.title,[data.position,data.department].filter(Boolean).join(' · '),actions)+
      `<div class="school-detail-grid">
        ${section('Академическая информация',`<p>${esc(data.description)}</p>`)}${section('Дисциплины',disciplineList(data.disciplines))}
        ${section('Учебные материалы',recentMaterials(data))}
        <div class="school-stack">${section('Занятия · МСК',teachingSchedule(data.schedule,'lesson'))}${section('Консультации · МСК',teachingSchedule(data.schedule,'consultation'))}</div>
      </div>`;
  }

  function teacherWorkbench(data){
    const groups=data.groups.map(row=>{
      const base='/app/teaching/'+Number(row.id);
      return `<li><strong>${appLink(base,row.discipline+' · '+row.group,'school-card-link')}</strong>
        <div class="school-actions">${appLink(base,'Студенты')}${appLink(base+'?tab=works','Задания')}
          ${appLink(base+'?tab=grades','Ведомость')}${appLink(base+'?tab=attendance','Посещаемость')}
          ${appLink(disciplines.coursePath(row.discipline_id),'Материалы дисциплины')}</div></li>`;
    });
    const pending=data.pending.map(row=>`<li><strong>${appLink('/app/teaching/'+row.load_id+'/works/'+row.work_id,row.title,'school-card-link')}</strong>
      <p>${esc(row.discipline)} · ${esc(row.group)} · ${Number(row.count)} на проверке</p></li>`);
    const lessons=data.calendar.filter(row=>row.day>=c.today()).slice(0,5).map(row=>`<li><strong>${esc(row.title||row.discipline)}</strong>
      <p>${esc(c.dateFmt(row.day)+' · '+row.start+'–'+row.end+' МСК · '+row.room+' · '+row.group)}</p></li>`);
    const consultations=data.consultations.filter(row=>!row.completed&&Date.parse(row.starts)>Date.now())
      .sort((a,b)=>Date.parse(a.starts)-Date.parse(b.starts)).slice(0,5)
      .map(row=>`<li><strong>${esc(row.subject)}</strong><p>${esc(c.stamp(row.starts)+' МСК · '+row.room)}</p></li>`);
    const rows=(items,message)=>items.length?`<ul class="school-list">${items.join('')}</ul>`:`<p class="compact-empty">${message}</p>`;
    const actions=appLink('/app/materials-admin','Публикации','primary-button')+
      appLink('/app/teaching','Группы и дисциплины','outline-button')+appLink(data.href,'Профиль преподавателя','outline-button');
    return title('Кабинет преподавателя',[data.title,data.position,data.department].filter(Boolean).join(' · '),actions)+
      `<div class="school-detail-grid teacher-workbench">
        <div class="school-stack">
          ${section('Работы на проверке',rows(pending,'Ожидающих проверки работ нет.'))}
          ${section('Учебные группы',rows(groups,'Учебные группы пока не назначены.'))}
          ${section('Последние публикации',recentMaterials(data))}
        </div>
        <div class="school-stack">
          ${section('Обращения и документы',`<p>Непрочитанных сообщений: ${Number(data.direct.unread_count)}.</p>
            ${appLink('/app/direct','Открыть личные сообщения')}`)}
          ${section('Занятия на этой неделе',rows(lessons,'На этой неделе занятий больше нет.')+
            appLink('/app/teach-schedule','Расписание преподавателя'))}
          ${section('Предстоящие консультации',rows(consultations,'Предстоящих консультаций пока нет.')+
            appLink('/app/teach-consultations','Управлять консультациями'))}
          ${section('Дисциплины',disciplineList(data.disciplines))}
        </div>
      </div>`;
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
      searchForm('university',input('q','Поиск по каталогу',q.q,{type:'search',query:true})+select('faculty','Подразделение',[['','Все подразделения'],...data.faculties.map(row=>[row.slug,row.title])],q.faculty)+
        select('kind','Показывать',[['','Всё'],...directoryKinds],q.kind),Object.keys(q).length>0)+directoryCards(data.items);
  }

  function compose(target,type,canAttach){
    const key=type+':'+target;
    return `<form class="school-compose" data-school-form="message" data-target="${target}" data-mode="${type}">
      <div class="field"><label class="sr-only" for="direct-message">Сообщение</label><textarea id="direct-message" name="message" placeholder="Напишите сообщение" maxlength="3000" rows="2" ${canAttach?'':'required'}>${esc(drafts.get(key)||'')}</textarea></div>
      <div class="inline-error" role="alert" data-school-error hidden></div>
      <button type="submit" class="primary-button">${icon('send')} Отправить</button>
      ${canAttach?`<details class="direct-attachment"><summary>Приложить документ</summary>${disciplines.fileInput('file','Файл сообщения')}</details>`:''}</form>`;
  }

  const inboxQuery=()=>{
    const {q,rq,offset}=c.state.routeContext;
    return {q,rq,offset};
  };

  function dialogRows(data){
    const query=inboxQuery();
    return data.inbox.items.length?data.inbox.items.map(row=>{
      const current=row.id===data.id;
      return `<a class="messenger-item" href="${esc(path('/app/direct/'+row.id,query))}" data-app-link data-messenger-link ${current?'aria-current="page"':''}>
        <span class="messenger-avatar" aria-hidden="true">${esc(row.person.initials)}</span><span class="messenger-person"><b>${esc(row.person.name)}</b><small>${esc(row.preview)}</small></span>
        <span class="messenger-meta"><time datetime="${esc(row.updated_at)}">${c.stamp(row.updated_at)}</time>
        ${row.unread_count?`<span class="campus-pill" aria-label="Непрочитанных: ${Number(row.unread_count)}">${Number(row.unread_count)}</span>`:''}</span></a>`;
    }).join(''):`<p class="compact-empty">${query.q?'Собеседники по запросу не найдены.':'Диалогов пока нет.'}</p>`;
  }

  function inboxResults(data){
    return `<div class="messenger-items" data-messenger-items>${dialogRows(data)}</div>${pager('direct',data.inbox,inboxQuery())}`;
  }

  function recipientResults(items){
    return items.length?`<ul class="school-list school-contacts">${items.map(row=>`<li>${appLink(path('/app/direct',{...inboxQuery(),recipient:row.id}),row.name,'school-card-link','data-messenger-link')}<p>${esc(row.label)}</p></li>`).join('')}</ul>`
      :`<p class="compact-empty">${c.state.routeContext.rq?'Адресаты по запросу не найдены.':'Нет доступных адресатов.'}</p>`;
  }

  function messengerSearch(key,label,content){
    return `<form class="messenger-search" data-messenger-search="${key}" role="search" aria-label="${label}">
      ${input(key,label,c.state.routeContext[key],{type:'search'})}
      <p class="messenger-search-status" data-messenger-status role="status"></p>
      <button type="submit" class="outline-button" hidden>Повторить</button>
    </form><div data-messenger-results="${key}">${content}</div>`;
  }

  function syncMessengerLinks(query){
    for(const link of c.$$('[data-messenger-link]')){
      const url=new URL(link.href);
      for(const key of ['q','rq','offset']){
        if(key==='offset'&&link.dataset.messengerLink==='page')continue;
        if(query[key])url.searchParams.set(key,query[key]);
        else url.searchParams.delete(key);
      }
      link.setAttribute('href',url.pathname+url.search);
    }
  }

  function searchMessenger(form,{immediate=false}={}){
    const key=form.dataset.messengerSearch, input=form.elements[key];
    const query=safeSearch(input.value), inbox=key==='q';
    const {sessionEpoch,loadingId}=c.state, data=c.state.data.direct;
    const results=c.$(`[data-messenger-results="${key}"]`);
    const status=c.$('[data-messenger-status]',form), retry=c.$('button',form);
    clearTimeout(messengerSearches.get(form)?.timer);
    const search={timer:0,pending:true,failed:false};
    messengerSearches.set(form,search);
    const current=()=>form.isConnected&&c.state.page==='direct'&&sessionEpoch===c.state.sessionEpoch&&
      loadingId===c.state.loadingId&&messengerSearches.get(form)===search;
    status.classList.remove('sr-only','messenger-search-error');
    status.textContent=inbox?'Ищем диалоги…':'Ищем адресатов…';
    retry.hidden=true;
    results.hidden=true;
    results.setAttribute('aria-busy','true');
    search.timer=setTimeout(async()=>{
      if(!current())return;
      try{
        const response=await c.api(path(inbox?'direct/dialogs':'direct/recipients',{q:query}));
        if(!current())return;
        const context={...c.state.routeContext};
        if(query)context[key]=query;
        else delete context[key];
        if(inbox)delete context.offset;
        c.replaceRouteContext(context);
        if(inbox)data.inbox=response;
        else data.contacts=response.items;
        results.innerHTML=inbox?inboxResults(data):recipientResults(data.contacts);
        syncMessengerLinks(context);
        status.classList.add('sr-only');
        status.textContent=inbox?`Найдено диалогов: ${response.total}.`:`Найдено адресатов: ${response.items.length}.`;
        results.hidden=false;
      }catch(error){
        if(!current()||error.stale)return;
        search.failed=true;
        status.classList.add('messenger-search-error');
        status.textContent=(inbox?'Не удалось найти диалоги. ':'Не удалось найти адресатов. ')+error.message;
        retry.hidden=false;
      }finally{
        if(current()){
          search.pending=false;
          results.removeAttribute('aria-busy');
        }
      }
    },immediate||!query?0:c.searchDelay);
  }

  function messages(data){
    if(!data.messages.length)return '<p class="compact-empty">В переписке пока нет сообщений.</p>';
    let previous;
    const rows=data.messages.map(row=>{
      const when=new Date(row.created_at), day=dayFormat.format(when);
      const heading=day!==previous?`<li class="messenger-day"><time datetime="${esc(row.created_at)}">${day}</time></li>`:'';
      previous=day;
      return `${heading}<li class="messenger-bubble ${row.mine?'mine':'received'}" data-message-id="${Number(row.id)}"><span class="sr-only">${esc(row.mine?'Вы':data.person.name)}</span>
        ${row.body?`<p>${esc(row.body)}</p>`:''}
        ${row.file?`<a download class="school-card-link" href="${esc(row.file.url)}">${esc(row.file.name)}</a>`:''}
        <footer><time datetime="${esc(row.created_at)}">${timeFormat.format(when)} МСК</time>${row.mine?`<span>${row.is_read?'Прочитано':'Отправлено'}</span>`:''}</footer></li>`;
    });
    return `<ol class="messenger-messages school-conversation" aria-label="Сообщения">${rows.join('')}</ol>`;
  }

  function direct(data){
    const query=inboxQuery();
    const contacts=data.contacts?`<details class="messenger-contacts" ${query.rq||!data.inbox.total?'open':''}><summary>Новый диалог</summary>
      ${messengerSearch('rq','Поиск адресата',recipientResults(data.contacts))}</details>`:'';
    const sidebar=`<nav class="messenger-inbox" aria-label="Диалоги">${messengerSearch('q','Поиск диалога',inboxResults(data))}${contacts}</nav>`;
    const back=appLink(path('/app/direct',query),'К списку диалогов','mini-link messenger-back','data-messenger-link');
    let panel='<div class="messenger-placeholder compact-empty">Выберите диалог, чтобы открыть переписку.</div>';
    if(data.mode!=='list'){
      const other=data.person;
      const history=data.mode==='dialog'?`<div class="messenger-history" tabindex="0" aria-label="История переписки" data-messenger-history>
        ${data.older_before?'<button type="button" class="mini-link messenger-older" data-messenger-older>Более ранние сообщения</button>':''}
        <div data-messenger-messages>${messages(data)}</div></div>`:'<div class="messenger-placeholder compact-empty">Здесь начнётся переписка.</div>';
      const canAttach=other.role==='teacher'||c.state.user.role==='teacher';
      const footer=data.mode==='compose'?compose(other.id,'recipient',canAttach):c.state.routeContext.before?
        appLink(path('/app/direct/'+data.id,query),'К последним сообщениям','outline-button','data-messenger-link')+compose(data.id,'dialog',canAttach):
        compose(data.id,'dialog',canAttach);
      panel=`<section class="messenger-thread" aria-labelledby="messenger-name"><header class="messenger-header">${back}<span class="messenger-avatar" aria-hidden="true">${esc(other.initials)}</span>
        <div><h2 id="messenger-name">${esc(other.name)}</h2><p>${esc(other.label||roleLabels[other.role]||'')}</p></div></header>${history}${footer}</section>`;
    }
    return title('Личные сообщения')+`<div class="card messenger ${data.mode==='list'?'messenger-list-view':'messenger-thread-view'}">${sidebar}${panel}</div><p class="sr-only" role="status" data-messenger-update></p>`;
  }

  const renderers={university:directory,teacher:teacherWorkbench,direct};

  async function submit(form){
    if(c.state.pending)return;
    const epoch=c.state.sessionEpoch, errorBox=c.$('[data-school-error]',form);
    const target=Number(form.dataset.target), starting=form.dataset.mode==='recipient';
    const endpoint=starting?'direct/dialogs':`direct/dialogs/${target}/messages`;
    const messageInput=form.elements.message, fileInput=form.elements.file;
    const submittedText=messageInput.value, file=fileInput?.files[0];
    const inCurrentThread=!starting&&c.state.routeParts[0]===form.dataset.target&&!c.state.routeContext.before;
    const controls=[c.$('button[type=submit]',form),fileInput].filter(Boolean);
    c.state.pending++;
    errorBox.hidden=true;
    if(inCurrentThread)messageInput.focus({preventScroll:true});
    else messageInput.readOnly=true;
    controls.forEach(control=>{control.disabled=true;});
    let result;
    try{
      const attachment=await disciplines.readUpload(file);
      const message=submittedText.trim();
      if(!message&&!attachment)throw new Error('Напишите сообщение или приложите документ.');
      if(epoch!==c.state.sessionEpoch||!form.isConnected)return;
      const body=JSON.stringify({message,file:attachment,...(starting?{recipient_id:target}:{})});
      const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(body));
      const hash=Array.from(new Uint8Array(digest),byte=>byte.toString(16).padStart(2,'0')).join('');
      if(epoch!==c.state.sessionEpoch||!form.isConnected)return;
      const saved=receipts.get(endpoint), key=saved?.hash===hash?saved.key:crypto.randomUUID();
      receipts.set(endpoint,{hash,key});
      result=await c.api(endpoint,{method:'POST',body,headers:{'Idempotency-Key':key}});
    }catch(error){
      if(!error.stale&&form.isConnected){errorBox.hidden=false;errorBox.textContent=error.message;}
    }finally{
      if(epoch===c.state.sessionEpoch){
        c.state.pending=Math.max(0,c.state.pending-1);
        controls.forEach(control=>{control.disabled=false;});
        if(!inCurrentThread)messageInput.readOnly=false;
      }
    }
    if(!result||epoch!==c.state.sessionEpoch)return;
    receipts.delete(endpoint);
    const draftKey=form.dataset.mode+':'+form.dataset.target;
    if(!inCurrentThread||drafts.get(draftKey)===submittedText)drafts.delete(draftKey);
    c.toast('Сообщение отправлено.');
    if(!form.isConnected||c.state.page!=='direct')return;
    if(inCurrentThread){
      if(messageInput.value===submittedText)messageInput.value='';
      if(fileInput){fileInput.value='';fileInput.closest('details').open=false;}
      await pollConversation({afterSend:true});
      return;
    }
    const dialogId=String(result.dialog_id), before=c.state.routeContext.before;
    await c.route('direct',{parts:[dialogId],context:inboxQuery(),replace:starting||Boolean(before)});
    if(epoch===c.state.sessionEpoch&&c.state.page==='direct'&&c.state.routeParts[0]===dialogId)c.$('#direct-message')?.focus({preventScroll:true});
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

  function pollConversation({afterSend=false}={}){
    const data=c.state.data.direct;
    if(c.state.page!=='direct'||!data||(historyPoll&&!afterSend)||c.state.pending||c.state.routeContext.before)return;
    const epoch=c.state.sessionEpoch, loadingId=c.state.loadingId;
    const {q,offset}=c.state.routeContext;
    const form=c.$('[data-messenger-search="q"]'), search=messengerSearches.get(form);
    const refreshInbox=!search?.pending&&!search?.failed;
    const request=Promise.all([
      refreshInbox?c.api(path('direct/dialogs',{q,offset}),{quietAuth:true}):null,
      data.mode==='dialog'?c.api('direct/dialogs/'+data.id,{quietAuth:true}):null,
    ]).then(([inbox,latest])=>{
      if(historyPoll!==request||epoch!==c.state.sessionEpoch||c.state.page!=='direct'||
        loadingId!==c.state.loadingId||c.state.data.direct!==data||c.state.pending)return;
      const list=c.$('[data-messenger-results="q"]');
      if(inbox&&list&&messengerSearches.get(form)===search&&!list.contains(document.activeElement)&&JSON.stringify(data.inbox)!==JSON.stringify(inbox)){
        data.inbox=inbox;list.innerHTML=inboxResults(data);
      }
      const history=c.$('[data-messenger-history]');
      if(!history||!latest)return;
      const bottom=afterSend||atEnd(history), through=data.read_through;
      const previousFirst=data.messages[0]?.id, latestFirst=latest.messages[0]?.id;
      const older=data.messages.filter(row=>row.id<latestFirst);
      const next=[...older,...latest.messages];
      const changed=next.length!==data.messages.length||next.some((row,index)=>row.id!==data.messages[index]?.id||row.is_read!==data.messages[index]?.is_read);
      data.read_through=latest.read_through;data.unread_count=latest.unread_count;
      if(changed){
        data.messages=next;
        if(previousFirst===undefined||!older.length)data.older_before=latest.older_before;
        c.$('[data-messenger-messages]',history).innerHTML=messages(data);
        if(!afterSend&&through!==latest.read_through)c.$('[data-messenger-update]').textContent='В переписке появились новые сообщения.';
      }
      if(bottom){
        if(changed||afterSend)history.scrollTop=history.scrollHeight;
        markThreadRead(data);
      }
    }).catch(()=>{}).finally(()=>{if(historyPoll===request)historyPoll=null;});
    historyPoll=request;
    return request;
  }

  function init(context){
    c=context;
    document.addEventListener('click',event=>{
      const older=event.target.closest('[data-messenger-older]');
      if(older){olderMessages(older);return;}
    });
    document.addEventListener('submit',event=>{
      const form=event.target;
      if(form.dataset.messengerSearch){
        event.preventDefault();
        form.elements[form.dataset.messengerSearch].focus({preventScroll:true});
        searchMessenger(form,{immediate:true});
      }else if(form.dataset.schoolFilter){
        event.preventDefault();
        const context=Object.fromEntries(new FormData(form));
        c.route(form.dataset.schoolFilter,{context});
      }else if(form.dataset.schoolForm){
        event.preventDefault();submit(form);
      }
    });
    document.addEventListener('scroll',event=>{
      if(event.target.matches?.('[data-messenger-history]')&&atEnd(event.target))markThreadRead(c.state.data.direct);
    },true);
    document.addEventListener('input',event=>{
      const input=event.target;
      if(!(input instanceof HTMLInputElement||input instanceof HTMLTextAreaElement||input instanceof HTMLSelectElement))return;
      const form=input.form;
      if(form?.dataset.messengerSearch){
        if(!(event instanceof InputEvent&&event.isComposing))searchMessenger(form);
        return;
      }
      if(!form?.dataset.schoolForm)return;
      if(form.dataset.schoolForm==='message'&&input.name==='message')drafts.set(form.dataset.mode+':'+form.dataset.target,input.value);
    });
  }

  function reset(){drafts.clear();receipts.clear();reading.clear();unread=0;poll=null;historyPoll=null;}
  window.ATLASUniversity={pages,has,validParts,cleanQuery,load,render:(page,data)=>renderers[page](data),
    init,reset,pollUnread,unreadBadge,afterRender};
})();
