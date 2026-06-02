#!/usr/bin/env python3
"""
Markdown → PDF 书籍级排版转换器
- 节标题自动生成 PDF 书签（可点击跳转）
- 仿书籍排版：合适字号/行距/页边距
- 页眉页脚/页码
- 代码块灰底、引用缩进、表格对齐
用法: python to_pdf.py <input.md> [output.pdf]
依赖: pip install fpdf2
"""

import sys, os, re
from pathlib import Path
from fpdf import FPDF

# ── 字体探测 ────────────────────────────────────
FONT_LIST = [
    ('SimSun',  r'C:/Windows/Fonts/simsun.ttc'),
    ('SimHei',  r'C:/Windows/Fonts/simhei.ttf'),
    ('KaiTi',   r'C:/Windows/Fonts/simkai.ttf'),
    ('FangSong',r'C:/Windows/Fonts/simfang.ttf'),
    ('Microsoft YaHei', r'C:/Windows/Fonts/msyh.ttc'),
    ('NSimSun', r'C:/Windows/Fonts/nsimsun.ttf'),
    # Linux / macOS
    ('NotoSansCJK', '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'),
    ('WenQuanYi',   '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc'),
    ('PingFang',    '/System/Library/Fonts/PingFang.ttc'),
]

def detect_font():
    for name, path in FONT_LIST:
        if os.path.exists(path):
            return name, path
    raise FileNotFoundError("未找到中文字体。请安装 SimSun / SimHei / Noto Sans CJK。")


