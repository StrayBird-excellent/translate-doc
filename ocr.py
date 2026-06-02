#!/usr/bin/env python3
"""
扫描版 PDF OCR 提取器 — 将图片型 PDF 转为可读文本
用法: python ocr.py <input.pdf> -o [output.txt]

后端:
  tesseract  — 本地 Tesseract OCR (默认，需安装 Tesseract + chi_sim)
  dashscope  — 阿里云 DashScope qwen-vl-max API (需 API Key)

依赖: pip install pymupdf pytesseract pillow opencv-python requests
      系统需安装 Tesseract-OCR + 中文语言包 (chi_sim) [仅 tesseract 后端]
"""

import sys
import os
import re
import io
import base64
import time
from pathlib import Path
from multiprocessing import Pool, cpu_count
from concurrent.futures import ThreadPoolExecutor, as_completed
import fitz  # PyMuPDF
from PIL import Image
import pytesseract
import numpy as np

# OpenCV 是可选依赖，用于预处理增强
try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


# ═══════════════════════════════════════════════════════════
# 图像预处理
# ═══════════════════════════════════════════════════════════

def preprocess_image(img_bytes):
    """
    图像预处理：CLAHE 对比度增强 + 降噪
    返回预处理后的 PIL Image
    """
    img = Image.open(io.BytesIO(img_bytes))
    if not HAS_CV2:
        return img

    arr = np.array(img.convert('RGB'))
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)

    denoised = cv2.fastNlMeansDenoising(enhanced, h=10)

    return Image.fromarray(denoised)


# ═══════════════════════════════════════════════════════════
# Tesseract 后端
# ═══════════════════════════════════════════════════════════

def ocr_page_tesseract(args):
    """对单页执行 Tesseract OCR，返回 (页码, 文本)"""
    page_num, pixmap_bytes, lang = args
    try:
        img = preprocess_image(pixmap_bytes)
        text = pytesseract.image_to_string(img, lang=lang, config='--psm 4')
        text = re.sub(r'[ \t]{3,}', '   ', text)
        text = re.sub(r'\n{4,}', '\n\n\n', text)
        return page_num, text.strip()
    except Exception as e:
        return page_num, f"[OCR 错误: {e}]"


