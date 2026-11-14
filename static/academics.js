(() => {
  'use strict';
  let c;
  const columns = [
    ['subject', 'Дисциплина'], ['earned_points', 'Набрано'], ['teacher', 'Преподаватель'], ['semesters', 'Семестр'],
    ['class_count', 'Занятий'], ['visited', 'Посещено'], ['missed', 'Пропущено'],
    ['attendance_percent', 'Посещаемость'], ['max_points', 'Максимум'],
    ['result', 'Результат'], ['assessment', 'Аттестация'],
  ];
  const workStatuses = {not_started:'Не начато', in_progress:'В работе', draft:'В работе', submitted:'Отправлено',
    in_review:'На проверке', revision_required:'Требуется доработка', withdrawn:'Отозвано',
    resubmitted:'Повторно отправлено', accepted:'Принято', completed:'Завершено'};
  const awardLabels = {opening:'Баланс при переносе', teacher:'Начисление преподавателем', assignment:'Проверенная работа'};
  const collator = new Intl.Collator('ru', {numeric:true, sensitivity:'base'});
  const cellValue = (row, key) => key==='assessment'?row.assessment.label:key==='semesters'?row.semesters.join(', '):row[key];
  function showCell(row,key){
    const value=cellValue(row,key);
    if(value==null||value==='')return '—';
    return c.esc(key==='attendance_percent'?value+'%':value);
  }
  const sentence = value => value ? `<p class="user-text">${c.esc(value)}</p>` : '';
  const assignmentLink = item => `<a href="/app/assignments?id=${Number(item.id)}" data-route="assignments" data-record-id="${Number(item.id)}">${c.esc(item.title)}</a>`;
  const awarded = points => points > 0 ? `+${Number(points)}` : '—';

  function showWork(item){
    return `<li><details class="academic-work"><summary>${c.esc(item.title)} <span>${c.esc(workStatuses[item.status]||item.status||'Не начато')}</span></summary>
      <div>${item.due_at?`<p>Срок сдачи · ${c.dateFmt(item.due_at.slice(0,10))}</p>`:''}
      ${item.score!=null?`<p>Баллы за работу · <b>${Number(item.score)}</b>${item.max_points!=null?' из '+Number(item.max_points):''}</p>`:''}
      ${sentence(item.feedback)}${assignmentLink(item)}</div></details></li>`;
  }
  function showClass(item){
    return `<li><details class="academic-session"${item.class_id?` data-class-id="${Number(item.class_id)}"`:''}><summary>${c.dateFmt(item.day)}${item.kind?' · '+c.esc(item.kind):''} <span>${c.esc(item.status_label)}</span></summary>
      <div>${item.topic?`<p>Тема · ${c.esc(item.topic)}</p>`:''}${sentence(item.note)}
      <p>Баллы за занятие · <b>${awarded(item.points)}</b></p>
      ${item.work?.length?`<ul>${item.work.map(work=>`<li>${assignmentLink(work)}</li>`).join('')}</ul>`:''}</div></details></li>`;
  }
  function showAward(item){
    return `<li><b>${awarded(item.points)}</b> · ${c.esc(awardLabels[item.source_kind]||'Начисление')}
      ${item.created_at?`<time datetime="${c.esc(item.created_at)}">${c.stamp(item.created_at)} МСК</time>`:''}${sentence(item.reason)}</li>`;
  }
  function subsection(title, items, render, cls, empty){
    return `<section class="${cls}"><h3>${title}</h3>${items.length?`<ul>${items.map(render).join('')}</ul>`:`<p>${empty}</p>`}</section>`;
  }
  function details(row){
    return subsection('Занятия',row.classes,showClass,'academic-classes','Записей о занятиях пока нет.')+
      subsection('Работы и проверка',row.work,showWork,'academic-works','Заданий пока нет.')+
      subsection('История баллов',row.awards,showAward,'academic-awards','Начислений пока нет.');
  }
  function tableRows(rows){
    return rows.map((row, i) => `<tr ${row.id?`data-record-id="${Number(row.id)}"`:''}>
      <th scope="row"><button class="mini-link academic-toggle" type="button" data-academic-toggle="${i}" aria-expanded="false" aria-controls="academic-details-${i}">${c.esc(row.subject)} ${c.icon('right')}</button></th>
      ${columns.slice(1).map(([key])=>`<td>${key==='assessment'?`<span class="campus-pill ${c.esc(row.assessment.tone)}">${c.esc(row.assessment.label)}</span>`:
        showCell(row,key)}</td>`).join('')}
      </tr><tr id="academic-details-${i}" hidden><td colspan="${columns.length}"><div class="academic-details">${details(row)}</div></td></tr>`).join('');
  }
  function render(data){
    const items = data.items;
    const subjects = items.map(row=>row.subject);
    const semesters = [...new Set(items.flatMap(row=>row.semesters))].sort().reverse();
    const options = values => values.map(value=>`<option value="${c.esc(value)}">${c.esc(value)}</option>`).join('');
    return c.head('','Успеваемость и посещаемость','Посещения, результаты работ и история начислений по дисциплинам.',
      `<a class="outline-button" data-route="exams" href="/app/exams">Сессия и зачёты ${c.icon('right')}</a>`)+
      (items.length?`<section class="card card-pad academic-progress" aria-label="Результаты по дисциплинам">
        <div class="academic-filters">
          <label class="search-field">${c.icon('search')}<input type="search" id="academic-search" maxlength="130" aria-label="Поиск по дисциплинам и преподавателям" placeholder="Поиск"></label>
          <label>Дисциплина<select id="academic-discipline"><option value="">Все дисциплины</option>${options(subjects)}</select></label>
          <label>Семестр<select id="academic-semester"><option value="">Все семестры</option>${options(semesters)}<option value="unknown">Не указан</option></select></label>
        </div>
        <p class="academic-result-count" id="academic-count" role="status">Дисциплин: ${items.length}</p>
        <div class="grade-table-wrap academic-scroll" tabindex="0" role="region" aria-label="Таблица академических результатов">
          <table class="academic-table"><caption class="sr-only">Результаты по дисциплинам. Нажмите название дисциплины для просмотра деталей.</caption><thead><tr>
            ${columns.map(([id,label],i)=>`<th scope="col" aria-sort="${i===0?'ascending':'none'}"><button type="button" data-academic-sort="${id}">${label} <span aria-hidden="true">${i===0?'↑':'↕'}</span></button></th>`).join('')}
          </tr></thead><tbody id="academic-rows">${tableRows(items)}</tbody></table>
        </div>
        <p class="academic-footnote">При необходимости прокрутите таблицу вправо. Опоздания считаются посещениями. Уважительные пропуски исключаются из расчёта процента.</p>
        <p class="academic-footnote" id="academic-term-hint" hidden>Фильтр семестра применяется к занятиям и работам. Баллы и результаты аттестации приведены за всё время.</p>
      </section>`:`<section class="card card-pad">${c.empty('graduation','Учебных результатов пока нет','Здесь появятся занятия, баллы и результаты аттестации.')}</section>`);
  }
  function bind(root, data, context){
    const panel = root.querySelector('.academic-progress');
    if(!panel)return;
    const [search,subject,semester] = panel.querySelectorAll('input,select');
    const tbody = panel.querySelector('#academic-rows');
    const open = new Set();
    let sort = 'subject', ascending = true;
    const picked = data.items.find(row=>row.id&&row.id===Number(context.id));
    const wanted = context.subject || picked?.subject;
    if(wanted && data.items.some(row=>row.subject===wanted)){subject.value=wanted;open.add(wanted);}
    let shown = data.items;
    const toggle = (button, isOpen) => {
      button.setAttribute('aria-expanded',String(isOpen));
      c.$('#'+button.getAttribute('aria-controls')).hidden=!isOpen;
    };
    function update(){
      const q=search.value.trim().toLocaleLowerCase('ru');
      shown=data.items.filter(row=>(!subject.value||row.subject===subject.value)&&
        (!semester.value||(semester.value==='unknown'?!row.semesters.length:row.semesters.includes(semester.value)))&&
        (!q||`${row.subject} ${row.teacher}`.toLocaleLowerCase('ru').includes(q)));
      const filteredTerm=Boolean(semester.value&&semester.value!=='unknown');
      if(filteredTerm)shown=shown.map(row=>({...row,...row.attendance_by_semester[semester.value],semesters:[semester.value],
        classes:row.classes.filter(item=>item.semester===semester.value),work:row.work.filter(item=>item.semester===semester.value)}));
      panel.querySelector('#academic-term-hint').hidden=!filteredTerm;
      shown.sort((a,b)=>{
        const x=cellValue(a,sort),y=cellValue(b,sort);
        if(x==null||y==null)return Number(x==null)-Number(y==null);
        return (typeof x==='number'&&typeof y==='number'?x-y:collator.compare(String(x),String(y)))*(ascending?1:-1);
      });
      tbody.innerHTML=tableRows(shown)||`<tr><td colspan="${columns.length}">Дисциплин по выбранным условиям нет.</td></tr>`;
      tbody.querySelectorAll('[data-academic-toggle]').forEach(button=>toggle(button,open.has(shown[Number(button.dataset.academicToggle)].subject)));
      panel.querySelector('#academic-count').textContent='Дисциплин: '+shown.length;
      panel.querySelectorAll('[data-academic-sort]').forEach(button=>{
        const selected=button.dataset.academicSort===sort;
        button.closest('th').setAttribute('aria-sort',selected?(ascending?'ascending':'descending'):'none');
        button.querySelector('span').textContent=selected?(ascending?'↑':'↓'):'↕';
      });
    }
    search.addEventListener('input',update);
    subject.addEventListener('change',update);
    semester.addEventListener('change',update);
    panel.addEventListener('click',event=>{
      const heading=event.target.closest('[data-academic-sort]');
      if(heading){const key=heading.dataset.academicSort;ascending=key!==sort||!ascending;sort=key;update();return;}
      const button=event.target.closest('[data-academic-toggle]');
      if(!button)return;
      const row=shown[Number(button.dataset.academicToggle)];
      const isOpen=!open.delete(row.subject);
      if(isOpen)open.add(row.subject);
      toggle(button,isOpen);
    });
    if(wanted)update();
  }

  window.ATLASAcademics={init(context){c=context;},render,bind,showAward};
})();
