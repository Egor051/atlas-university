/* Discipline workspaces and material management share the publication API. */
(() => {
  'use strict';
  const managers=['teacher','staff','coordinator','department'];
  const pages=[
    {id:'courses',label:'Мои дисциплины',icon:'book',hint:'Предметы, учебные материалы и прогресс по модулям',roles:['student','teacher']},
    {id:'courses',label:'Дисциплины',icon:'book',hint:'Предметы и публикации преподавателей',roles:['staff','coordinator','department','admin','scheduler']},
    {id:'materials-admin',label:'Публикации',icon:'file',hint:'Загрузка, редактирование и архив материалов',roles:managers},
    {id:'material-delegations',label:'Полномочия по материалам',icon:'shield',hint:'Права на дисциплину или кафедру',roles:['admin']},
  ];
  const materialKinds=['lecture','guide','slides','practice','lab','extra'];
  const sorts={newest:'Сначала новые',updated:'По обновлению',oldest:'Сначала ранние',title:'По названию'};
  const accessLabels={campus:'Весь кампус',group:'Назначенные группы',hidden:'Скрыт',archived:'В архиве'};
  const sources={text:'Текст',file:'Файл',link:'Ссылка'};
  const tabs={materials:'Материалы',overview:'О дисциплине',schedule:'Расписание',works:'Задания и работы',
    consultations:'Консультации',announcements:'Объявления'};
  const employeeTabs=['materials','overview','announcements'];
  const formats=['pdf','png','jpg','jpeg','docx','pptx','xlsx','txt','md'];
  const maxFileSize=5*1024*1024;
  const receipts=new Map();
  let c;
  const esc=value=>c.esc(value);
  const icon=name=>c.icon(name);
  const has=page=>pages.some(item=>item.id===page);
  const student=()=>c.state.user.role==='student';
  const id=value=>/^[1-9]\d{0,9}$/.test(value)&&Number(value)<=2147483647;
  const expectId=value=>id(value)?Number(value):undefined;
  const searchText=value=>String(value??'').replace(/[\x00-\x1f]/g,'').trim().slice(0,100);
  const date=value=>c.dateFmt(value,{day:'numeric',month:'short',year:'numeric'});
  const title=(name,description='',actions='',meta='')=>c.head('',esc(name),esc(description),actions,meta);
  const section=(name,content)=>`<section class="card card-pad school-section"><h2>${esc(name)}</h2>${content}</section>`;
  const empty=(name,description)=>c.empty('book',name,description);
  const path=(base,query={})=>{
    const search=new URLSearchParams(Object.entries(query).filter(([,value])=>value!==undefined&&value!==null&&value!=='')).toString();
    return base+(search?'?'+search:'');
  };
  const link=(href,text,cls='mini-link')=>`<a class="${cls}" href="${esc(href)}" data-app-link>${esc(text)}</a>`;
  const coursePath=(id,tab='materials')=>path('/app/courses/'+Number(id),tab==='materials'?{}:{tab});
  const personalPath=(id,tab='overview')=>path('/app/courses/personal/'+Number(id),tab==='overview'?{}:{tab});
  const materialPath=id=>'/app/courses/materials/'+Number(id);

  function legacyRoute(parts,query){
    if(parts.length===1&&id(parts[0]))return {page:'courses',parts:['materials',parts[0]],context:{}};
    const discipline=expectId(query.discipline);
    return {page:'courses',parts:discipline?[String(discipline)]:[],context:query};
  }

  function validParts(page,parts){
    if(page!=='courses')return false;
    if(parts.length===1)return id(parts[0]);
    return parts.length===2&&id(parts[1])&&(parts[0]==='materials'||(student()&&parts[0]==='personal'));
  }

  function materialQuery(query){
    return {
      q:searchText(query.q)||undefined,
      kind:materialKinds.includes(query.kind)?query.kind:undefined,
      sort:Object.hasOwn(sorts,query.sort)&&query.sort!=='newest'?query.sort:undefined,
      teacher:expectId(query.teacher),
      offset:expectId(query.offset),
    };
  }

  function cleanQuery(page,query,parts){
    if(page==='material-delegations')return {};
    if(page==='materials-admin')return {...materialQuery(query),discipline:expectId(query.discipline),
      access:Object.hasOwn(accessLabels,query.access)?query.access:undefined};
    if(parts[0]==='materials')return query.history==='1' ? {history:'1',offset:expectId(query.offset)} : {};
    if(!parts.length)return {...materialQuery(query),id:expectId(query.id),subject:searchText(query.subject)||undefined,
      discipline:expectId(query.discipline)};
    const fallback=parts[0]==='personal'?'overview':'materials';
    const allowed=student()?Object.keys(tabs):employeeTabs;
    const active=allowed.includes(query.tab)&&!(parts[0]==='personal'&&['materials','announcements'].includes(query.tab))?query.tab:fallback;
    const tab=active===fallback?undefined:active;
    if(active==='materials')return materialQuery(query);
    return {tab,offset:['works','announcements'].includes(active)?expectId(query.offset):undefined};
  }

  async function catalog(query){
    const [index,learning,results]=await Promise.all([
      c.api('disciplines'),
      student()?c.api('learning/courses'):null,
      query.q||query.teacher||query.kind||query.sort||query.offset||query.discipline?c.api(path('materials',query)):null,
    ]);
    const personal=learning?.items||[];
    const matches=personal.filter(row=>query.id?row.id===query.id:row.subject===query.subject);
    const exact=matches.length===1?matches[0]:null;
    const enrolled=index.items.filter(row=>row.mine&&row.title===query.subject);
    const fallback=enrolled.length===1?{parts:[String(enrolled[0].id)]}:null;
    const jump=exact?{parts:exact.discipline_id?[String(exact.discipline_id)]:['personal',String(exact.id)]}:fallback;
    return {index:index.items,personal,results,jump};
  }

  async function workspace(parts,query){
    const personal=parts[0]==='personal';
    const key=Number(parts.at(-1));
    const active=query.tab||(personal?'overview':'materials');
    const scope=personal?'disciplines/personal/'+key:'disciplines/'+key;
    const [record,current]=await Promise.all([
      c.api(personal?'learning/courses/'+key:scope),
      active==='materials'?c.api(path('materials',{...query,discipline:key})):
        active==='announcements'?c.api(path('announcements',{discipline:key,limit:20,offset:query.offset})):
        ['works','schedule','consultations'].includes(active)?c.api(path(scope+'/activity',{view:active,offset:query.offset})):null,
    ]);
    const progress=personal?record:active==='overview'&&record.course_id?await c.api('learning/courses/'+record.course_id):null;
    const discipline=personal?{title:record.subject,description:record.description,teachers:[],loads:[]}:record;
    return {...discipline,active,personal,progress,current,key};
  }

  async function materialDetail(key,query){
    let row;
    try{row=await c.api('materials/'+key);}
    catch(error){
      if(error.status===404)return {title:'Материал недоступен',unavailable:true};
      throw error;
    }
    const history=row.can_edit&&query.history?await c.api(path('materials/'+key+'/history',{offset:query.offset})):null;
    return {...row,history,parents:[{title:row.discipline.title,href:coursePath(row.discipline.id)}]};
  }

  async function load(page,parts,query){
    if(page==='materials-admin'){
      const [materials,options]=await Promise.all([c.api(path('materials',{...query,mine:true})),c.api('materials/assignments')]);
      return {...materials,assignments:options.items};
    }
    if(page==='material-delegations')return c.api('materials/delegations');
    if(!parts.length)return catalog(query);
    if(parts[0]==='materials')return materialDetail(parts[1],query);
    return workspace(parts,query);
  }

  function field(name,label,value='',options={}){
    const key='disc-field-'+name;
    return `<div class="field"><label for="${key}">${esc(label)}</label><input id="${key}" name="${name}" type="${options.type||'text'}" value="${esc(value)}" ${options.attrs||''}></div>`;
  }

  function choices(name,label,values,value,required=false,prefix='disc-field'){
    const key=prefix+'-'+name;
    return `<div class="field"><label for="${key}">${esc(label)}</label><select id="${key}" name="${name}" ${required?'required':''}>
      ${values.map(([key,text])=>`<option value="${esc(key)}" ${String(key)===String(value)?'selected':''}>${esc(text)}</option>`).join('')}
    </select></div>`;
  }

  function filterForm(data,{base,scope='course',query=c.state.routeContext,discipline=false}){
    const search=field('q',scope==='course'?'Поиск по материалам':'Название, автор или дисциплина',query.q,
      {type:'search',attrs:'maxlength="100" placeholder="Введите запрос"'});
    const kind=choices('kind','Тип',[['','Все типы'],...Object.entries(data?.kinds||{})],query.kind);
    const sort=choices('sort','Сортировка',Object.entries(sorts),query.sort||'newest');
    const course=discipline?choices('discipline','Дисциплина',[['','Все дисциплины'],...discipline.map(row=>[row.id,row.title])],query.discipline):'';
    const access=scope==='manage'?choices('access','Доступность',[['','Все состояния'],...Object.entries(accessLabels)],query.access):'';
    const author=query.teacher?`<input type="hidden" name="teacher" value="${Number(query.teacher)}">`:'';
    const reset=Object.values(query).some(Boolean)?link(base,'Сбросить'):'';
    return `<form class="filter-bar school-filter discipline-filter" data-discipline-filter role="search" aria-label="Поиск и фильтры">
      ${search}${kind}${course}${access}${sort}${author}
      <div class="filter-actions"><button class="outline-button" type="submit">${icon('search')} Найти</button>${reset}</div>
    </form>`;
  }

  function pagination(base,data,query=c.state.routeContext){
    if(data.total<=data.limit&&!data.offset)return '';
    const prev=data.offset?link(path(base,{...query,offset:Math.max(0,data.offset-data.limit)||undefined}),'Назад','outline-button'):'';
    const next=data.offset+data.items.length<data.total?link(path(base,{...query,offset:data.offset+data.limit}),'Следующая страница','outline-button'):'';
    const range=data.items.length?`${data.offset+1}–${Math.min(data.offset+data.items.length,data.total)} из ${data.total}`:`0 из ${data.total}`;
    return `<nav class="campus-pagination" aria-label="Страницы материалов"><span role="status">${range}</span><div>${prev}${next}</div></nav>`;
  }

  function fileLink(row){
    if(!row.file_url)return '';
    return `<a class="outline-button" href="${esc(row.file_url)}" download>${icon('download')} ${row.file?'Скачать файл':'Скачать HTML'}</a>`;
  }

  function externalLink(value){
    try{
      const url=new URL(value);
      if(url.protocol==='https:'&&!url.username&&!url.password)return `<a class="outline-button" href="${esc(url.href)}" target="_blank" rel="noopener noreferrer">Открыть ссылку ${icon('arrow')}</a>`;
    }catch{/* Material may have no external resource. */}
    return '';
  }

  function action(name,label,row){
    const key=row?` data-id="${Number(row.id)}" aria-label="${esc(label+': '+row.title)}"`:'';
    return `<button type="button" class="outline-button" data-material-action="${name}"${key}>${esc(label)}</button>`;
  }

  function newButton(discipline){
    return `<button class="primary-button" type="button" data-material-action="new" ${discipline?`data-discipline="${Number(discipline)}"`:''}>${icon('plus')} Добавить материал</button>`;
  }

  function materialMeta(row,manage=false){
    return `<ul class="school-material-meta" aria-label="Сведения о материале">
      <li>${esc(row.kind_label)}</li><li>${link(row.author.href,row.author.title,'school-card-link')}</li>
      <li>Добавлен <time datetime="${esc(row.created_at)}">${date(row.created_at)}</time></li>
      <li>Обновлён <time datetime="${esc(row.updated_at)}">${date(row.updated_at)}</time></li>
      ${manage?`<li class="material-access">${esc(accessLabels[row.access])}</li>`:''}
    </ul>`;
  }

  function resource(row){
    if(row.file){
      const size=new Intl.NumberFormat('ru-RU',{maximumFractionDigits:1}).format(row.file.size/1024);
      return `<p class="material-resource">${icon('file')} <span>${esc(row.file.name)} · ${size} КиБ</span></p>`;
    }
    if(row.url)return `<p class="material-resource">${icon('right')} <span>${esc(new URL(row.url).hostname)}</span></p>`;
    return '';
  }

  function materialRows(items,{manage=false,showDiscipline=false,level=2}={}){
    return `<ul class="material-list">${items.map(row=>`<li class="card material-row">
      <div class="material-copy"><h${level}>${link(materialPath(row.id),row.title,'school-card-link')}</h${level}>
        ${showDiscipline?link(coursePath(row.discipline.id),row.discipline.title):''}
        ${materialMeta(row,manage)}<p class="material-description">${esc(row.description)}</p>${resource(row)}
      </div>
      <div class="school-actions material-actions">${fileLink(row)}${externalLink(row.url)}
        ${manage&&row.can_edit?action('edit','Изменить',row)+(row.access!=='archived'?action('archive','Архивировать',row):''):''}
      </div></li>`).join('')}</ul>`;
  }

  function catalogView(data){
    const {index,personal,results}=data;
    const label=pages.find(page=>page.id==='courses'&&page.roles.includes(c.state.user.role)).label;
    const query=c.state.routeContext;
    const resultsView=results?catalogResults(results):'';
    const byDiscipline=new Map(personal.filter(row=>row.discipline_id).map(row=>[row.discipline_id,row]));
    const owned=index.filter(row=>row.mine);
    const personalOnly=personal.filter(row=>!row.discipline_id);
    const mine=owned.map(row=>disciplineRow(row,byDiscipline.get(row.id))).concat(personalOnly.map(legacyCourseRow));
    const other=index.filter(row=>!row.mine).map(row=>disciplineRow(row));
    return title(label,'',student()?link('/app/assignments','К сдаче работ','outline-button'):'')+
      filterForm(results||{kinds:kindLabels}, {base:'/app/courses',scope:'all',discipline:index})+
      (results?resultsView:`${mine.length?section('Ваши дисциплины',`<ul class="school-list discipline-catalog">${mine.join('')}</ul>`):''}
        ${other.length?section(mine.length?'Другие дисциплины':'Дисциплины с материалами',`<ul class="school-list discipline-catalog">${other.join('')}</ul>`):''}
        ${!mine.length&&!other.length?empty('Дисциплины пока не доступны',''):''}`);
  }

  const kindLabels={lecture:'Лекция',guide:'Методические указания',slides:'Презентация',practice:'Практическое задание',
    lab:'Лабораторная работа',extra:'Дополнительный материал'};

  function courseProgress(row){
    return `<div class="row-progress"><progress max="100" value="${Number(row.progress)}" aria-label="Прогресс по дисциплине ${esc(row.subject)}"></progress><span>${Number(row.modules_done)} из ${Number(row.modules_total)} модулей</span></div>`;
  }

  function disciplineRow(row,personal){
    return `<li><div><h3>${link(coursePath(row.id),row.title,'school-card-link')}</h3>
      <p>${personal?esc(personal.teacher):esc(row.description)}</p>
      ${personal?courseProgress(personal):''}</div><span class="discipline-count">Материалов ${Number(row.material_count)}</span></li>`;
  }

  function legacyCourseRow(row){
    return `<li><div><h3>${link(personalPath(row.id),row.subject,'school-card-link')}</h3><p>${esc(row.teacher)}</p>${courseProgress(row)}</div></li>`;
  }

  function catalogResults(data){
    const courseItems=new Map();
    for(const row of data.items){
      const discipline=row.discipline;
      if(!courseItems.has(discipline.id))courseItems.set(discipline.id,{discipline,items:[]});
      courseItems.get(discipline.id).items.push(row);
    }
    const byAuthor=data.teacher?`<p class="course-author">Материалы преподавателя ${link(data.teacher.href,data.teacher.title,'school-card-link')}</p>`:'';
    return byAuthor+(courseItems.size?[...courseItems.values()].map(({discipline,items})=>`<section class="discipline-result">
      <h2>${link(coursePath(discipline.id),discipline.title,'school-card-link')}</h2>${materialRows(items,{level:3})}</section>`).join('')
      :empty('Материалы не найдены','Измените поиск или фильтры.'))+pagination('/app/courses',data);
  }

  function courseTabs(data,base){
    const active=data.active;
    return `<nav class="discipline-tabs" aria-label="Разделы дисциплины">${Object.entries(tabs).filter(([key])=>
      (!data.personal||!['materials','announcements'].includes(key))&&(student()||employeeTabs.includes(key)))
      .map(([key,label])=>`<a href="${esc(path(base,{tab:key===(data.personal?'overview':'materials')?undefined:key}))}" data-app-link ${key===active?'aria-current="page"':''}>${esc(label)}</a>`).join('')}</nav>`;
  }

  function modules(row){
    return section('Учебные модули',courseProgress(row)+`<div class="campus-modules">${row.modules.map(module=>
      `<details class="card"><summary><b>${esc(module.title)}</b><span class="campus-pill ${module.is_done?'success':''}">${module.is_done?'Изучено':'К изучению'}</span></summary>
        <div><p class="user-text">${esc(module.content)}</p><label class="campus-module-check"><input type="checkbox" data-discipline-module="${Number(module.id)}" data-course="${Number(row.id)}" ${module.is_done?'checked':''}> Отметить модуль изученным</label></div></details>`).join('')}</div>`);
  }

  function overview(data){
    const teachers=data.teachers.length?`<ul class="school-list">${data.teachers.map(row=>`<li>${link(row.href,row.title,'school-card-link')}<p>${esc(row.position)} · ${esc(row.department)}</p></li>`).join('')}</ul>`:
      `<p>${esc(data.progress?.teacher||'Преподаватель пока не указан.')}</p>`;
    const basic=`<p class="user-text">${esc(data.description)}</p>${data.department?link(data.department.href,data.department.title):''}
      ${data.progress?`<p>${Number(data.progress.credits)} зачётных единиц</p>`:''}`;
    const groups=data.loads.length?section('Учебные группы',`<ul class="school-list">${data.loads.map(row=>
      `<li>${link('/app/teaching/'+row.id,row.group,'school-card-link')}<div class="school-actions">
        ${link('/app/teaching/'+row.id+'?tab=works','Сдача работ')}${link('/app/teaching/'+row.id+'?tab=attendance','Посещаемость')}</div></li>`).join('')}</ul>`):'';
    return `<div class="school-detail-grid"><div class="school-stack">${section('Основная информация',basic)}${data.progress?.modules.length?modules(data.progress):''}</div>
      <div class="school-stack">${section('Преподаватели',teachers)}${groups}</div></div>`;
  }

  function activity(data,base){
    const {items}=data.current;
    const row=(href,text,details)=>`<li>${link(href,text,'school-card-link')}<p>${esc(details)}</p></li>`;
    if(data.active==='schedule'){
      const value=items.map(item=>row(path('/app/schedule',{id:item.id,date:item.date}),item.title,
        [date(item.date),item.start+'–'+item.end,item.kind,item.room,item.teacher,item.status==='cancelled'?'Отменено':''].filter(Boolean).join(' · ')));
      return section('Ближайшие занятия',value.length?`<ul class="school-list">${value.join('')}</ul>`:'<p>В ближайшие 14 дней занятий нет.</p>')+
        link('/app/schedule','Открыть расписание','outline-button');
    }
    if(data.active==='consultations'){
      const value=items.map(item=>row(path('/app/consultations',{id:item.id}),item.teacher,
        [c.stamp(item.start_at)+' МСК',item.room,item.my_booking_id?'Вы записаны':item.available?'Есть места':'Мест нет'].join(' · ')));
      return section('Предстоящие консультации',value.length?`<ul class="school-list">${value.join('')}</ul>`:'<p>Свободные часы пока не опубликованы.</p>')+
        link(path('/app/consultations',{subject:data.title}),'Все консультации по дисциплине','outline-button');
    }
    if(data.active==='announcements'){
      const value=items.map(item=>row('/app/announcements/'+item.id,item.title,date(item.published_at)+' · '+item.excerpt));
      return section('Объявления по дисциплине',value.length?`<ul class="school-list">${value.join('')}</ul>`:'<p>Объявлений по этой дисциплине пока нет.</p>')+
        activityPages(base,data.current,'announcements','Страницы объявлений');
    }
    const labels={not_started:'Не начато',in_progress:'В работе',submitted:'Сдано',resubmitted:'Сдано повторно',
      in_review:'На проверке',revision_required:'На доработке',withdrawn:'Отозвано',accepted:'Принято',completed:'Завершено'};
    const value=items.map(item=>row(path('/app/assignments',{id:item.id}),item.title,
      ['Срок '+date(item.due_date),labels[item.status]].filter(Boolean).join(' · ')));
    return section('Задания по дисциплине',value.length?`<ul class="school-list">${value.join('')}</ul>`:'<p>У вас пока нет работ по этой дисциплине.</p>')+
      activityPages(base,data.current,'works','Страницы заданий');
  }

  function activityPages(base,data,tab,label){
    const {offset,more}=data;
    const prev=offset?link(path(base,{tab,offset:Math.max(0,offset-20)||undefined}),'Назад','outline-button'):'';
    const next=more?link(path(base,{tab,offset:offset+20}),'Следующая страница','outline-button'):'';
    return prev||next?`<nav class="school-actions" aria-label="${label}">${prev}${next}</nav>`:'';
  }

  function workspaceView(data){
    const base=data.personal?personalPath(data.key):coursePath(data.key);
    const action=data.can_manage&&data.active==='materials'?newButton(data.key):'';
    let body;
    if(data.active==='materials'){
      body=filterForm(data.current,{base})+(data.current.items.length?materialRows(data.current.items):
        empty('Материалы не найдены','Проверьте фильтры или вернитесь позже.'))+pagination(base,data.current);
    }else body=data.active==='overview'?overview(data):activity(data,base);
    return title(data.title,'',action)+courseTabs(data,base)+body;
  }

  function materialView(row){
    if(row.unavailable)return title(row.title,'',link('/app/courses','К дисциплинам','outline-button'));
    const slides=row.kind==='slides'&&row.source==='text';
    const base=materialPath(row.id), back=link(coursePath(row.discipline.id),'К материалам дисциплины','outline-button');
    const actions=fileLink(row)+externalLink(row.url)+(row.can_edit?action('edit','Изменить',row)+
      (row.access==='archived'?'':action('archive','Архивировать',row)):'');
    const meta=materialMeta(row,row.can_edit);
    const navigation=slides?`<nav class="school-slide-nav" aria-label="Слайды">${row.sections.map((part,i)=>
      `<button type="button" class="mini-link" data-material-part="${i}">${esc(part.heading)}</button>`).join('')}</nav>`:'';
    const content=row.sections.length?`<article class="card card-pad school-reader ${slides?'school-slides':''}">${row.sections.map((part,i)=>
      `<section id="material-part-${i}" tabindex="-1">${part.heading?`<h2>${esc(part.heading)}</h2>`:''}
        ${part.paragraphs.map(text=>`<p>${esc(text)}</p>`).join('')}</section>`).join('')}</article>`:'';
    return title(row.title,row.description,actions,meta)+`<div class="material-detail-path school-actions">${back}
      ${row.can_edit?link(row.history?base:path(base,{history:'1'}),row.history?'Скрыть историю':'История изменений'):''}
      </div>${row.file||row.url?section(row.file?'Вложение':'Ссылка',resource(row)):''}
      ${navigation}${content}${row.history?historyView(base,row.history):''}`;
  }

  function historyView(base,history){
    const events={created:'Добавлен',edited:'Изменён',access_changed:'Изменена доступность',archived:'Архивирован'};
    const rows=history.items.map(row=>`<li><strong>${esc(events[row.action])}</strong><p>${esc(row.author)} ·
      <time datetime="${esc(row.created_at)}">${date(row.created_at)} · ${c.stamp(row.created_at).split(', ').at(-1)} МСК</time></p></li>`);
    const prev=history.offset?link(path(base,{history:1,offset:Math.max(0,history.offset-50)||undefined}),'Позже'):'';
    const next=history.has_more?link(path(base,{history:1,offset:history.offset+50}),'Ранее'):'';
    return section('История изменений',rows.length?`<ul class="school-list">${rows.join('')}</ul><div class="school-actions">${prev}${next}</div>`:
      '<p>Изменений после подключения истории пока нет.</p>');
  }

  function manageView(data){
    const base='/app/materials-admin';
    return title('Публикации','',data.assignments.length?newButton():'')+
      filterForm(data,{base,scope:'manage',discipline:data.disciplines})+
      (data.items.length?materialRows(data.items,{manage:true,showDiscipline:true}):empty('Материалы не найдены',
        data.assignments.length?'Добавьте материал или измените фильтры.':'Для публикации требуется учебное назначение.'))+
      pagination(base,data);
  }

  function delegationsView(data){
    const roleTitle={coordinator:'Ответственный за курс',department:'Сотрудник кафедры'};
    const actor=choices('user_id','Сотрудник',[['','Выберите сотрудника'],...data.actors.map(row=>[row.id,row.name+' · '+roleTitle[row.role]])],null,true);
    const scope=choices('scope','Область полномочий',[['course','Дисциплина'],['department','Кафедра']],'course',true);
    const course=choices('course','Дисциплина',data.disciplines.map(row=>[row.id,row.title]),null,true);
    const department=choices('department','Кафедра',data.departments.map(row=>[row.id,row.title]),null,true);
    const rows=data.items.map(row=>`<li><strong>${esc(row.name)}</strong><p>${esc(row.label)}</p>
      <button class="outline-button" data-material-action="revoke" data-id="${Number(row.id)}" type="button">Отозвать</button></li>`);
    const form=data.actors.length?`<form class="card card-pad delegation-form" data-discipline-form="grant">
       ${actor}${scope}<div data-delegation-scope="course">${course}</div><div data-delegation-scope="department" hidden>${department}</div>
       <div class="inline-error" data-material-error role="alert" hidden></div>
       <button class="primary-button" type="submit">Выдать полномочие</button></form>`:'';
    return title('Полномочия по материалам','')+form+
      section('Действующие полномочия',rows.length?`<ul class="school-list">${rows.join('')}</ul>`:'<p>Полномочия по дисциплинам и кафедрам пока не назначены.</p>');
  }

  function render(page,data){
    if(page==='material-delegations')return delegationsView(data);
    if(page==='materials-admin')return manageView(data);
    if(!c.state.routeParts.length)return catalogView(data);
    if(c.state.routeParts[0]==='materials')return materialView(data);
    return workspaceView(data);
  }

  function afterRender(page,data){
    if(page==='courses'&&data.jump){
      const {loadingId,sessionEpoch}=c.state;
      queueMicrotask(()=>{
        if(c.state.loadingId===loadingId&&c.state.sessionEpoch===sessionEpoch)c.route('courses',{...data.jump,replace:true});
      });
    }
    if(page==='material-delegations')toggleDelegation(c.$('.delegation-form'));
  }

  function textarea(name,label,value,attrs){
    return `<div class="field"><label for="disc-field-${name}">${esc(label)}</label><textarea id="disc-field-${name}" name="${name}" ${attrs}>${esc(value)}</textarea></div>`;
  }

  function fileInput(name,label){
    return `<div class="field discipline-file"><label for="disc-field-${name}">${esc(label)}</label>
      <input id="disc-field-${name}" name="${name}" type="file" accept="${formats.map(ext=>'.'+ext).join(',')}" aria-describedby="disc-file-hint-${name}">
      <small class="hint" id="disc-file-hint-${name}">PDF, DOCX, PPTX, XLSX, PNG, JPEG, TXT или MD, до 5 МиБ.</small></div>`;
  }

  async function readUpload(file){
    if(!file?.name)return undefined;
    const extension=file.name.split('.').at(-1).toLowerCase();
    if(!file.size||file.size>maxFileSize||!formats.includes(extension))throw new Error('Выберите файл разрешённого формата до 5 МиБ.');
    const data=await new Promise((resolve,reject)=>{
      const reader=new FileReader();
      reader.addEventListener('load',()=>resolve(reader.result));
      reader.addEventListener('error',()=>reject(new Error('Не удалось прочитать файл. Выберите его снова.')));
      reader.readAsDataURL(file);
    });
    return {name:file.name,content:data.slice(data.indexOf(',')+1)};
  }

  function toggleMaterialFields(form){
    const source=form.elements.source.value;
    for(const group of form.querySelectorAll('[data-material-source]')){
      group.hidden=group.dataset.materialSource!==source;
      group.disabled=group.hidden;
    }
    form.elements.file.required=source==='file'&&form.dataset.hasFile!=='true';
  }

  function toggleDelegation(form){
    if(!form)return;
    const value=form.elements.scope.value;
    for(const group of form.querySelectorAll('[data-delegation-scope]')){
      group.hidden=group.dataset.delegationScope!==value;
      group.querySelector('select').disabled=group.hidden;
    }
  }

  function formActions(submit,danger=false){
    return `<div class="inline-error" data-material-error role="alert" hidden></div><div class="modal-actions">
      <button class="outline-button" type="button" data-action="close-modal">Отмена</button>
      <button class="${danger?'danger-button':'primary-button'}" type="submit">${esc(submit)}</button></div>`;
  }

  function editor(options,row,discipline){
    const assignments=options.items.filter(item=>!discipline||item.discipline_id===discipline);
    if(!assignments.length){c.toast('Доступного учебного назначения нет.');return;}
    const selected=row?.assignment_id??assignments[0].id;
    const name=row?'Изменить материал':'Добавить материал';
    const availability=Object.entries(accessLabels).filter(([key])=>key!=='archived'||row?.access==='archived');
    const select=(field,label,items,value)=>choices(field,label,items,value,true,'material-editor');
    c.modal(c.modalHead(name,'')+`<form data-discipline-form="material" data-id="${row?.id||''}" data-version="${row?.version||''}" data-has-file="${Boolean(row?.file)}">
      ${select('assignment_id','Дисциплина и преподаватель',assignments.map(item=>[item.id,item.discipline+' · '+item.author]),selected)}
      <div class="discipline-form-grid">${select('kind','Тип материала',Object.entries(options.kinds),row?.kind||'lecture')}
      ${select('access','Доступность',availability,row?.access||'group')}</div>
      ${field('title','Название',row?.title,{attrs:'required minlength="4" maxlength="180"'})}
      ${textarea('description','Описание',row?.description,'required rows="2" minlength="10" maxlength="600"')}
      ${select('source','Содержание',Object.entries(sources),row?.source||'text')}
      <fieldset class="material-source-fields" data-material-source="file">${row?.file?`<p class="hint">Текущий файл: ${esc(row.file.name)}</p>`:''}
        ${fileInput('file',row?.file?'Заменить файл':'Выбрать файл')}</fieldset>
      <fieldset class="material-source-fields" data-material-source="link">${field('url','HTTPS-ссылка',row?.url,
        {type:'url',attrs:'required maxlength="1000" placeholder="https://"'})}</fieldset>
      <fieldset class="material-source-fields" data-material-source="text">${textarea('body','Текст материала',row?.body,
        'required rows="8" minlength="20" maxlength="6000" aria-describedby="material-text-hint"')}
        <p class="hint" id="material-text-hint">Для текстовой презентации добавьте минимум два слайда. Каждый заголовок начните с «## ».</p></fieldset>
      ${formActions(row?'Сохранить изменения':'Добавить материал')}</form>`,{label:name});
    toggleMaterialFields(c.$('.modal [data-discipline-form]'));
  }

  async function openEditor(button){
    const {sessionEpoch,loadingId,modalId}=c.state;
    const kind=button.dataset.materialAction, key=Number(button.dataset.id);
    const current=()=>sessionEpoch===c.state.sessionEpoch&&loadingId===c.state.loadingId&&modalId===c.state.modalId&&button.isConnected;
    button.disabled=true;
    try{
      if(kind==='revoke'){
        return c.modal(c.modalHead('Отозвать полномочие','')+`<form data-discipline-form="revoke" data-id="${key}">
          <p>Сотрудник потеряет предоставленный доступ к управлению материалами.</p>${formActions('Отозвать',true)}</form>`,{label:'Отозвать полномочие'});
      }
      const [row,options]=await Promise.all([key?c.api('materials/'+key):null,
        kind==='archive'?null:c.api('materials/assignments')]);
      if(!current())return;
      if(kind==='archive'){
        return c.modal(c.modalHead('Архивировать материал',row.title)+`<form data-discipline-form="archive" data-id="${key}" data-version="${row.version}">
          <p>Студенты потеряют доступ к материалу и файлу. В архиве сохранятся запись, вложение и история изменений.</p>
          ${formActions('Архивировать',true)}</form>`,{label:'Архивировать материал'});
      }
      editor(options,row,expectId(button.dataset.discipline));
    }catch(error){if(!error.stale&&current())c.toast(error.message);}
    finally{button.disabled=false;}
  }

  async function submit(form){
    if(c.state.pending)return;
    const {sessionEpoch}=c.state, kind=form.dataset.disciplineForm, key=Number(form.dataset.id);
    const values=Object.fromEntries(new FormData(form)), errorBox=c.$('[data-material-error]',form);
    const controls=[...form.elements].filter(control=>!control.disabled);
    c.state.pending++;
    errorBox.hidden=true;
    controls.forEach(control=>{control.disabled=true;});
    let saved=false, receiptFingerprint;
    try{
      if(kind==='archive'){
        await c.api(`materials/${key}?version=${Number(form.dataset.version)}`,{method:'DELETE'});
      }else if(kind==='revoke'){
        await c.api('materials/delegations/'+key,{method:'DELETE'});
      }else if(kind==='grant'){
        await c.api('materials/delegations',{method:'POST',body:JSON.stringify({user_id:Number(values.user_id),
          scope:values.scope,scope_id:Number(values[values.scope])})});
      }else{
        const {assignment_id,kind,access,source,title,description}=values;
        const payload={assignment_id:Number(assignment_id),kind,access,source,title,description};
        if(source==='text')payload.body=values.body;
        if(source==='link')payload.url=values.url;
        if(source==='file')payload.file=await readUpload(values.file);
        if(sessionEpoch!==c.state.sessionEpoch||!form.isConnected)return;
        if(key)payload.version=Number(form.dataset.version);
        const body=JSON.stringify(payload);
        if(!key){
          const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(body));
          receiptFingerprint=Array.from(new Uint8Array(digest),byte=>byte.toString(16).padStart(2,'0')).join('');
          if(sessionEpoch!==c.state.sessionEpoch||!form.isConnected)return;
          if(!receipts.has(receiptFingerprint))receipts.set(receiptFingerprint,crypto.randomUUID());
        }
        await c.api(key?'materials/'+key:'materials',{method:key?'PATCH':'POST',body,
          headers:key?undefined:{'Idempotency-Key':receipts.get(receiptFingerprint)}});
      }
      saved=true;
    }catch(error){
      if(!error.stale&&sessionEpoch===c.state.sessionEpoch&&form.isConnected){
        controls.forEach(control=>{control.disabled=false;});
        errorBox.textContent=error.message;
        errorBox.hidden=false;
        c.showFieldErrors(error,form);
      }
    }finally{
      if(sessionEpoch===c.state.sessionEpoch){
        c.state.pending=Math.max(0,c.state.pending-1);
        controls.forEach(control=>{control.disabled=false;});
      }
    }
    if(!saved||sessionEpoch!==c.state.sessionEpoch)return;
    receipts.delete(receiptFingerprint);
    c.closeModal({force:true});
    c.toast(({archive:'Материал перенесён в архив.',revoke:'Полномочие отозвано.',grant:'Полномочие выдано.'})[kind]||
      (key?'Изменения сохранены.':'Материал добавлен.'));
    await c.updatePage({quiet:true});
  }

  async function saveModule(input){
    if(c.state.pending){input.checked=!input.checked;return;}
    const {sessionEpoch}=c.state, module=input.dataset.disciplineModule, key=input.dataset.course;
    input.disabled=true;
    c.state.pending++;
    try{
      const course=await c.api(`learning/courses/${key}/modules/${module}`,{method:'POST',body:JSON.stringify({is_done:input.checked})});
      if(sessionEpoch!==c.state.sessionEpoch||!input.isConnected)return;
      c.state.data.courses.progress=course;
      const badge=input.closest('details').querySelector('.campus-pill');
      badge.textContent=input.checked?'Изучено':'К изучению';
      badge.classList.toggle('success',input.checked);
      const progress=input.closest('.school-section').querySelector('.row-progress');
      progress.querySelector('progress').value=course.progress;
      progress.querySelector('span').textContent=`${course.modules_done} из ${course.modules_total} модулей`;
      c.toast('Прогресс модуля сохранён.');
    }catch(error){
      if(!error.stale){input.checked=!input.checked;c.toast(error.message);}
    }finally{
      if(sessionEpoch===c.state.sessionEpoch)c.state.pending=Math.max(0,c.state.pending-1);
      input.disabled=false;
    }
  }

  function init(context){
    c=context;
    document.addEventListener('click',event=>{
      const action=event.target.closest('[data-material-action]');
      if(action&&!c.state.pending)openEditor(action);
      const part=event.target.closest('[data-material-part]');
      if(part)c.$('#material-part-'+Number(part.dataset.materialPart))?.focus();
    });
    document.addEventListener('submit',event=>{
      const form=event.target;
      if(form.hasAttribute('data-discipline-filter')){
        event.preventDefault();
        const query=Object.fromEntries(new FormData(form));
        c.route(c.state.page,{parts:c.state.routeParts,context:query});
      }else if(form.dataset.disciplineForm){
        event.preventDefault();
        submit(form);
      }
    });
    document.addEventListener('input',event=>{
      const form=event.target.form;
      if(form?.dataset.disciplineForm==='material')form.dataset.dirty='true';
    });
    document.addEventListener('change',event=>{
      const input=event.target, form=input.form;
      if(form?.dataset.disciplineForm==='material'){
        form.dataset.dirty='true';
        if(input.name==='source')toggleMaterialFields(form);
      }else if(form?.dataset.disciplineForm==='grant'&&input.name==='scope')toggleDelegation(form);
      else if(input.dataset.disciplineModule)saveModule(input);
    });
  }

  window.ATLASDisciplines={pages,has,validParts,cleanQuery,legacyRoute,load,render,afterRender,init,
    reset:()=>receipts.clear(),coursePath,materialPath,fileInput,readUpload};
})();