def ocr_pdf_tesseract(pdf_path, output_path=None, lang='chi_sim', workers=None, dpi=300):
    """使用 Tesseract 对扫描版 PDF 执行 OCR"""
    if workers is None:
        workers = min(cpu_count(), 6)

    doc = fitz.open(pdf_path)
    total = len(doc)
    print(f"后端: Tesseract | PDF: {total} 页 | DPI: {dpi} | 并行: {workers} 核 | 语言: {lang}")
    if HAS_CV2:
        print("预处理: CLAHE + 降噪 (OpenCV)")

    print("渲染页面为图片...")
    page_images = []
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)

    for i in range(total):
        pix = doc[i].get_pixmap(matrix=mat)
        page_images.append((i + 1, pix.tobytes("png"), lang))

    doc.close()

    print(f"OCR 识别中 ({workers} 进程)...")
    results = []
    chunk_size = max(1, total // (workers * 4))

    with Pool(workers) as pool:
        for i, result in enumerate(pool.imap_unordered(ocr_page_tesseract, page_images, chunksize=chunk_size)):
            results.append(result)
            if (i + 1) % 30 == 0 or (i + 1) == total:
                print(f"  进度: {i+1}/{total} 页")

    results.sort(key=lambda x: x[0])
    full_text = '\n\n'.join(text for _, text in results if text)

    if output_path:
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(full_text)
        print(f"文本已保存: {output_path}")
        return output_path

    return full_text


# ═══════════════════════════════════════════════════════════
# DashScope API 后端
# ═══════════════════════════════════════════════════════════

DASHSCOPE_API_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'
DASHSCOPE_MODEL = 'qwen-vl-max'

# 可通过环境变量配置
DASHSCOPE_API_KEY = os.environ.get('DASHSCOPE_API_KEY', '')


def ocr_page_dashscope(page_num, img_jpeg_b64, api_key, api_url, model):
    """调用 DashScope qwen-vl-max 识别单页"""
    payload = {
        'model': model,
        'messages': [{
            'role': 'user',
            'content': [
                {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{img_jpeg_b64}'}},
                {'type': 'text', 'text': '请逐行识别并输出图片中的所有文字，严格保持原文格式和排版，不要添加任何解释、不要总结。如果页面为空白或没有文字，请回复"（空）"。'}
            ]
        }],
        'max_tokens': 4096
    }

    for attempt in range(3):
        try:
            import requests
            resp = requests.post(api_url,
                headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                json=payload, timeout=120)
            if resp.status_code == 200:
                data = resp.json()
                text = data['choices'][0]['message']['content']
                return page_num, text
            elif resp.status_code == 429:
                wait = 5 * (attempt + 1)
                print(f'  第 {page_num} 页: 限流，等待 {wait}s...')
                time.sleep(wait)
            else:
                print(f'  第 {page_num} 页: HTTP {resp.status_code}: {resp.text[:200]}')
                time.sleep(2)
        except Exception as e:
            print(f'  第 {page_num} 页: {e}')
            time.sleep(2)
    return page_num, f'[OCR失败]'


def ocr_pdf_dashscope(pdf_path, output_path=None, api_key=None, api_url=None,
                      model=None, workers=5, dpi=150, jpeg_quality=80):
    """使用 DashScope qwen-vl-max 对扫描版 PDF 执行 OCR"""
    api_key = api_key or DASHSCOPE_API_KEY
    if not api_key:
        raise ValueError(
            "DashScope API Key 未设置。请通过以下方式之一提供:\n"
            "  1. 命令行: --api-key sk-xxxx\n"
            "  2. 环境变量: export DASHSCOPE_API_KEY=sk-xxxx\n"
            "  3. 代码中设置: DASHSCOPE_API_KEY = 'sk-xxxx'"
        )

    api_url = api_url or DASHSCOPE_API_URL
    model = model or DASHSCOPE_MODEL

    doc = fitz.open(pdf_path)
    total = len(doc)
    print(f"后端: DashScope ({model}) | PDF: {total} 页 | DPI: {dpi} | 并发: {workers}")
    print("渲染页面 + OCR 中...")

    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    results = {}
    t0 = time.time()
    batch_size = workers * 3

    if output_path:
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

    if output_path:
        out_f = open(output_path, 'w', encoding='utf-8')
    else:
        out_f = None

    try:
        for batch_start in range(0, total, batch_size):
            batch_end = min(batch_start + batch_size, total)
            batch = []
            for i in range(batch_start, batch_end):
                pix = doc[i].get_pixmap(matrix=mat)
                img = Image.open(io.BytesIO(pix.tobytes('png')))
                buf = io.BytesIO()
                img.convert('RGB').save(buf, format='JPEG', quality=jpeg_quality)
                b64 = base64.b64encode(buf.getvalue()).decode()
                batch.append((i + 1, b64))

            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(ocr_page_dashscope, pn, b64, api_key, api_url, model): pn for pn, b64 in batch}
                for fut in as_completed(futures):
                    pn, text = fut.result()
                    results[pn] = text

            if out_f:
                for pn in range(batch_start + 1, batch_end + 1):
                    if pn in results:
                        out_f.write(f'\n{"="*60}\n第 {pn} 页\n{"="*60}\n')
                        out_f.write(results[pn] + '\n')
                out_f.flush()
            results.clear()

            elapsed = time.time() - t0
            speed = batch_end / elapsed if elapsed > 0 else 0
            eta = (total - batch_end) / speed if speed > 0 else 0
            print(f'  {batch_end}/{total} ({elapsed:.0f}s, ~{eta:.0f}s left)')
    finally:
        if out_f:
            out_f.close()

    doc.close()

    if output_path:
        elapsed = time.time() - t0
        print(f"完成! {total} 页 / {elapsed:.0f}s")
        print(f"输出: {output_path}")
        return output_path

    # 如果没有输出文件，收集所有结果
    return ""


# ═══════════════════════════════════════════════════════════
# 统一入口
# ═══════════════════════════════════════════════════════════

def ocr_pdf(pdf_path, output_path=None, backend='tesseract', **kwargs):
    """
    对扫描版 PDF 执行 OCR。

    参数:
      pdf_path   : PDF 文件路径
      output_path: 输出文本文件路径 (可选)
      backend    : 'tesseract' 或 'dashscope'

    Tesseract 参数:
      lang       : OCR 语言 (默认 chi_sim)
      workers    : 并行进程数
      dpi        : 渲染分辨率 (默认 300)

    DashScope 参数:
      api_key    : DashScope API Key
      api_url    : API 端点
      model      : 模型名称 (默认 qwen-vl-max)
      workers    : 并发请求数 (默认 5)
      dpi        : 渲染分辨率 (默认 150)
      jpeg_quality: JPEG 压缩质量 (默认 80)
    """
    if backend == 'dashscope':
        return ocr_pdf_dashscope(
            pdf_path, output_path,
            api_key=kwargs.get('api_key'),
            api_url=kwargs.get('api_url'),
            model=kwargs.get('model'),
            workers=kwargs.get('workers', 5),
            dpi=kwargs.get('dpi', 150),
            jpeg_quality=kwargs.get('jpeg_quality', 80)
        )
    else:
        return ocr_pdf_tesseract(
            pdf_path, output_path,
            lang=kwargs.get('lang', 'chi_sim'),
            workers=kwargs.get('workers'),
            dpi=kwargs.get('dpi', 300)
        )


# ── CLI ────────────────────────────────────────
if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='扫描版 PDF OCR 提取器')
    parser.add_argument('input', help='输入 PDF 文件路径')
    parser.add_argument('-o', '--output', default=None, help='输出文本文件路径')
    parser.add_argument('--backend', choices=['tesseract', 'dashscope'], default='tesseract',
                        help='OCR 后端 (默认 tesseract)')

    # Tesseract 参数
    parser.add_argument('-l', '--lang', default='chi_sim', help='OCR 语言 (Tesseract, 默认 chi_sim)')
    parser.add_argument('--no-preprocess', action='store_true', help='禁用图像预处理')

    # DashScope 参数
    parser.add_argument('--api-key', default=None, help='DashScope API Key (或设置环境变量 DASHSCOPE_API_KEY)')
    parser.add_argument('--api-url', default=None, help='DashScope API 端点')
    parser.add_argument('--model', default=None, help='DashScope 模型 (默认 qwen-vl-max)')

    # 通用参数
    parser.add_argument('-w', '--workers', type=int, default=None, help='并行进程/请求数')
    parser.add_argument('-d', '--dpi', type=int, default=None, help='渲染 DPI')
    parser.add_argument('--dry-run', action='store_true', help='仅测试前 3 页')
    parser.add_argument('-q', '--jpeg-quality', type=int, default=80, help='JPEG 质量 (DashScope, 默认 80)')

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"错误: 文件不存在: {args.input}")
        sys.exit(1)

    output = args.output or str(Path(args.input).with_suffix('.txt'))

    if args.no_preprocess:
        global HAS_CV2
        HAS_CV2 = False

    if args.dry_run:
        doc = fitz.open(args.input)
        backend = args.backend
        if backend == 'dashscope':
            api_key = args.api_key or DASHSCOPE_API_KEY
            if not api_key:
                print("错误: DashScope 后端需要 --api-key 或环境变量 DASHSCOPE_API_KEY")
                sys.exit(1)
            import requests
            api_url = args.api_url or DASHSCOPE_API_URL
            model = args.model or DASHSCOPE_MODEL
            dpi = args.dpi or 150
            zoom = dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)
            for i in range(min(3, len(doc))):
                pix = doc[i].get_pixmap(matrix=mat)
                img = Image.open(io.BytesIO(pix.tobytes('png')))
                buf = io.BytesIO()
                img.convert('RGB').save(buf, format='JPEG', quality=args.jpeg_quality)
                b64 = base64.b64encode(buf.getvalue()).decode()
                _, text = ocr_page_dashscope(i + 1, b64, api_key, api_url, model)
                print(f"\n=== 第 {i+1} 页 ===")
                print(text[:800])
        else:
            dpi = args.dpi or 300
            zoom = dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)
            for i in range(min(3, len(doc))):
                pix = doc[i].get_pixmap(matrix=mat)
                text = pytesseract.image_to_string(
                    preprocess_image(pix.tobytes("png")), lang=args.lang, config='--psm 4'
                )
                print(f"\n=== 第 {i+1} 页 ===")
                print(text[:800])
        doc.close()
    else:
        if args.backend == 'dashscope':
            ocr_pdf(
                args.input, output, backend='dashscope',
                api_key=args.api_key,
                api_url=args.api_url,
                model=args.model,
                workers=args.workers or 5,
                dpi=args.dpi or 150,
                jpeg_quality=args.jpeg_quality
            )
        else:
            ocr_pdf(
                args.input, output, backend='tesseract',
                lang=args.lang,
                workers=args.workers,
                dpi=args.dpi or 300
            )