# ── PDF 构建器 ──────────────────────────────────
class BookPDF(FPDF):
    def __init__(self, font_name, font_path):
        super().__init__('P', 'mm', 'A4')
        self.font_name = font_name
        self.font_path = font_path
        self.add_font(font_name, '', font_path)
        # 页边距
        self.set_auto_page_break(True, 22)
        self.set_left_margin(24)
        self.set_right_margin(24)
        self.top_margin = 24
        # 字号体系
        self.sz_body   = 10.5
        self.sz_h1     = 18
        self.sz_h2     = 14
        self.sz_h3     = 12
        self.sz_h4     = 11
        self.sz_small  = 9
        self.sz_footer = 8
        # 行高 (相对于字号)
        self.lh_body   = 6.5
        self.lh_heading = 8
        # 可用宽度
        self._usable_w = 210 - self.l_margin - self.r_margin
        # 书签栈
        self._bookmark_level = 0
        # 章节计数
        self._page_number_start = 1
        self._in_code = False

    # ── 页眉页脚 ──────────────────────────────
    def header(self):
        if self.page_no() == 1:
            return  # 封面页不用页眉
        self.set_font(self.font_name, '', self.sz_footer)
        self.set_text_color(150, 150, 150)
        self.cell(0, 5, self._doc_title if hasattr(self, '_doc_title') else '',
                  align='C', new_x="LMARGIN", new_y="NEXT")
        self.line(self.l_margin, self.get_y(), 210 - self.r_margin, self.get_y())
        self.ln(3)

    def footer(self):
        if self.page_no() == 1:
            return
        self.set_y(-18)
        self.set_font(self.font_name, '', self.sz_footer)
        self.set_text_color(150, 150, 150)
        self.cell(0, 5, str(self.page_no()), align='C')

    # ── 排版基础方法 ──────────────────────────
    def _strip_md(self, text):
        """移除行内 markdown 标记，保留纯文本"""
        t = text
        t = re.sub(r'\*\*(.+?)\*\*', r'\1', t)
        t = re.sub(r'\*(.+?)\*', r'\1', t)
        t = re.sub(r'`(.+?)`', r'\1', t)
        t = re.sub(r'~~(.+?)~~', r'\1', t)
        # 链接: [text](url)
        t = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', t)
        # 图片: ![alt](url)
        t = re.sub(r'!\[.+?\]\(.+?\)', '', t)
        return t

    def _write_body(self, text, indent=0):
        """正文段落"""
        self.set_font(self.font_name, '', self.sz_body)
        self.set_text_color(30, 30, 30)
        x0 = self.l_margin + indent
        self.set_x(x0)
        self.multi_cell(self._usable_w - indent, self.lh_body,
                        self._strip_md(text), align='L')
        self.ln(1)

    def _write_heading(self, text, level, bookmark_title=None):
        """标题 + 自动创建 PDF 书签"""
        sizes = {1: self.sz_h1, 2: self.sz_h2, 3: self.sz_h3, 4: self.sz_h4}
        sz = sizes.get(level, self.sz_h3)
        clean = self._strip_md(text)

        # PDF 书签
        bm = bookmark_title or clean
        self._add_bookmark(bm, level)

        # 段前距
        if level <= 2:
            self.ln(4)
        else:
            self.ln(2)

        self.set_font(self.font_name, '', sz)
        self.set_text_color(20, 20, 20)
        self.set_x(self.l_margin)

        # h1 居中，其他左对齐
        align = 'C' if level == 1 else 'L'
        self.multi_cell(self._usable_w, self.lh_heading, clean, align=align)

        # h1/h2 下划线
        if level <= 2:
            y = self.get_y() + 1
            self.set_draw_color(180, 180, 180)
            w = self._usable_w if level == 1 else self._usable_w * 0.6
            x = self.l_margin if level == 1 else self.l_margin
            self.line(x, y, x + w, y)
        self.ln(3 if level <= 2 else 1.5)

    def _add_bookmark(self, title, level):
        """添加 PDF 书签(大纲)，支持层级"""
        if level <= 2:
            self._bookmark_level = level

        # fpdf2 用 start_section 创建书签
        self.start_section(title, level=level - 1)

    def _write_quote(self, text):
        """引用块 — 左侧竖线 + 缩进 + 灰色"""
        self.set_font(self.font_name, '', self.sz_body - 0.5)
        self.set_text_color(100, 100, 100)
        x0 = self.l_margin + 8
        # 左侧竖线
        self.set_draw_color(180, 180, 180)
        y1 = self.get_y()
        self.set_x(x0 - 4)
        self.multi_cell(self._usable_w - 8, self.lh_body,
                        self._strip_md(text), align='L')
        y2 = self.get_y()
        self.set_draw_color(180, 180, 180)
        self.line(self.l_margin + 2, y1, self.l_margin + 2, y2)
        self.set_text_color(30, 30, 30)
        self.ln(1)

    def _write_code_block(self, lines):
        """代码块 — 灰底 + 等宽字体"""
        self.ln(2)
        self.set_fill_color(245, 245, 247)
        self.set_draw_color(220, 220, 225)

        # 计算代码块高度
        code_h = len(lines) * 4.5 + 6
        y_start = self.get_y()

        # 检查是否需要换页
        if y_start + code_h > 297 - 22:
            self.add_page()
            y_start = self.get_y()

        # 背景矩形
        self.rect(self.l_margin, y_start, self._usable_w, code_h, 'FD')

        self.set_font('Courier', '', 8.5)
        self.set_text_color(50, 50, 60)
        for i, line in enumerate(lines):
            self.set_xy(self.l_margin + 4, y_start + 3 + i * 4.5)
            self.cell(self._usable_w - 8, 4.5, line[:110])
        self.set_y(y_start + code_h + 2)

    def _write_list_item(self, text, ordered=False, index=0):
        """列表项"""
        self.set_font(self.font_name, '', self.sz_body)
        self.set_text_color(30, 30, 30)
        prefix = f'{index}.' if ordered else '•'
        x0 = self.l_margin + 4
        self.set_x(x0)
        self.cell(8, self.lh_body, prefix)
        self.multi_cell(self._usable_w - 12, self.lh_body,
                        self._strip_md(text), align='L')

    def _write_table(self, rows):
        """简易表格渲染"""
        if len(rows) < 2:
            return
        self.ln(2)
        cols = len(rows[0])
        col_w = self._usable_w / cols
        self.set_font(self.font_name, '', self.sz_body - 0.5)

        for ri, row in enumerate(rows):
            if self.get_y() > 260:
                self.add_page()

            # 表头灰底
            if ri == 0:
                self.set_fill_color(240, 240, 245)
            else:
                self.set_fill_color(255, 255, 255)

            self.set_x(self.l_margin)
            for ci, cell in enumerate(row):
                self.cell(col_w, 6, self._strip_md(cell)[:50],
                          border=1, fill=True)
            self.ln()

        # 表后分隔
        self.set_draw_color(200, 200, 200)
        self.ln(3)

    def _write_hr(self):
        """水平分割线"""
        self.ln(3)
        y = self.get_y()
        self.set_draw_color(200, 200, 200)
        self.set_dash_pattern(1, 2)
        self.line(self.l_margin + 20, y, 210 - self.r_margin - 20, y)
        self.set_dash_pattern(0, 0)  # reset to solid
        self.ln(3)

    def _write_blockquote_note(self, text):
        """译者注/脚注 — 小字灰色"""
        self.ln(1)
        self.set_font(self.font_name, '', self.sz_small)
        self.set_text_color(120, 120, 120)
        self.set_x(self.l_margin + 4)
        self.multi_cell(self._usable_w - 4, 4.5,
                        self._strip_md(text), align='L')
        self.set_text_color(30, 30, 30)
        self.ln(1)


