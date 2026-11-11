/* Student union and VUC. Shared form and table controls live in operations.js. */
(() => {
  'use strict';
  const ui=window.ATLASOperations.ui;
  const names={union:'Студенческий профсоюз',vuc:'Военный учебный центр'};
  const statuses={submitted:'Подано',review:'Проверяется',needs_info:'Нужно уточнение',
    selection:'Рассмотрение решения',accepted:'Одобрено',rejected:'Отклонено',resolved:'Ответ готов'};
  const actions={review:'Взять на проверку',needs_info:'Запросить уточнение',selection:'Передать на решение',
    accepted:'Одобрить',rejected:'Отклонить',resolved:'Оформить ответ'};
  const applicationTitles={join:'Вступить в профсоюз',leave:'Выйти из профсоюза',aid:'Запросить материальную помощь',
    consult:'Запросить консультацию',appeal:'Написать обращение',event:'Записаться',apply:'Подать заявление'};
  const postKinds={structure:'Представители',news:'Объявления',benefit:'Социальные программы и льготы',
    event:'Мероприятия',document:'Документы',material:'Учебные материалы'};
  const unitsPosts={union:['structure','news','benefit','event','document'],vuc:['structure','news','document','material']};
  const outcomes={pending:'Ожидает результата',passed:'Зачтено',revision:'Нужна доработка'};
  const historyActions={publication:'Публикация',program:'Программа',group:'Группа',session:'Занятие'};
  const pages=[
    {id:'union',label:names.union,icon:'users',hint:'Членство, консультации, помощь и мероприятия',roles:['student']},
    {id:'vuc',label:names.vuc,icon:'graduation',hint:'Поступление, расписание и результаты',roles:['student']},
    {id:'union-office',label:'Кабинет профсоюза',icon:'users',hint:'Членство, обращения и публикации',roles:['union']},
    {id:'vuc-office',label:'Кабинет ВУЦ',icon:'graduation',hint:'Заявления, программы, расписание и результаты',roles:['vuc']},
  ];
  let c;
  const has=page=>pages.some(item=>item.id===page);
  const unitOf=page=>page.split('-')[0];
  const isOffice=page=>page.endsWith('-office');
  const int=value=>/^[1-9]\d{0,9}$/.test(value)&&Number(value)<=2147483647;
  const validParts=(_page,parts)=>parts.length===1&&int(parts[0]);
  const current=()=>c.state.data[c.state.page];
  const esc=value=>c.esc(value);
  const path=page=>'/app/'+page;
  const tabPath=(page,tab)=>ui.url(path(page),{tab});
  const casePath=(page,id)=>path(page)+'/'+Number(id);
  const time=value=>c.stamp(value)+' МСК';
  const choices=(items,label)=>items.map(item=>[item.id,label(item)]);
  const editorId=item=>item?{id:item.id,version:item.version}:{};
  const dateTime=value=>new Date(+new Date(value)+10800000).toISOString().slice(0,16);
  const button=(action,label,id='')=>`<button type="button" class="outline-button" data-unit-action="${esc(action)}" data-id="${esc(id)}">${esc(label)}</button>`;
  const paragraph=value=>value?`<p class="user-text">${esc(value)}</p>`:'';
  const checkbox=(key,label)=>`<label class="unit-check"><input type="checkbox" name="${esc(key)}" required> <span>${esc(label)}</span></label>`;

  function tabOptions(page){
    const office=isOffice(page);
    return {
      ...(office?{cases:'Очередь заявлений'}:{overview:'Обзор',cases:'Мои заявления'}),
      content:'Публикации',...(unitOf(page)==='vuc'?{learning:'Учебный процесс'}:{}),...(office?{report:'Отчёт и журнал'}:{}),
    };
  }

  function activeTab(page,query){
    return query.tab||(isOffice(page)?'cases':'overview');
  }

  function cleanQuery(page,query,parts){
    if(parts.length)return int(query.before)?{before:Number(query.before)}:{};
    const context=Object.hasOwn(tabOptions(page),query.tab)?{tab:query.tab}:{};
    if(activeTab(page,context)==='cases'){
      if(Object.hasOwn(statuses,query.status))context.status=query.status;
      if(int(query.offset))context.offset=Number(query.offset);
    }
    return context;
  }

  async function load(page,parts,query){
    const unit=unitOf(page), office=isOffice(page), base='units/'+unit;
    if(parts.length){
      const detail=await c.api(ui.url(base+'/cases/'+parts[0],{before:query.before}));
      return {title:detail.title+' №'+detail.id,unit,office,detail,parents:[
        {title:office?'Очередь заявлений':'Мои заявления',href:tabPath(page,'cases')},
      ]};
    }
    const tab=activeTab(page,query);
    const [overview,cases,learning,report,history]=await Promise.all([
      c.api(base),
      tab==='cases'?c.api(ui.url(base+'/cases',{status:query.status,offset:query.offset})):null,
      tab==='learning'||(tab==='content'&&unit==='vuc'&&office)?c.api('units/vuc/learning'):null,
      tab==='report'?c.api(base+'/report'):null,
      tab==='report'?c.api(base+'/history'):null,
    ]);
    return {...overview,cases,learning,report,history,tab};
  }

  function caseList(page,data){
    const {status}=c.state.routeContext;
    const filters=`<form class="op-inline-form" data-unit-filter>
      ${ui.select('status','Статус',[['','Все статусы'],...Object.entries(statuses)],status)}
      <button type="submit" class="outline-button">Показать</button></form>`;
    const items=ui.list(data.cases.items,item=>ui.row(
      ui.link(casePath(page,item.id),item.title+' №'+item.id),
      ui.p([item.student,item.subject,item.status_label].filter(Boolean).join(' · '))+
        `<small>Обновлено ${time(item.updated_at)}</small>`),
      'Заявлений нет','Здесь появятся заявления и их статусы.');
    return ui.section(data.office?'Очередь заявлений':'Мои заявления',filters+items+ui.pageLinks(path(page),data.cases,30));
  }

  function caseDetail(page,data){
    const item=data.detail;
    const buttons=data.office?item.allowed.map(status=>button('step-'+status,actions[status])).join(''):
      item.can_followup?button('followup','Добавить уточнение'):'';
    const header=ui.title(data.title,[item.student,item.subject,item.status_label].filter(Boolean).join(' · '),
      ui.link(tabPath(page,'cases'),data.office?'К очереди':'К моим заявлениям','outline-button'));
    const checklist=item.checklist.length?
      `<ul>${item.checklist.map(key=>`<li>${esc(key==='sample_application'?'Образец заявления':'Образец подтверждения статуса студента')}</li>`).join('')}</ul>`:'';
    const summary=ui.p('Подано '+time(item.created_at))+paragraph(item.message)+checklist+
      (item.response?`<h3 class="unit-subhead">Ответ сотрудника</h3>${paragraph(item.response)}`:'')+
      `<div class="op-actions unit-actions">${buttons}${item.file_url?ui.download(item.file_url,'Скачать решение'):''}</div>`;
    const timeline=`<ol class="op-log">${item.history.map(event=>`<li>
      <strong>${esc(event.action==='followup'?'Уточнение студента':event.status)}</strong>
      <small>${time(event.created_at)} · ${esc(event.author)}</small>${paragraph(event.message)}</li>`).join('')}</ol>`;
    const back=c.state.routeContext.before?ui.link(casePath(page,item.id),'К последним событиям','outline-button'):'';
    const older=item.older_before?ui.link(ui.url(casePath(page,item.id),{before:item.older_before}),'Более ранние события','outline-button'):'';
    return header+ui.section('Заявление',summary)+ui.section('История рассмотрения',timeline+`<div class="op-actions">${back}${older}</div>`);
  }

  function programRow(program,office){
    const state=program.accepting?'Идёт приём':program.published?'Приём закрыт':'Черновик';
    const range=c.dateFmt(program.opens)+' — '+c.dateFmt(program.closes);
    return ui.row(esc(program.title),paragraph(program.description)+ui.p('Условия подачи. '+program.requirements)+ui.p(range+' · '+state),
      office?button('edit-program','Изменить программу',program.id):
        program.accepting?button('apply','Подать заявление',program.id):'');
  }

  function overview(data){
    const contacts=ui.section('Связь с подразделением',
      `<div class="op-actions">${button('consult','Запросить консультацию')}${button('appeal','Написать обращение')}</div>`);
    if(data.unit==='vuc'){
      return ui.section('Программы и сроки приёма',ui.list(data.programs,item=>programRow(item,false),
        'Открытых программ пока нет','Опубликованные программы появятся здесь.'))+
        ui.section('Этапы рассмотрения',ui.p('Подайте заявление с двумя учебными образцами. Сотрудник проверит его, при необходимости запросит уточнение и оформит решение. При одобрении в кабинете появится ваша учебная группа.'))+contacts;
    }
    const {active,updated_at:updated}=data.member;
    const membership=ui.section('Моё членство',ui.p(active?'Членство действует':'Членство не оформлено')+
      (updated?`<small>Обновлено ${time(updated)}</small>`:'')+
      `<div class="op-actions unit-actions">${active?button('aid','Запросить материальную помощь')+button('leave','Выйти из профсоюза'):button('join','Вступить в профсоюз')}</div>`);
    return membership+contacts;
  }

  function publication(data,item){
    const group=data.learning?.groups.find(group=>group.id===item.group_id);
    const info=[item.event_day?c.dateFmt(item.event_day):'',item.capacity?`Мест: ${item.capacity}`:'',
      group?.code,data.office?(item.published?'Опубликовано':'Черновик'):''].filter(Boolean).join(' · ');
    const event=!data.office&&item.kind==='event'&&item.event_day>=c.today();
    return ui.row(esc(item.title),paragraph(item.body)+ui.p(info),
      (item.file_url?ui.download(item.file_url,'Скачать'):'')+
      (data.office?button('edit-publication','Изменить',item.id):event?button('event','Записаться',item.id):''));
  }

  function publications(data){
    const create=data.office?`<div class="op-actions unit-actions">${button('new-publication','Добавить публикацию')}</div>`:'';
    const sections=unitsPosts[data.unit].map(kind=>{
      const items=data.publications.filter(item=>item.kind===kind);
      return items.length?ui.section(postKinds[kind],ui.list(items,item=>publication(data,item))):'';
    }).join('');
    return create+(sections||ui.section('Публикации',ui.list([],null,'Публикаций пока нет','Здесь появятся объявления и документы.')));
  }

  function learning(page,data){
    const {groups,sessions,enrollments}=data.learning, office=data.office;
    const heading=(label,create,available)=>office&&available?`<div class="op-actions">${button(create,label)}</div>`:'';
    const roster=ui.section(office?'Учебные результаты':'Моя группа и результаты',ui.list(enrollments,item=>ui.row(
      esc([item.student,item.group,item.program].filter(Boolean).join(' · ')),ui.p(outcomes[item.outcome])+paragraph(item.comment),
      office?button('edit-result','Оформить результат',item.id):ui.link(casePath(page,item.case_id),'Решение о зачислении')),
    'Учебных записей пока нет','Учебная запись появится после одобрения заявления и назначения группы.'));
    const calendar=ui.section('Занятия по московскому времени',heading('Добавить занятие','new-session',groups.length)+
      ui.list(sessions,item=>ui.row(esc(item.title),ui.p(`${time(item.starts)} — ${time(item.ends)} · ${item.group} · ${item.room}`)+
        (item.cancelled?ui.p('Отменено'):''),office?button('edit-session','Изменить занятие',item.id):''),
      'Расписание пока пусто','Здесь появятся занятия учебной группы.'));
    if(!office)return roster+calendar;
    return ui.section('Программы',heading('Добавить программу','new-program',true)+ui.list(data.programs,item=>programRow(item,true)))+
      ui.section('Учебные группы',heading('Добавить группу','new-group',data.programs.length)+ui.list(groups,item=>
        ui.row(esc(item.code),ui.p(`${item.program} · Мест: ${item.capacity}`),button('edit-group','Изменить группу',item.id))))+
      calendar+roster;
  }

  function report(data){
    const base='/api/units/'+data.unit+'/report';
    const exports=`<div class="op-actions">${ui.download(base+'?format=csv','Выгрузить CSV')}${ui.download(base+'?format=xlsx','Выгрузить XLSX')}</div>`;
    const totals=`<dl class="op-summary">${data.report.items.map(item=>`<div><dt>${esc(item.section+' · '+item.status)}</dt><dd>${Number(item.count)}</dd></div>`).join('')}</dl>`;
    const activity=ui.list(data.history.items,item=>{
      const [kind,action]=item.action.split('_');
      const label=kind==='result'?'Результат':(historyActions[kind]||kind)+' · '+(action==='edit'?'изменение':'создание');
      return ui.row(esc(label+' №'+item.object_id),ui.p(item.author+' · '+time(item.created_at)));
    },'Записей пока нет','Действия по конкретному заявлению видны в его истории.');
    return ui.section('Сводка подразделения',exports+totals)+ui.section('Последние изменения',activity);
  }

  function render(page,data){
    if(data.detail)return caseDetail(page,data);
    const header=ui.title(data.office?(data.unit==='vuc'?'Кабинет ВУЦ':'Кабинет профсоюза'):names[data.unit],
      data.office?'Заявления и материалы подразделения':data.unit==='union'?
        'Членство, поддержка и студенческие инициативы':'Демонстрационный приём, учебный календарь и результаты');
    const navigation=ui.tabs('Разделы подразделения',tabOptions(page),data.tab,key=>tabPath(page,key));
    const renderers={overview,content:publications,cases:()=>caseList(page,data),learning:()=>learning(page,data),report};
    return header+navigation+renderers[data.tab](data);
  }

  function applicationForm(kind,id,data){
    const program=data.programs?.find(item=>item.id===id);
    const event=data.publications?.find(item=>item.id===id);
    const confirmation=['join','leave','apply','event'].includes(kind);
    const details=kind==='apply'?`<fieldset class="unit-checklist"><legend>Демонстрационные образцы</legend>
      ${Object.entries(data.checklist).map(([key,label])=>checkbox(key,label)).join('')}</fieldset>`:
      confirmation?'':ui.area('message','Опишите вымышленную ситуацию или вопрос','',1200);
    const instruction=kind==='apply'?'Отметьте учебные образцы. Для демонстрационной заявки достаточно флажков.':
      program?.title||event?.title||'Заявление относится к конкурсному концепту.';
    const fields=(program?`<p>${esc(program.title)}</p>`:'')+details+
      (confirmation?checkbox('confirmed','Подтверждаю демонстрационное действие'):'');
    const save=values=>{
      const payload={kind,...(confirmation?{confirmed:values.confirmed==='on'}:{message:values.message})};
      if(kind==='event')payload.publication_id=id;
      if(kind==='apply'){
        payload.program_id=id;
        payload.checklist=Object.keys(data.checklist).filter(key=>values[key]==='on');
      }
      return ui.request('units/'+data.unit+'/cases','POST',payload);
    };
    return ui.modal(applicationTitles[kind],instruction,fields,save,
      result=>c.route(data.unit,{parts:[String(result.id)]}),'Отправить');
  }

  function caseForm(action,data){
    const item=data.detail, base='units/'+data.unit+'/cases/'+item.id;
    if(action==='followup')return ui.modal('Добавить уточнение','Опишите вымышленную ситуацию.',
      ui.area('message','Уточнение','',1200),values=>ui.request(base+'/followup','POST',{...values,version:item.version}),
      undefined,'Отправить');
    const status=action.slice('step-'.length);
    const group=item.kind==='apply'&&status==='accepted';
    const required=['accepted','rejected','resolved','needs_info'].includes(status);
    const selector=group?ui.select('group_id','Учебная группа',
      [['','Выберите группу'],...choices(item.groups,row=>row.code)],'','required'):'';
    return ui.modal(actions[status],item.title+' №'+item.id,selector+
      ui.area('message',required?'Ответ студенту':'Комментарий к переходу (необязательно)','',1200),
      values=>ui.request(base+'/step','POST',{status,message:values.message,version:item.version,
        ...(group?{group_id:Number(values.group_id)}:{})}),undefined,actions[status]);
  }

  function syncPublicationForm(form){
    const kind=form.elements.kind.value;
    const eventFields=form.querySelector('[data-unit-post-event]');
    const groupField=form.querySelector('[data-unit-post-group]');
    if(eventFields){
      eventFields.hidden=kind!=='event';
      for(const field of eventFields.querySelectorAll('input'))field.required=kind==='event';
    }
    if(groupField)groupField.hidden=!['news','document','material'].includes(kind);
  }

  function publicationForm(data,item){
    const kinds=(item?[item.kind]:unitsPosts[data.unit]).map(kind=>[kind,postKinds[kind]]);
    const eventFields=data.unit==='union'?`<div data-unit-post-event><div class="op-form-grid">
      ${ui.input('event_day','Дата мероприятия',item?.event_day||c.addDays(c.today(),7),'date')}
      ${ui.input('capacity','Число мест',item?.capacity||20,'number','min="1" max="200" step="1"')}</div></div>`:'';
    const groupField=data.unit==='vuc'?`<div data-unit-post-group>${ui.select('group_id','Кому доступно',
      [['','Всем студентам'],...choices(data.learning.groups,row=>row.code)],item?.group_id??'')}</div>`:'';
    ui.modal(item?'Изменить публикацию':'Добавить публикацию',names[data.unit],
      ui.select('kind','Раздел публикации',kinds,item?.kind||kinds[0][0])+
      ui.input('title','Заголовок',item?.title,'text','required minlength="4" maxlength="180"')+
      ui.area('body','Текст',item?.body,5000)+eventFields+groupField+
      ui.yesNo('published','Опубликовать',item?.published??true),
      values=>ui.request('units/'+data.unit+'/publications','PUT',{
        ...editorId(item),kind:values.kind,title:values.title,body:values.body,published:values.published==='true',
        ...(values.kind==='event'?{event_day:values.event_day,capacity:Number(values.capacity)}:{}),
        ...(values.group_id&&['news','document','material'].includes(values.kind)?{group_id:Number(values.group_id)}:{}),
      }));
    const form=c.$('.modal [data-op-form]');
    form.dataset.unitPublication='';
    syncPublicationForm(form);
  }

  function programForm(item){
    const fields=ui.input('title','Название',item?.title,'text','required minlength="4" maxlength="180"')+
      ui.area('description','Описание',item?.description,1200)+ui.area('requirements','Условия подачи',item?.requirements,1200)+
      `<div class="op-form-grid">${ui.input('opens','Начало приёма',item?.opens||c.today(),'date','required')}
        ${ui.input('closes','Конец приёма',item?.closes||c.addDays(c.today(),30),'date','required')}</div>`+
      ui.yesNo('published','Показывать студентам',item?.published??true);
    return ui.modal(item?'Изменить программу':'Добавить программу',names.vuc,fields,values=>
      ui.request('units/vuc/learning/programs','PUT',{...values,...editorId(item),published:values.published==='true'}));
  }

  function groupForm(data,item){
    const programs=item?data.programs.filter(program=>program.id===item.program_id):data.programs;
    return ui.modal(item?'Изменить группу':'Добавить группу',names.vuc,
      ui.select('program_id','Программа',choices(programs,row=>row.title),item?.program_id,'required')+
      ui.input('code','Код группы',item?.code,'text','required minlength="2" maxlength="60"')+
      ui.input('capacity','Число мест',item?.capacity||20,'number','required min="1" max="100" step="1"'),
      values=>ui.request('units/vuc/learning/groups','PUT',ui.numbers({...values,...editorId(item)},'capacity','program_id')));
  }

  function sessionForm(data,item){
    const date=c.addDays(c.today(),3);
    const fields=ui.select('group_id','Учебная группа',choices(data.learning.groups,row=>row.code),item?.group_id,'required')+
      ui.input('title','Тема',item?.title,'text','required minlength="4" maxlength="180"')+
      ui.input('room','Помещение',item?.room,'text','required minlength="2" maxlength="100"')+
      `<div class="op-form-grid">${ui.input('starts','Начало (МСК)',item?dateTime(item.starts):date+'T15:00','datetime-local','required')}
        ${ui.input('ends','Окончание (МСК)',item?dateTime(item.ends):date+'T16:00','datetime-local','required')}</div>`+
      (item?ui.yesNo('cancelled','Отменено',item.cancelled):'');
    return ui.modal(item?'Изменить занятие':'Добавить занятие','Укажите время в часовом поясе кампуса.',fields,values=>
      ui.request('units/vuc/learning/sessions','PUT',{...values,...editorId(item),
        group_id:Number(values.group_id),starts:ui.msk(values.starts),ends:ui.msk(values.ends),cancelled:values.cancelled==='true'}));
  }

  function resultForm(item){
    return ui.modal('Оформить результат',item.student+' · '+item.group,
      ui.select('outcome','Результат',Object.entries(outcomes),item.outcome)+
      ui.area('comment','Комментарий студенту',item.comment,1200),values=>
      ui.request('units/vuc/learning/results/'+item.id,'PUT',{...values,version:item.version}));
  }

  function handle(action,id,data){
    if(Object.hasOwn(applicationTitles,action))return applicationForm(action,id,data);
    if(data.detail)return caseForm(action,data);
    if(action.endsWith('-publication'))return publicationForm(data,data.publications.find(item=>item.id===id));
    if(action.endsWith('-program'))return programForm(data.programs.find(item=>item.id===id));
    if(action.endsWith('-group'))return groupForm(data,data.learning.groups.find(item=>item.id===id));
    if(action.endsWith('-session'))return sessionForm(data,data.learning.sessions.find(item=>item.id===id));
    if(action==='edit-result')return resultForm(data.learning.enrollments.find(item=>item.id===id));
  }

  function init(context){
    c=context;
    document.addEventListener('click',event=>{
      const element=event.target.closest('[data-unit-action]');
      if(element&&has(c.state.page)&&!c.state.pending&&current())handle(element.dataset.unitAction,Number(element.dataset.id),current());
    });
    document.addEventListener('submit',event=>{
      const form=event.target;
      if(!form.hasAttribute('data-unit-filter'))return;
      event.preventDefault();
      const status=new FormData(form).get('status');
      c.route(c.state.page,{context:{tab:'cases',status}});
    });
    document.addEventListener('change',event=>{
      const form=event.target.closest('[data-unit-publication]');
      if(form&&event.target.name==='kind')syncPublicationForm(form);
    });
  }

  window.ATLASUnits={pages,has,validParts,cleanQuery,load,render,init};
})();
