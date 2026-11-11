"""Bounded CSV/OOXML data sheets. Spreadsheet expressions are never evaluated."""
import csv
from io import BytesIO, StringIO
import posixpath
import re
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile
from zlib import error as CompressionError

MAX_UPLOAD = 22000
MAX_ROWS = 200
MAX_COLUMNS = 32
NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PACKAGE_REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
CONTENT = 'http://schemas.openxmlformats.org/package/2006/content-types'
XLSX_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def literal(value, *, csv_export=False):
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'true' if value else 'false'
    text = str(value)
    if csv_export and isinstance(value, str) and (text.lstrip().startswith(('=', '+', '-', '@'))
                                                   or text.startswith(('\t','\r','\n'))):
        return "'" + text
    return text


def table_bytes(format, columns, rows):
    if format == 'csv':
        output = StringIO(newline='')
        writer = csv.writer(output, delimiter=';')
        writer.writerow(columns)
        writer.writerows([literal(row.get(column), csv_export=True) for column in columns] for row in rows)
        return output.getvalue().encode('utf-8-sig'), 'text/csv'
    book = BytesIO()
    sheet = ET.Element('worksheet', {'xmlns': NS})
    data = ET.SubElement(sheet, 'sheetData')
    for index, values in enumerate([columns, *([row.get(column) for column in columns] for row in rows)], 1):
        line = ET.SubElement(data, 'row', {'r': str(index)})
        for i, value in enumerate(values):
            if value is None:
                continue
            col = chr(ord('A')+i) if i<26 else 'A'+chr(ord('A')+i-26)
            cell = ET.SubElement(line, 'c', {'r': f'{col}{index}', 't':'inlineStr'})
            entry = ET.SubElement(ET.SubElement(cell,'is'),'t', {'xml:space':'preserve'})
            entry.text = literal(value)
    types = f'''<Types xmlns="{CONTENT}"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="{XLSX_TYPE.replace('.sheet','.sheet.main+xml')}"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>'''
    with ZipFile(book,'w',compression=ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml',types)
        z.writestr('_rels/.rels',f'<Relationships xmlns="{PACKAGE_REL}"><Relationship Id="rId1" Type="{REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml',f'<workbook xmlns="{NS}" xmlns:r="{REL}"><sheets><sheet name="АТЛАС" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels',f'<Relationships xmlns="{PACKAGE_REL}"><Relationship Id="rId1" Type="{REL}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml',ET.tostring(sheet,encoding='utf-8',xml_declaration=True))
    return book.getvalue(), XLSX_TYPE


def read_csv(content):
    try:
        decoded = content.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError('Сохраните CSV в кодировке UTF-8') from None
    sample = decoded.splitlines()
    if not sample:
        return []
    try:
        try:
            delimiter = csv.Sniffer().sniff(decoded[:4096], delimiters=',;').delimiter
        except csv.Error:
            delimiter = ';' if sample[0].count(';') > sample[0].count(',') else ','
        reader = csv.reader(StringIO(decoded, newline=''), delimiter=delimiter, strict=True)
        return [(reader.line_num, values) for values in reader if any(values)]
    except csv.Error:
        raise ValueError('Некорректная структура CSV') from None


def xml_member(archive, name):
    source = archive.read(name)
    if re.search(rb'<!\s*(DOCTYPE|ENTITY)', source, re.I) or b'\x00' in source:
        raise ValueError('Допускаются обычные XML-таблицы UTF-8')
    return ET.fromstring(source)


def read_xlsx(content):
    try:
        with ZipFile(BytesIO(content)) as archive:
            files = archive.infolist()
            names = set(archive.namelist())
            if len(files) > 80 or len(names) != len(files) or sum(item.file_size for item in files) > 1200000:
                raise ValueError('Содержимое XLSX слишком велико')
            if any(name.endswith('.bin') or 'externallinks/' in name.lower() or 'embeddings/' in name.lower() for name in names):
                raise ValueError('Удалите активное содержимое и внешние ссылки из книги')
            for name in names:
                if name.endswith('.rels') and any(link.get('TargetMode','').lower() == 'external' for link in xml_member(archive, name)):
                    raise ValueError('Внешние ссылки в книге не поддерживаются')
            workbook = xml_member(archive,'xl/workbook.xml')
            sheets = workbook.findall(f'{{{NS}}}sheets/{{{NS}}}sheet')
            if len(sheets) != 1:
                raise ValueError('Для импорта нужен один лист')
            props = workbook.find(f'{{{NS}}}workbookPr')
            date1904 = props is not None and props.get('date1904') in {'1','true'}
            rel_id = sheets[0].get(f'{{{REL}}}id')
            links = xml_member(archive, 'xl/_rels/workbook.xml.rels')
            target = next((link.get('Target','') for link in links if link.get('Id') == rel_id and
                           link.get('Type') == REL+'/worksheet'), '')
            path = posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join('xl',target))
            if not path.startswith('xl/worksheets/') or path not in names:
                raise ValueError('Лист XLSX не найден')
            strings = []
            if 'xl/sharedStrings.xml' in names:
                strings = [''.join(t.text or '' for t in node.iter(f'{{{NS}}}t'))
                           for node in xml_member(archive, 'xl/sharedStrings.xml')]
            return sheet_rows(xml_member(archive,path), strings), date1904
    except (BadZipFile, ET.ParseError, KeyError, OSError, RuntimeError, IndexError, TypeError, NotImplementedError, CompressionError):
        raise ValueError('Не удалось прочитать XLSX') from None