# ── 主转换函数 ─────────────────────────────────
def convert_md_to_pdf(md_path, output_pdf, doc_title=None):
    font_name, font_path = detect_font()
    pdf = BookPDF(font_name, font_path)

    with open(md_path, 'r', encoding='utf-8') as f:
        raw = f.read()

    # 分离 YAML frontmatter
    body = raw
    frontmatter = {}
    if raw.startswith('---'):
        parts = raw.split('---', 2)
        if len(parts) >= 3:
            body = parts[2]
            for line in parts[1].strip().split('\n'):
                if ':' in line:
                    k, v = line.split(':', 1)
                    frontmatter[k.strip()] = v.strip()

    pdf._doc_title = doc_title or frontmatter.get('title', '')
    lines = body.split('\n')

    pdf.add_page()
    in_code = False
    code_buf = []
    table_rows = []

    for line in lines:
        stripped = line.rstrip()
        leading = len(line) - len(line.lstrip())

        # ── 代码块 ──
        if stripped.startswith('```'):
            if in_code:
                if code_buf:
                    pdf._write_code_block(code_buf)
                code_buf = []
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_buf.append(stripped)
            continue

        # ── 空白行: 结束表格收集 ──
        if not stripped:
            if table_rows:
                pdf._write_table(table_rows)
                table_rows = []
            pdf.ln(1.5)
            continue

        # ── 表格行 (管道符) ──
        if '|' in stripped and not stripped.startswith('>'):
            cells = [c.strip() for c in stripped.split('|')]
            cells = [c for c in cells if c]  # 去掉首尾空
            # 检测分隔行
            if all(re.match(r'^[-:]+$', c.replace(' ', '')) for c in cells):
                continue
            if cells:
                table_rows.append(cells)
            continue

        # 如果之前有表格缓冲，先输出
        if table_rows:
            pdf._write_table(table_rows)
            table_rows = []

        # ── 标题 ──
        m = re.match(r'^(#{1,4})\s+(.+)$', stripped)
        if m:
            level = len(m.group(1))
            title = m.group(2)
            if level <= 3:
                pdf._write_heading(title, level)
            else:
                pdf._write_heading(title, 4)
            continue

        # ── 水平线 ──
        if re.match(r'^[-*_]{3,}$', stripped):
            pdf._write_hr()
            continue

        # ── 引用 ──
        if stripped.startswith('> '):
            quoted = stripped[2:]
            # 处理连续 >
            while quoted.startswith('> '):
                quoted = quoted[2:]
            pdf._write_quote(quoted)
            continue

        # ── 无序列表 ──
        m = re.match(r'^(\s*)[-*+]\s+(.+)$', stripped)
        if m:
            indent = len(m.group(1)) * 2
            pdf._write_list_item(m.group(2), ordered=False)
            continue

        # ── 有序列表 ──
        m = re.match(r'^(\s*)\d+[.)]\s+(.+)$', stripped)
        if m:
            pdf._write_list_item(m.group(2), ordered=True)
            continue

        # ── 译者注/脚注引用 ──
        if re.match(r'^>\s*\[', stripped) or re.match(r'^>\s*\*', stripped):
            pdf._write_blockquote_note(stripped.lstrip('> '))
            continue

        # ── 普通段落 ──
        pdf._write_body(stripped)

    # 残留表格
    if table_rows:
        pdf._write_table(table_rows)

    # ── 输出 ──
    pdf.output(output_pdf)
    return output_pdf


# ── CLI ────────────────────────────────────────
if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"用法: python {os.path.basename(__file__)} <input.md> [output.pdf]")
        sys.exit(1)

    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else Path(src).with_suffix('.pdf')
    if not os.path.exists(src):
        print(f"错误: 文件不存在: {src}")
        sys.exit(1)

    try:
        result = convert_md_to_pdf(src, str(dst))
        pages = BookPDF(*detect_font()).pages_count if False else "?"
        print(f"PDF 已生成: {result}")
    except Exception as e:
        print(f"PDF 生成失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
