#!/usr/bin/env python3
"""
文档内容提取器 — 从 EPUB/PDF/DOCX/TXT/HTML 中提取纯文本
用法: python extract.py <input.file> [output.txt]
"""

import sys
import os
import re
import zipfile
from pathlib import Path


def extract_epub(path):
    """从 EPUB 提取文本（EPUB = ZIP + XHTML）"""
    texts = []
    with zipfile.ZipFile(path, 'r') as z:
        for name in sorted(z.namelist()):
            if name.endswith(('.html', '.xhtml', '.htm')):
                content = z.read(name).decode('utf-8', errors='replace')
                # 移除标签
                text = re.sub(r'<br\s*/?>', '\n', content)
                text = re.sub(r'<p[^>]*>', '\n\n', text)
                text = re.sub(r'<title[^>]*>.*?</title>', '', text, flags=re.DOTALL)
                text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
                text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
                text = re.sub(r'<[^>]+>', ' ', text)
                text = re.sub(r'&nbsp;', ' ', text)
                text = re.sub(r'&amp;', '&', text)
                text = re.sub(r'&lt;', '<', text)
                text = re.sub(r'&gt;', '>', text)
                text = re.sub(r'&quot;', '"', text)
                text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
                text = re.sub(r' +', ' ', text)
                text = text.strip()
                if len(text) > 50:  # 跳过纯导航/标题页
                    texts.append(text)
    return '\n\n'.join(texts)


def extract_txt(path):
    """纯文本文件直接读取"""
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        return f.read()


def extract_html(path):
    """从 HTML 提取文本"""
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    text = re.sub(r'<br\s*/?>', '\n', content)
    text = re.sub(r'<p[^>]*>', '\n\n', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
    text = re.sub(r' +', ' ', text)
    return text.strip()


EXTRACTORS = {
    '.epub': extract_epub,
    '.txt':  extract_txt,
    '.text': extract_txt,
    '.html': extract_html,
    '.htm':  extract_html,
    '.xhtml': extract_html,
    '.md': extract_txt,
    '.markdown': extract_txt,
}


def extract(input_path, output_path=None):
    """主提取方法，自动识别格式"""
    ext = Path(input_path).suffix.lower()
    if ext not in EXTRACTORS:
        supported = ', '.join(EXTRACTORS.keys())
        raise ValueError(f"不支持的格式: {ext}，支持: {supported}")

    text = EXTRACTORS[ext](input_path)

    if output_path:
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(text)
        return output_path

    return text


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"用法: python {os.path.basename(__file__)} <input.file> [output.txt]")
        print(f"支持格式: EPUB, HTML, TXT, Markdown")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None

    if not os.path.exists(input_path):
        print(f"错误: 文件不存在: {input_path}")
        sys.exit(1)

    try:
        result = extract(input_path, output_path)
        if output_path:
            print(f"文本已提取至: {result}")
        else:
            print(result[:500])
            if len(result) > 500:
                print(f"\n... (共 {len(result)} 字符)")
    except Exception as e:
        print(f"提取失败: {e}")
        sys.exit(1)
