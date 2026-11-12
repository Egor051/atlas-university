"""Document types and routing shared by the student and staff workflows."""

APPENDIX_4 = 'military_appendix_4'
APPENDIX_4_NAME = 'Справка об обучении для военного комиссариата (приложение № 4)'
APPENDIX_4_FORM = 'Справка об обучении по образовательной программе среднего профессионального или высшего образования'
APPENDIX_4_BASIS = 'Приложение № 4 к Положению, утверждённому постановлением Правительства РФ от 11.11.2006 № 663'
APPENDIX_4_SOURCE = 'https://www.kontur-extern.ru/info/normativ/document/1/508743-postanovlenie-pravitelstva-rf-ot-11-11-2006-n-663'
STUDY_SOURCE = 'https://misis.ru/students/sto-services/studserv/reference/sp1/'
OFFICE = 'Учебный офис'

CERTIFICATE_CODES = {'study', 'transcript', 'scholarship', 'tax', 'military', APPENDIX_4}
CERTIFICATE_DETAILS = {
    'study': {
        'basis': 'Справка с места учёбы по правилам образовательной организации',
        'source_url': STUDY_SOURCE,
        'required_data': 'Назначение и количество экземпляров. Имя, направление, курс и группу берём из профиля.',
    },
    'transcript': {'required_data': 'Учебный период и формат. Оценки берём из учебной ведомости.',
                   'basis': 'Пример университетской услуги — выписка из учебной карточки',
                   'source_url': 'https://misis.ru/students/sto-services/studserv/reference/sp3/'},
    'scholarship': {'required_data': 'При необходимости укажите период в комментарии.',
                    'basis': 'Пример университетской услуги — справка о выплатах',
                    'source_url': 'https://misis.ru/students/sto-services/studserv/reference/sp11/'},
    'tax': {'required_data': 'В комментарии можно указать период и назначение запроса.'},
    APPENDIX_4: {
        'form': APPENDIX_4_FORM,
        'basis': APPENDIX_4_BASIS,
        'source_url': APPENDIX_4_SOURCE,
        'required_data': 'Выберите военный комиссариат. Учебный офис сверит имя, год рождения, сведения о зачислении, код программы, аккредитацию, курс, форму, срок и дату окончания обучения.',
        'eligibility': 'Для очного обучения по аккредитованным программам СПО, бакалавриата, специалитета или магистратуры. Для аспирантуры, ординатуры и ассистентуры-стажировки предусмотрено приложение № 5.',
    },
}

# Requests can be created on a public demo. Never collect real conscription
# records or permit a free-text destination to enter the generated form.
COMMISSIONER_OPTIONS = {
    'north': 'Военный комиссариат муниципального округа Северный (учебный)',
    'east': 'Военный комиссариат муниципального округа Восточный (учебный)',
}