def sheet_rows(sheet, strings):
    rows = []
    if any(True for _ in sheet.iter(f'{{{NS}}}f')):
        raise ValueError('Замените формулы их значениями')
    for row in sheet.findall(f'{{{NS}}}sheetData/{{{NS}}}row'):
        index = int(row.get('r',0))
        cells = {}
        for cell in row.findall(f'{{{NS}}}c'):
            address = re.fullmatch(r'([A-Z]{1,3})([1-9][0-9]{0,6})',cell.get('r',''))
            if address is None or int(address[2]) != index:
                raise ValueError('Не удалось определить адрес ячейки XLSX')
            col = 0
            for char in address[1]:
                col = col*26+ord(char)-ord('A')+1
            if col>MAX_COLUMNS or col in cells:
                raise ValueError('Слишком много столбцов или повторяется адрес ячейки')
            kind = cell.get('t','n')
            raw = cell.findtext(f'{{{NS}}}v','')
            if kind == 'inlineStr':
                raw = ''.join(t.text or '' for t in cell.iter(f'{{{NS}}}t'))
            elif kind == 's':
                key = int(raw)
                if not 0 <= key < len(strings):
                    raise ValueError('Повреждён словарь строк XLSX')
                raw = strings[key]
            elif kind == 'e':
                raise ValueError(f'Строка {index} содержит ошибку Excel')
            cells[col] = raw
        if any(cells.values()):
            if not 1 <= index <= 1048576 or (rows and index <= rows[-1][0]):
                raise ValueError('Некорректная нумерация строк XLSX')
            rows.append((index,[cells.get(i,'') for i in range(1,max(cells)+1)]))
            if len(rows)>MAX_ROWS+1:
                raise ValueError(f'Допустимо до {MAX_ROWS} строк данных')
    return rows


def read_table(format, data):
    if not data or len(data)>MAX_UPLOAD:
        raise ValueError(f'Выберите файл размером до {MAX_UPLOAD//1000} КБ')
    rows, date1904 = read_xlsx(data) if format=='xlsx' else (read_csv(data),False)
    if len(rows)<2:
        raise ValueError('Добавьте заголовки и хотя бы одну строку данных')
    if len(rows)>MAX_ROWS+1 or any(len(values)>MAX_COLUMNS for _,values in rows):
        raise ValueError(f'Допустимо до {MAX_ROWS} строк и {MAX_COLUMNS} столбцов')
    headers = [value.strip() for value in rows[0][1]]
    if any(not h or len(h)>100 for h in headers) or len(set(h.casefold() for h in headers)) != len(headers):
        raise ValueError('Дайте каждому столбцу неповторяющийся заголовок')
    if any(len(values)>len(headers) or any(len(value)>4000 for value in values) for _,values in rows[1:]):
        raise ValueError('Проверьте длину ячеек и заголовки всех столбцов')
    return headers, [(index,dict(zip(headers,values))) for index,values in rows[1:]], date1904
