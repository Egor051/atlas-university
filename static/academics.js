(() => {
  'use strict';
  let c, restoreFilters, refreshPoints;
  const queue = {id:'absence-certificates', label:'Справки о пропусках', icon:'certificate',
    hint:'Документы студентов и решения об уважительных пропусках', roles:['teacher']};
  const pointKinds = {opening:'Баланс при переносе', teacher:'Начисление преподавателем',
    assignment:'Проверенная работа', assignment_correction:'Корректировка оценки',
    teacher_correction:'Корректировка начисления'};
  const lessonKinds = {lecture:'Лекции', practice:'Практические занятия', lab:'Лабораторные работы'};
  const attendanceLabels = {present:'Присутствовал', absent:'Отсутствовал', excused:'Уважительный пропуск',
    unmarked:'Статус не выставлен', cancelled:'Занятие отменено', late:'Опоздал'};
  const certificateLabels = {pending:'На рассмотрении', accepted:'Принята', rejected:'Отклонена'};
  const pointColumns = [
    ['discipline','Дисциплина'], ['points','Баллы'], ['day','Дата'], ['title','Занятие или работа'],
    ['kind_label','Вид работы'], ['teacher','Преподаватель'], ['max_points','Максимум за работу'],
    ['result','Сведения о результате'],
  ];
  const attendanceColumns = [
    ['discipline','Дисциплина'], ['status_label','Посещение'], ['day','Дата и время'], ['kind_label','Вид занятия'],
    ['teacher','Преподаватель'], ['group','Группа или подгруппа'], ['title','Занятие'],
  ];
  const collator = new Intl.Collator('ru', {numeric:true, sensitivity:'base'});
  const dayFormatter = new Intl.DateTimeFormat('ru-RU', {day:'2-digit', month:'2-digit', year:'numeric'});
  const pointFormatter = new Intl.NumberFormat('ru-RU', {maximumFractionDigits:1});
  const format = value => pointFormatter.format(value);
  const registerPath = 'learning/point-register';
  const esc = value => c.esc(value);
  const text = value => esc(value ?? '—');
  const dayFmt = value => dayFormatter.format(c.asDate(value));
  const day = value => value ? '<time datetime="'+esc(value)+'">'+dayFmt(value)+'</time>' : '—';
  const stamp = value => value ? '<time datetime="'+esc(value)+'">'+c.stamp(value)+' МСК</time>' : '—';
  const signed = value => value > 0 ? '+'+value : String(value);
  const paragraph = value => value ? '<p class="user-text academic-note">'+esc(value)+'</p>' : '';
  const badge = (label, tone='') => '<span class="campus-pill '+tone+'">'+esc(label)+'</span>';
  const certificateBadge = status => badge(certificateLabels[status], {
    accepted:'success', rejected:'warning',
  }[status]);
  const option = ([value,label]) => '<option value="'+esc(value)+'">'+esc(label)+'</option>';
  const select = (prefix, name, label, choices) => '<div class="filter-field"><label for="'+prefix+name+'">'+label+
    '</label><select id="'+prefix+name+'" name="'+name+'">'+choices.map(option).join('')+'</select></div>';
  const search = value => String(value ?? '').toLocaleLowerCase('ru').replaceAll('ё','е');
  const attendanceRow = row => ({...row,status_label:attendanceLabels[row.status]});
  const pointRow = row => ({...row,discipline:row.subject});

  async function loadStudent(){
    const [points,attendance] = await Promise.all([c.api(registerPath),c.api('learning/attendance-register')]);
    return {points,attendance};
  }

  function showAward(item, actions=''){
    const value = signed(Number(item.points));
    const cap = item.max_points==null ? '' : ' из '+Number(item.max_points);
    return '<li><b>'+esc(value+cap)+'</b> · '+esc(item.title||pointKinds[item.source_kind]||'Начисление')+
      (item.kind_label?' · '+esc(item.kind_label):'')+
      (item.effective_points!=null&&item.effective_points!==item.points?
        '<p>После корректировки · '+Number(item.effective_points)+'</p>':'')+
      (item.created_at?stamp(item.created_at):'')+paragraph(item.reason)+actions+'</li>';
  }

  function pointsCells(row){
    const assignmentId = Number(row.assignment_id);
    const title = assignmentId ? '<a href="/app/assignments?id='+assignmentId+
      '" data-route="assignments" data-record-id="'+assignmentId+'">'+esc(row.title)+'</a>' :
      classLink(row.class_id,row.class_day,row.title);
    const adjusted = row.entry_type==='correction';
    const points = adjusted ? signed(row.points) : text(row.points);
    const change = adjusted && row.previous_points!=null
      ? '<br><small>'+Number(row.previous_points)+' → '+Number(row.corrected_points)+'</small>' : '';
    return [
      '<strong>'+points+'</strong>'+change, day(row.day), title,
      text(row.kind_label), text(row.teacher||'—'), text(row.max_points),
      (row.result?esc(row.result):'')+(row.note!==row.result?paragraph(row.note):'')||'—',
    ];
  }
  function classLink(id, date, label){
    if(!id||!date)return text(label);
    const params = new URLSearchParams({date,id:1000000000+Number(id)});
    return '<a href="/app/schedule?'+esc(params)+'" data-app-link>'+esc(label)+'</a>';
  }
  function attendanceCells(row){
    const tone = ['present','excused'].includes(row.status) ? 'success' : row.status==='absent' ? 'warning' : '';
    const doc = row.certificate;
    const upload = row.can_submit
      ? '<button class="mini-link academic-row-action" type="button" data-absence-send="'+esc(row.id)+'">Отправить справку</button>' : '';
    const caseButton = doc
      ? '<button class="mini-link academic-row-action" type="button" data-absence-view="'+esc(row.id)+'">Решение по справке</button>' : '';
    const status = badge(row.status_label,tone)+(doc?certificateBadge(doc.status):'')+upload+caseButton;
    return [
      '<div class="academic-row-status">'+status+'</div>', day(row.day)+
        '<small class="academic-meta">'+esc(row.start)+'–'+esc(row.end)+' МСК</small>',
      text(row.kind_label), text(row.teacher||'—'), esc([row.group,row.subgroup].filter(Boolean).join(' · ')||'—'),
      classLink(row.class_id,row.day,row.title),
    ];
  }
  function rowsHTML(rows, cells){
    return rows.map(row => '<tr'+(row.grade_id?' data-record-id="'+Number(row.grade_id)+'"':'')+
      (row.id?' data-academic-record="'+esc(row.id)+'"':'')+'><th scope="row">'+esc(row.discipline)+'</th>'+
      cells(row).map(html => '<td>'+html+'</td>').join('')+'</tr>').join('');
  }

  function filterOptions(rows, key, labelKey=key){
    const options = new Map(rows.filter(row=>row[key]).map(row=>[row[key],row[labelKey]]));
    return [...options].sort((a,b)=>collator.compare(a[1],b[1]));
  }
  function disciplineOptions(rows, attendance){
    return [['','Все дисциплины'],...filterOptions(rows,attendance?'discipline':'discipline_key','discipline')];
  }
  function filters(rows, attendance){
    const prefix = attendance ? 'attendance-filter-' : 'points-filter-';
    return '<div class="academic-filters">'+
      select(prefix,'discipline','Дисциплина',disciplineOptions(rows,attendance))+
      select(prefix,'kind',attendance?'Вид занятия':'Вид работы',[['','Все виды'],...(attendance?
        Object.entries(lessonKinds):filterOptions(rows,'kind_label'))])+
      select(prefix,'grouping','Группировка',[['','Без группировки'],['discipline','По дисциплине'],
        ['kind',attendance?'По дисциплине и виду':'По дисциплине и виду работы']])+
      (attendance?select(prefix,'status','Отметка',[['','Все отметки'],...Object.entries(attendanceLabels)]):'')+
      '</div><details class="academic-extra-filters"><summary>Поиск и период</summary><div class="academic-filters">'+
      '<label class="filter-field">Поиск<input type="search" name="search" autocomplete="off" maxlength="130" '+
        'placeholder="Дисциплина, преподаватель…"></label>'+
      '<label class="filter-field">С даты<input type="date" name="from"></label>'+
      '<label class="filter-field">По дату<input type="date" name="to"></label>'+
      '</div></details>';
  }

  function tablePanel(rows, columns, attendance, term, availabilityMessage){
    const id = attendance ? 'academic-attendance' : 'academic-points';
    const title = attendance ? 'Посещаемость занятий' : 'История начислений';
    const scope = attendance ? '<p>'+(term ? esc(term.label)+' · '+day(term.starts_on)+' — '+day(term.ends_on) :
      'Учебный семестр не опубликован')+'</p>' : '';
    return '<section class="card card-pad academic-panel" aria-labelledby="'+id+'" data-academic-table '+
      'data-type="'+(attendance?'attendance':'points')+'"><header class="academic-panel-head"><h2 id="'+id+
      '" tabindex="-1">'+title+'</h2>'+scope+'</header>'+
      (availabilityMessage?'<p class="academic-availability">'+esc(availabilityMessage)+'</p>':'')+
      filters(rows,attendance)+(attendance?'<div data-attendance-counts class="academic-counts"></div>':'')+
      '<p class="academic-result-count" role="status" data-academic-count></p>'+
      '<p class="academic-scroll-hint">Прокрутите таблицу, чтобы увидеть остальные столбцы.</p>'+
      '<div class="academic-scroll" tabindex="0" role="region" aria-label="Прокрутка таблицы «'+title+'»"><table class="academic-table"'+
      ' aria-labelledby="'+id+'"><thead><tr>'+columns.map(([key,label])=>
        '<th scope="col" aria-sort="none"><button type="button" data-academic-sort="'+key+'">'+label+
          ' <span aria-hidden="true">↕</span></button></th>').join('')+
      '</tr></thead><tbody></tbody></table></div></section>';
  }
  function semesterPanel(){
    return '<section class="card card-pad academic-panel" aria-labelledby="academic-semester" data-semester-panel>'+
      '<header class="academic-panel-head"><h2 id="academic-semester">Семестровая успеваемость</h2></header>'+
      '<div class="academic-filters academic-period-controls">'+select('period-','year','Учебный год',[])+
      select('period-','semester','Семестр',[])+'</div><p class="academic-meta" role="status" data-semester-dates></p>'+
      '<p class="academic-semester-empty" data-semester-empty hidden></p>'+
      '<table class="academic-semester-table" aria-labelledby="academic-semester"><thead><tr>'+
      '<th scope="col">Дисциплина</th><th scope="col">Набрано</th><th scope="col" aria-label="Выполнение">'+
      '<span class="academic-percent-label">Выполнение</span><span class="academic-percent-short" aria-hidden="true">%</span></th>'+
      '</tr></thead><tbody></tbody></table></section>';
  }
  function semesterDetails(row){
    const byKind = row.breakdown.map(kind=>'<div><dt>'+esc(kind.label)+'</dt><dd>'+format(kind.points)+'</dd></div>');
    const dates = [...row.timeline].reverse().map(item=>'<tr><th scope="row">'+day(item.day)+'</th><td>'+esc(signed(item.change))+
      '</td><td><strong>'+format(item.total)+'</strong></td></tr>');
    if(!dates.length)return '<p class="academic-meta">Начислений по дисциплине пока нет.</p>';
    return '<div class="academic-semester-details"><section><h3>Баллы по видам деятельности</h3><dl>'+byKind.join('')+'</dl></section>'+
      '<section><h3>Динамика начислений</h3><div class="academic-timeline"'+(dates.length>4?
        ' tabindex="0" role="region" aria-label="Прокрутка динамики начислений"':'')+'><table aria-label="Динамика начислений">'+
      '<thead><tr><th scope="col">Дата</th><th scope="col">Изменение</th><th scope="col">Итого</th></tr></thead><tbody>'+
      dates.join('')+'</tbody></table></div></section></div><a class="mini-link academic-history-link" href="#academic-points" '+
      'data-semester-history="'+esc(row.key)+'">К истории дисциплины '+c.icon('arrow')+'</a>';
  }
  function semesterRow(row, open){
    const key = esc(row.key), detailId = 'semester-detail-'+key;
    const percentage = row.percent===null ? '—' : format(row.percent)+' %';
    return '<tr class="academic-semester-row"'+(row.grade_id?' data-record-id="'+Number(row.grade_id)+'"':'')+'>'+
      '<th scope="row"><button type="button" data-semester-discipline="'+key+'" aria-expanded="'+open+
      '" aria-controls="'+detailId+'">'+c.icon('right')+'<span>'+esc(row.subject)+'</span></button></th>'+
      '<td><strong class="academic-earned">'+format(row.earned_points)+'</strong><small class="academic-meta">'+
      (row.max_points===null?'макс. —':'из '+format(row.max_points))+'</small></td><td><span class="academic-percent">'+
      percentage+'</span>'+(row.percent===null?'':'<progress aria-hidden="true" max="100" value="'+
      Math.min(100,row.percent)+'"></progress>')+'</td></tr><tr class="academic-semester-detail" id="'+detailId+'"'+
      (open?'':' hidden')+'><td colspan="3">'+(open?semesterDetails(row):'')+'</td></tr>';
  }
  function renderStudent(data){
    const links = '<a class="outline-button" href="#academic-attendance" data-academic-jump>К посещаемости '+c.icon('arrow')+'</a>'+
      '<a class="outline-button" data-route="exams" href="/app/exams">Сессия и зачёты '+c.icon('right')+'</a>';
    return c.head('','Успеваемость и посещаемость','',links)+'<div class="academic-registers">'+
      semesterPanel()+tablePanel([],pointColumns,false)+
      tablePanel(data.attendance.items.map(attendanceRow),attendanceColumns,true,data.attendance.term,
        data.attendance.availability_message)+'</div>';
  }

  function counts(rows){
    const totals = {present:0, absent:0, excused:0, unmarked:0, late:0, cancelled:0};
    for(const row of rows)totals[row.status]++;
    return [
      ['Проведено',rows.length-totals.cancelled], ['Посещено',totals.present+totals.late],
      ['Пропущено',totals.absent+totals.excused], ['Из них уважительных',totals.excused], ['Без отметки',totals.unmarked],
    ];
  }
  function attendanceCounts(rows){
    return Object.entries(lessonKinds).map(([kind,label])=>'<section aria-label="'+label+'"><h3>'+label+
      '</h3><dl>'+counts(rows.filter(row=>row.kind===kind)).map(([name,value])=>
        '<div><dt>'+name+'</dt><dd>'+value+'</dd></div>').join('')+'</dl></section>').join('');
  }

  function groupRows(rows, group, columnCount, cells, attendance){
    if(!group)return '<tbody>'+rowsHTML(rows,cells)+'</tbody>';
    const groups = new Map();
    for(const row of rows){
      const key = group==='kind' ? row.discipline+' · '+row.kind_label : row.discipline;
      if(!groups.has(key))groups.set(key,[]);
      groups.get(key).push(row);
    }
    return [...groups].sort((a,b)=>collator.compare(a[0],b[0])).map(([label,items])=>{
      const totals = attendance ? counts(items).map(([name,n])=>name+' '+n).join(' · ') :
        'Баллы в строках · '+format(items.reduce((sum,row)=>sum+row.points,0));
      return '<tbody><tr class="academic-group"><th scope="rowgroup" colspan="'+columnCount+'">'+esc(label)+
        (totals?'<small class="academic-meta">'+esc(totals)+'</small>':'')+'</th></tr>'+rowsHTML(items,cells)+'</tbody>';
    }).join('');
  }
  function filterValues(root){
    return [...root.querySelectorAll('[data-academic-table]')].map(panel=>{
      const values = Object.fromEntries([...panel.querySelectorAll('[name]')].map(control=>[control.name,control.value]));
      const active = panel.querySelector('th:not([aria-sort=none])');
      return {...values,sort:active?.firstElementChild.dataset.academicSort,
        direction:active?.getAttribute('aria-sort'),expanded:panel.querySelector('details').open,
        top:panel.querySelector('.academic-scroll').scrollTop,left:panel.querySelector('.academic-scroll').scrollLeft};
    });
  }
  function bindTable(panel, rows, {attendance, saved, subject, date}){
    const table = panel.querySelector('table');
    const region = panel.querySelector('.academic-scroll');
    const indicator = panel.querySelector('[data-academic-count]');
    const controls = Object.fromEntries([...panel.querySelectorAll('[name]')].map(control=>[control.name,control]));
    const columns = attendance ? attendanceColumns : pointColumns;
    let sort = saved?.sort||'day', direction = saved?.direction||'descending';
    const initial = saved||{discipline:attendance?subject:rows.find(row=>row.discipline===subject)?.discipline_key,from:date,to:date};
    function historyOptions(discipline,kind){
      const options = [[controls.discipline,disciplineOptions(rows,false),discipline],
        [controls.kind,[['','Все виды'],...filterOptions(rows,'kind_label')],kind]];
      for(const [control,choices,value] of options){
        control.innerHTML=choices.map(option).join('');
        control.value=choices.some(([key])=>key===value)?value:'';
      }
    }
    if(!attendance)historyOptions(initial.discipline,initial.kind);
    for(const [name,control] of Object.entries(controls)){
      if(initial[name]!=null)control.value=initial[name];
      // A scope link can lead to a discipline that has no rows yet.
      if(control instanceof HTMLSelectElement && control.selectedIndex<0)control.selectedIndex=0;
    }
    if(initial.expanded||date)panel.querySelector('details').open=true;

    function update(){
      const query = search(controls.search.value.trim());
      const scope = rows.filter(row =>
        (!controls.discipline.value || (attendance?row.discipline:row.discipline_key)===controls.discipline.value) &&
        (!controls.kind.value || (attendance?row.kind:row.kind_label)===controls.kind.value) &&
        (!controls.from.value || row.day && row.day>=controls.from.value) &&
        (!controls.to.value || row.day && row.day<=controls.to.value) &&
        (!query || search([row.discipline,row.title,row.teacher,row.group,row.subgroup].join(' ')).includes(query)));
      const visible = scope.filter(row=>!controls.status?.value||row.status===controls.status.value);
      visible.sort((a,b)=>{
        const x=a[sort], y=b[sort];
        if(x==null||y==null)return Number(x==null)-Number(y==null);
        const result = typeof x==='number'&&typeof y==='number' ? x-y : collator.compare(x,y);
        const time = sort==='day' ? (a.start||a.created_at||'').localeCompare(b.start||b.created_at||'') : 0;
        return (result||time)*(direction==='ascending'?1:-1);
      });
      table.querySelectorAll('tbody').forEach(body=>body.remove());
      const message = rows.length ? 'По выбранным условиям записей нет.' :
        attendance ? 'В текущем семестре пока нет завершённых занятий.' : 'Начислений и оценённых работ пока нет.';
      const body = visible.length ? groupRows(visible,controls.grouping.value,columns.length,
        attendance?attendanceCells:pointsCells,attendance) :
        '<tbody><tr><td colspan="'+columns.length+'">'+message+'</td></tr></tbody>';
      table.insertAdjacentHTML('beforeend',body);
      indicator.textContent='Строк в таблице · '+visible.length+
        (attendance||!visible.length?'':' · Баллы в выбранных строках '+format(visible.reduce((sum,row)=>sum+row.points,0)));
      if(attendance)panel.querySelector('[data-attendance-counts]').innerHTML=attendanceCounts(scope);
      for(const button of table.querySelectorAll('[data-academic-sort]')){
        const picked = button.dataset.academicSort===sort;
        button.closest('th').setAttribute('aria-sort',picked?direction:'none');
        button.querySelector('span').textContent=picked?(direction==='ascending'?'↑':'↓'):'↕';
      }
      region.scrollTop=0;
    }

    for(const input of Object.values(controls)){
      input.addEventListener(input.type==='search'?'input':'change',update);
    }
    table.addEventListener('click',event=>{
      const button = event.target.closest('[data-academic-sort]');
      if(!button)return;
      const key = button.dataset.academicSort;
      direction = key===sort&&direction==='ascending'?'descending':'ascending';
      sort=key;
      update();
    });
    update();
    if(saved){region.scrollTop=saved.top;region.scrollLeft=saved.left;}
    return (next, discipline=controls.discipline.value, reset=false)=>{
      rows=next;
      if(reset)for(const key of ['kind','search','from','to'])controls[key].value='';
      historyOptions(discipline,controls.kind.value);
      update();
    };
  }
  function showSection(heading){
    heading.scrollIntoView({block:'start',behavior:'instant'});
    heading.focus({preventScroll:true});
  }
  const yearKey = period => String(period.academic_year??period.id);

  function bindSemesters(root,data,context,saved){
    const panel = root.querySelector('[data-semester-panel]');
    const table = panel.querySelector('table');
    const body = table.querySelector('tbody');
    const year = panel.querySelector('[name=year]'), term = panel.querySelector('[name=semester]');
    const history = root.querySelector('[data-type=points]');
    const historyHeading = history.querySelector('h2');
    const historyFilter = history.querySelector('[name=discipline]');
    const scroll = history.querySelector('.academic-scroll');
    const findPeriod = id => data.points.periods.find(period=>period.id===id);
    const gradeId = Number(context.id);
    const matching = data.points.items.filter(row=>row.grade_id===gradeId||context.subject&&row.subject===context.subject);
    const current = findPeriod(data.points.default_period);
    const currentMatch = matching.find(row=>row.period===current.id)||
      current.disciplines.find(row=>row.grade_id===gradeId||row.subject===context.subject);
    let selected = findPeriod(saved?.period||context.period) ||
      (!currentMatch && findPeriod(matching[0]?.period)) || current;
    let expanded = saved?.expanded || '';
    let historyRows = data.points.items.filter(row=>row.period===selected.id).map(pointRow);
    const setHistory = bindTable(history,historyRows,{attendance:false,saved:saved?.tables[0]});

    function drawSummary(){
      const focused = table.contains(document.activeElement) ? document.activeElement : null;
      body.innerHTML = selected.disciplines.map(row=>semesterRow(row,row.key===expanded)).join('');
      if(focused?.dataset.semesterDiscipline||focused?.dataset.semesterHistory){
        const attribute = focused.dataset.semesterDiscipline ? 'semester-discipline' : 'semester-history';
        const key = CSS.escape(focused.dataset.semesterDiscipline||focused.dataset.semesterHistory);
        table.querySelector('[data-'+attribute+'="'+key+'"]')?.focus({preventScroll:true});
      }
    }
    function drawPeriod(discipline){
      const years = new Map(data.points.periods.map(period=>[yearKey(period),period.academic_year===null?
        period.label:period.academic_year+'/'+(period.academic_year+1)]));
      year.innerHTML = [...years].map(option).join('');
      year.value = yearKey(selected);
      term.innerHTML = data.points.periods.filter(period=>yearKey(period)===year.value)
        .map(period=>option([period.id,period.label])).join('');
      term.value = selected.id;
      term.closest('.filter-field').hidden = selected.academic_year===null;
      const dates = panel.querySelector('[data-semester-dates]');
      dates.innerHTML = selected.starts_on?day(selected.starts_on)+' — '+day(selected.ends_on):'';
      dates.hidden = !selected.starts_on;
      historyRows = data.points.items.filter(row=>row.period===selected.id).map(pointRow);
      const empty = panel.querySelector('[data-semester-empty]');
      table.hidden = !selected.disciplines.length;
      empty.hidden = !table.hidden;
      empty.textContent = selected.starts_on ? 'На этот период дисциплины пока не опубликованы.' :
        historyRows.length ? 'Записи без опубликованного семестра доступны в истории начислений.' :
        'Учебный семестр пока не опубликован.';
      drawSummary();
      setHistory(historyRows,discipline);
    }
    const initialDiscipline = data.points.items.find(row=>row.period===selected.id&&matching.includes(row))?.discipline_key;
    drawPeriod(saved?.tables[0]?.discipline??initialDiscipline);
    if(saved?.tables[0]){scroll.scrollTop=saved.tables[0].top;scroll.scrollLeft=saved.tables[0].left;}

    function changePeriod(period){
      if(!period||period.id===selected.id)return;
      selected = period;
      expanded = '';
      c.replaceRouteContext({...c.state.routeContext,period:period.id});
      drawPeriod();
    }
    year.addEventListener('change',()=>{
      const choices = data.points.periods.filter(period=>yearKey(period)===year.value);
      changePeriod(choices.find(period=>period.id===data.points.default_period)||
        choices.find(period=>period.starts_on<=c.today())||choices[0]);
    });
    term.addEventListener('change',()=>changePeriod(findPeriod(term.value)));
    table.addEventListener('click',event=>{
      const button = event.target.closest('[data-semester-discipline]');
      if(button){
        const key = button.dataset.semesterDiscipline;
        expanded = expanded===key?'':key;
        drawSummary();
      }
      const link = event.target.closest('[data-semester-history]');
      if(link){
        event.preventDefault();
        setHistory(historyRows,link.dataset.semesterHistory,true);
        showSection(historyHeading);
      }
    });
    if(gradeId&&!saved){
      queueMicrotask(()=>{
        const row = panel.querySelector('[data-record-id="'+gradeId+'"]')||history.querySelector('[data-record-id="'+gradeId+'"]');
        if(row?.isConnected){
          row.classList.add('search-match');
          row.tabIndex=-1;
          row.scrollIntoView({block:'nearest',behavior:'instant'});
          row.focus({preventScroll:true});
        }
      });
    }
    refreshPoints = async()=>{
      if(!panel.isConnected)return;
      const points = await c.api(registerPath,{quietAuth:true});
      if(!panel.isConnected||JSON.stringify(points)===JSON.stringify(data.points))return;
      const period = c.state.routeContext.period||(selected.id===data.points.default_period?points.default_period:selected.id);
      data.points = points;
      selected = findPeriod(period)||findPeriod(points.default_period);
      const top = scroll.scrollTop;
      drawPeriod(historyFilter.value);
      scroll.scrollTop = top;
    };
  }

  function bindStudent(root,data,context){
    const rows = data.attendance.items.map(attendanceRow);
    const points = data.points.items.map(pointRow);
    const subject = context.subject||points.find(row=>row.grade_id===Number(context.id))?.discipline;
    const saved = restoreFilters?.href===c.state.routeHref ? restoreFilters : null;
    restoreFilters = null;
    bindSemesters(root,data,context,saved);
    bindTable(root.querySelector('[data-type=attendance]'),rows,{attendance:true,subject,saved:saved?.tables[1],
      date:context.kind==='attendance'?context.date:undefined});
    const heading = root.querySelector('#academic-attendance');
    root.querySelector('[data-academic-jump]').addEventListener('click',event=>{
      event.preventDefault();
      showSection(heading);
    });
    if(saved?.row){
      const row = [...root.querySelectorAll('[data-academic-record]')].find(element=>element.dataset.academicRecord===saved.row);
      (row?.querySelector('[data-absence-view]')||heading).focus({preventScroll:true});
    }else if(context.kind==='attendance'){
      queueMicrotask(()=>{if(heading.isConnected)showSection(heading);});
    }
    root.querySelector('[data-type="attendance"]').addEventListener('click',event=>{
      const send = event.target.closest('[data-absence-send]');
      const view = event.target.closest('[data-absence-view]');
      if(send)openUpload(rows,send.dataset.absenceSend,root);
      if(view)openStudentCase(rows.find(row=>row.id===view.dataset.absenceView));
    });
  }

  function checklist(title, rows, name, selected, label){
    return '<fieldset class="academic-checklist"><legend>'+title+'</legend><div>'+
      rows.map(row=>'<label><input type="checkbox" name="'+name+'" value="'+esc(row.id)+'" '+
        (selected(row)?'checked':'')+'><span>'+label(row)+'</span></label>').join('')+'</div></fieldset>';
  }
  function occurrenceLabel(row){
    return '<strong>'+esc(row.discipline)+'</strong><small>'+day(row.day)+' · '+esc(row.start)+
      ' · '+esc(row.kind_label)+(row.teacher?' · '+esc(row.teacher):'')+'</small>';
  }
  const downloadButton = id => '<button type="button" class="outline-button" data-absence-download="'+Number(id)+
    '">'+c.icon('download')+' Скачать справку</button>';

  async function fileContent(file){
    const maximum = 5*1024*1024;
    if(!file?.size||file.size>maximum||!/\.(pdf|jpe?g|png)$/i.test(file.name)){
      throw new Error('Выберите PDF, JPG, JPEG или PNG размером до 5 МиБ.');
    }
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = '';
    for(let offset=0;offset<bytes.length;offset+=16384){
      binary+=String.fromCharCode(...bytes.subarray(offset,offset+16384));
    }
    return {name:file.name,content:btoa(binary)};
  }
  function openUpload(rows, id, root){
    const chosen = rows.find(row=>row.id===id&&row.can_submit);
    if(!chosen)return;
    const other = rows.filter(row=>row.can_submit&&row.id!==id);
    const fields = checklist('Пропуски, к которым относится справка',[chosen,...other],'occurrences',
      row=>row.id===id,occurrenceLabel)+
      '<div class="field"><label for="absence-document">Справка</label><input id="absence-document" name="document" '+
      'type="file" accept=".pdf,.jpg,.jpeg,.png" aria-describedby="absence-file-rules" required>'+
      '<p class="field-meta" id="absence-file-rules">PDF, JPG, JPEG или PNG до 5 МиБ. Файл хранится до 90 дней.</p></div>'+
      window.ATLASOperations.ui.area('note','Пояснение (необязательно)','',500);
    let previousBody, idempotencyKey;
    window.ATLASOperations.ui.modal('Отправить справку','Выберите занятия, которые подтверждает один документ.',fields,
      async (values,formData)=>{
        const occurrences = formData.getAll('occurrences');
        if(!occurrences.length||occurrences.length>30)throw new Error('Выберите от 1 до 30 пропущенных занятий.');
        const epoch = c.state.sessionEpoch;
        const file = await fileContent(values.document);
        if(epoch!==c.state.sessionEpoch)throw Object.assign(new Error('Сеанс изменился.'),{stale:true});
        const body = JSON.stringify({occurrences,file,note:values.note});
        if(body!==previousBody){previousBody=body;idempotencyKey=crypto.randomUUID();}
        return c.api('learning/absence-certificates',{method:'POST',headers:{'Idempotency-Key':idempotencyKey},
          body});
      },
      async ()=>{
        restoreFilters={href:c.state.routeHref,tables:filterValues(root),row:id,
          period:root.querySelector('#period-semester').value,
          expanded:root.querySelector('[data-semester-discipline][aria-expanded=true]')?.dataset.semesterDiscipline};
        await c.updatePage({quiet:true});
      },'Отправить справку');
  }
  function openStudentCase(row){
    if(!row?.certificate)return;
    const doc = row.certificate;
    c.modal(c.modalHead('Решение по справке',row.discipline+' · '+dayFmt(row.day))+
      certificateBadge(doc.status)+'<p class="academic-meta">Отправлена '+stamp(doc.submitted_at)+'</p>'+
      (doc.reviewed_at?'<p class="academic-meta">Рассмотрена '+stamp(doc.reviewed_at)+'</p>':'')+
      paragraph(doc.reason)+(doc.file_available?'<div class="modal-actions">'+downloadButton(doc.id)+'</div>':
        '<p class="academic-meta">Файл больше недоступен.</p>'),{label:'Решение по справке'});
  }

  function cleanQuery(_page,query){
    const id = Number(query.id), offset = Number(query.offset);
    if(Number.isSafeInteger(id)&&id>0)return {id};
    return {...(query.status==='all'||Object.hasOwn(certificateLabels,query.status)?{status:query.status}:{}),
      ...(Number.isSafeInteger(offset)&&offset>0?{offset}:{})};
  }
  function loadQueue(_page,_parts,query){
    const params = new URLSearchParams(query.id?{id:query.id}:{offset:query.offset||0});
    if(!query.id&&query.status!=='all')params.set('status',query.status||'pending');
    return c.api('teaching/absence-certificates?'+params);
  }
  function queueLink(query){
    const params = new URLSearchParams(query).toString();
    return '/app/'+queue.id+(params?'?'+params:'');
  }
  function queueRows(items){
    return items.map(item=>{
      const entries = item.entries.map(row=>'<li>'+occurrenceLabel(row)+' '+certificateBadge(row.status)+paragraph(row.reason)+'</li>');
      const actions = item.entries.some(row=>row.can_review)?
        '<button type="button" class="outline-button academic-case-action" data-absence-review="'+Number(item.id)+
        '">Рассмотреть справку</button>':'';
      return '<tr><th scope="row">'+esc(item.student)+'</th><td><ul class="academic-case-entries">'+entries.join('')+
        '</ul>'+actions+'</td><td>'+stamp(item.submitted_at)+'</td><td>'+(item.file_available?
          downloadButton(item.id)+'<small class="academic-meta">Хранится до '+day(docDate(item.expires_at))+'</small>':
          'Файл больше недоступен')+'</td><td>'+paragraph(item.note)+(item.note?'':'—')+'</td></tr>';
    }).join('');
  }
  function docDate(value){
    return value ? new Date(Date.parse(value)+3*3600000).toISOString().slice(0,10) : '';
  }
  function renderQueue(_page,data){
    const query = c.state.routeContext;
    const active = query.id ? '' : query.status||'pending';
    const choices = [['pending','На рассмотрении'],['accepted','Приняты'],['rejected','Отклонены'],['all','Все']];
    const filters = choices.map(([key,label])=>'<a class="outline-button" href="'+queueLink({status:key})+
      '" data-app-link '+(key===active?'aria-current="page"':'')+'>'+label+'</a>').join('');
    const pager = (offset,label)=>'<a class="outline-button" data-app-link href="'+
      queueLink({status:active,offset})+'">'+label+'</a>';
    const navigation = !query.id&&(data.offset||data.more) ? '<div class="academic-queue-pages">'+
      (data.offset?pager(Math.max(0,data.offset-data.limit),'Предыдущая'):'')+
      (data.more?pager(data.offset+data.limit,'Следующая'):'')+'</div>' : '';
    const header = c.head('',queue.label,'Решения о пропусках по уважительной причине.');
    return header+'<section class="card card-pad academic-panel" aria-label="Очередь справок">'+
      (data.availability_message?'<p class="academic-availability">'+esc(data.availability_message)+'</p>':'')+
      '<nav class="academic-queue-filters" aria-label="Статус справки">'+filters+'</nav>'+
      (data.items.length?'<p class="academic-scroll-hint">Прокрутите таблицу, чтобы увидеть остальные столбцы.</p>'+
        '<div class="academic-scroll" tabindex="0" role="region" aria-label="Прокрутка очереди справок">'+
        '<table class="academic-table academic-queue-table" aria-label="Справки о пропусках"><thead><tr>'+
        ['Студент','Пропуски и решения','Отправлена','Документ','Пояснение'].map(label=>'<th scope="col">'+label+'</th>').join('')+
        '</tr></thead><tbody>'+queueRows(data.items)+'</tbody></table></div>':
        '<p class="academic-result-count">Справок по выбранным условиям нет.</p>')+navigation+'</section>';
  }
  function openReview(item){
    const entries = item.entries.filter(row=>row.can_review);
    if(!entries.length)return;
    const ui = window.ATLASOperations.ui;
    const fields = (item.file_available?downloadButton(item.id):'')+paragraph(item.note)+
      checklist('Рассматриваемые пропуски',entries,'entries',()=>true,occurrenceLabel)+
      ui.select('status','Решение',[['','Выберите решение'],['accepted','Принять'],['rejected','Отклонить']],'','required')+
      ui.area('reason','Причина отклонения (необязательно)','',500);
    ui.modal('Рассмотреть справку',item.student,fields,(values,data)=>{
      const selected = data.getAll('entries').map(Number);
      if(!selected.length)throw new Error('Выберите пропуски для рассмотрения.');
      return c.api('teaching/absence-certificates/'+Number(item.id)+'/decision',{
        method:'POST',body:JSON.stringify({entries:selected,status:values.status,reason:values.reason}),
      });
    },()=>c.route(queue.id,{replace:true,context:{id:item.id}}),'Сохранить решение');
    const form = c.$('.modal [data-op-form]');
    const toggleReason = ()=>{
      const rejected = form.elements.status.value==='rejected';
      form.elements.reason.disabled=!rejected;
      form.elements.reason.closest('.field').hidden=!rejected;
    };
    form.elements.status.addEventListener('change',toggleReason);
    toggleReason();
  }
  async function download(button){
    if(button.disabled)return;
    button.disabled=true;
    button.setAttribute('aria-busy','true');
    try{
      const id=Number(button.dataset.absenceDownload);
      c.saveDownload(await c.api('absence-certificates/'+id+'/download',{method:'POST',responseType:'blob'}),'spravka');
    }catch(error){if(!error.stale)c.toast(error.message);}
    finally{button.disabled=false;button.removeAttribute('aria-busy');}
  }
  function init(context){
    c=context;
    document.addEventListener('click',event=>{
      const file = event.target.closest('[data-absence-download]');
      if(file){download(file);return;}
      const decision = event.target.closest('[data-absence-review]');
      if(decision&&c.state.page===queue.id){
        const item = c.state.data[queue.id]?.items.find(record=>record.id===Number(decision.dataset.absenceReview));
        if(item)openReview(item);
      }
    });
  }

  window.ATLASAcademics={pages:[queue],has:page=>page===queue.id,validParts:()=>false,
    cleanQuery,load:loadQueue,render:renderQueue,init,reset(){restoreFilters=null;refreshPoints=null;},
    loadStudent,renderStudent,bindStudent,showAward,refreshStudent:()=>refreshPoints?.()};
})();
