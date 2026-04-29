# -*- coding: utf-8 -*-
"""HTML strip 工具：移除標籤、解碼 entity、合併空白。

零依賴（stdlib html.parser），用於 knowledge_atoms.content → content_plain。

使用情境：
- Tiptap 編輯器 + tiptap-markdown 在使用 Color/Highlight/Table 時會 fallback HTML，
  例如「最高<font color='red'>機密</font>資料」。
- 直接 ILIKE '%機密%' 找不到（被切斷）→ 故維護一份 strip 版本給搜尋與 embedding 使用。
"""
from html import unescape
from html.parser import HTMLParser
import re


# 應該被視為「區塊」的標籤：strip 後在前後補一個空白，避免內文相黏
# 例如 <li>A</li><li>B</li> → "A B" 而非 "AB"
_BLOCK_TAGS = {
    'p', 'div', 'br', 'hr',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'li', 'ul', 'ol',
    'tr', 'td', 'th', 'thead', 'tbody', 'table',
    'blockquote', 'pre',
    'section', 'article', 'header', 'footer',
}

# 整個 strip 掉、不取內文的標籤
_DROP_TAGS = {'script', 'style', 'noscript', 'iframe'}

_MULTISPACE = re.compile(r'[ \t]+')
_MULTINEWLINE = re.compile(r'\n{3,}')


class _Stripper(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._buf = []
        self._drop_depth = 0  # 在 drop tag 內的深度

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in _DROP_TAGS:
            self._drop_depth += 1
            return
        if tag in _BLOCK_TAGS:
            self._buf.append('\n')

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _DROP_TAGS:
            if self._drop_depth > 0:
                self._drop_depth -= 1
            return
        if tag in _BLOCK_TAGS:
            self._buf.append('\n')

    def handle_startendtag(self, tag, attrs):
        # 自閉合，如 <br/>
        tag = tag.lower()
        if tag in _BLOCK_TAGS:
            self._buf.append('\n')

    def handle_data(self, data):
        if self._drop_depth > 0:
            return
        self._buf.append(data)

    def get_text(self):
        return ''.join(self._buf)


def strip_html(text):
    """從 HTML / Markdown-with-HTML 字串萃取純文字。

    - 標籤移除（含屬性、nested）
    - HTML entity 解碼（&amp; → &）
    - script/style/iframe 內容直接丟棄
    - 區塊標籤前後補換行，避免單字黏連
    - 空白合併（連續空格 / 連續空行）

    輸入: str（可能含 HTML、純 markdown、純文字皆可）
    回傳: str（純文字）

    傳 None / 空字串 → 回傳 ''。
    """
    if not text:
        return ''
    if not isinstance(text, str):
        text = str(text)

    # 即使輸入是純 markdown 不含 HTML，跑一遍也不會破壞內容
    parser = _Stripper()
    try:
        parser.feed(text)
        parser.close()
        out = parser.get_text()
    except Exception:
        # parser 對極端畸形 HTML 容錯：fallback 用 regex 粗暴清標籤
        out = re.sub(r'<[^>]+>', ' ', text)
        out = unescape(out)

    # 合併空白：連續空格 → 一個空格；連續空行（>=3）→ 兩個空行
    out = _MULTISPACE.sub(' ', out)
    out = _MULTINEWLINE.sub('\n\n', out)
    # 每行兩端 trim
    lines = [ln.strip() for ln in out.split('\n')]
    # 刪除前後空行
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return '\n'.join(lines)


if __name__ == '__main__':
    # 簡單煙霧測試
    cases = [
        ('這是最高<font color="red">機密</font>資料',
         '這是最高機密資料'),
        ('<span style="color:blue">最高機</span><span style="color:red">密的</span>資料',
         '最高機密的資料'),
        ('<table><tr><td>A</td><td>B</td></tr></table>',
         'A\n\nB'),  # block tag 前後加換行；A 和 B 不會黏在一起即達到搜尋目的
        ('<p>第一段</p><p>第二段</p>',
         '第一段\n\n第二段'),
        ('<script>alert(1)</script>內容',
         '內容'),
        ('純文字無標籤', '純文字無標籤'),
        ('', ''),
        (None, ''),
        ('&lt;tag&gt; &amp; entity', '<tag> & entity'),
    ]
    pass_n = fail_n = 0
    for src, want in cases:
        got = strip_html(src)
        ok = got == want
        marker = 'OK ' if ok else 'FAIL'
        print(f'{marker}  {src!r:60} -> {got!r}')
        if not ok:
            print(f'      expected: {want!r}')
            fail_n += 1
        else:
            pass_n += 1
    print(f'\n{pass_n} passed, {fail_n} failed')
