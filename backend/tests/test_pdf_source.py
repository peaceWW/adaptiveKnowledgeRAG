from pathlib import Path
from types import SimpleNamespace

import pymupdf as fitz
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api import documents
from app.api.pdf_source import page_text_layer, pdf_manifest, render_pdf_page
from app.storage.db import get_session


def sample_pdf() -> bytes:
    """Two-column source, vector diagram, formula and embedded image for fidelity QA."""
    with fitz.open() as pdf:
        for number in range(1, 4):
            page = pdf.new_page(width=612, height=792)
            page.insert_text((44, 35), 'KNOWLEDGE SYSTEMS / ORIGINAL SOURCE', fontsize=9, color=(.35, .4, .5))
            page.insert_text((554, 35), str(number), fontsize=9)
            page.insert_text((44, 78), 'A Hybrid ADC-Based Receiver', fontsize=23, fontname='tiro')
            page.insert_text((44, 104), 'Source layout verification - two-column technical paper', fontsize=11, fontname='tiro')
            page.insert_text((44, 145), f'{number}. Architecture and equalization', fontsize=14, fontname='tiro')
            paragraph = ('The receiver combines analog equalization with a digital signal path. '
                         'Original typography, figures and equations remain on the PDF page. '
                         'Knowledge extraction is shown separately for review.\n\n')
            page.insert_textbox(fitz.Rect(44, 167, 288, 460), paragraph * 4, fontsize=11, fontname='tiro')
            page.insert_textbox(fitz.Rect(324, 167, 568, 300), paragraph * 2, fontsize=11, fontname='tiro')
            page.insert_text((330, 328), 'SNR = 6.02N + 1.76', fontsize=16, fontname='tiit')
            page.insert_text((548, 328), '(1)', fontsize=11, fontname='tiro')
            for left, label in [(330, 'ADC'), (465, 'FFE')]:
                page.draw_rect(fitz.Rect(left, 377, left + 84, 428), color=(.12, .25, .45), fill=(.9, .95, 1))
                page.insert_text((left + 23, 407), label, fontsize=14)
            page.draw_line(fitz.Point(414, 402), fitz.Point(465, 402), color=(.12, .25, .45))
            page.insert_text((324, 450), 'Fig. 1. Hybrid receiver signal path.', fontsize=10, fontname='tiro')
            # A raster asset as well as vector content must survive full-page rendering.
            tile = fitz.Pixmap(fitz.csRGB, (0, 0, 120, 60), False)
            tile.clear_with(215)
            page.insert_image(fitz.Rect(44, 490, 288, 612), pixmap=tile)
            page.insert_text((44, 632), 'Fig. 2. Embedded measurement image.', fontsize=10, fontname='tiro')
            page.insert_textbox(fitz.Rect(324, 490, 568, 700), paragraph * 3, fontsize=11, fontname='tiro')
            page.insert_text((44, 756), 'Source PDF - page geometry and illustration positions are preserved.', fontsize=9)
        return pdf.tobytes()


def test_page_render_preserves_original_pixels():
    raw = sample_pdf()
    info = pdf_manifest(raw)
    assert info['page_count'] == 3
    assert info['pages'][0]['width'] == 612
    actual = fitz.Pixmap(render_pdf_page(raw, 2, 1224))
    with fitz.open(stream=raw, filetype='pdf') as original:
        expected = original[1].get_pixmap(matrix=fitz.Matrix(2, 2), colorspace=fitz.csRGB, alpha=False)
        assert original[1].get_images()
        assert actual.samples == expected.samples
        assert (actual.width, actual.height) == (1224, 1584)


def test_invalid_missing_encrypted_and_out_of_range():
    for raw, status in [(b'', 404), (b'not a PDF', 422)]:
        with pytest.raises(HTTPException) as caught:
            pdf_manifest(raw)
        assert caught.value.status_code == status
    for page in [0, 4, -1]:
        with pytest.raises(HTTPException) as caught:
            render_pdf_page(sample_pdf(), page)
        assert caught.value.status_code == 404
    with fitz.open(stream=sample_pdf(), filetype='pdf') as pdf:
        encrypted = pdf.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw='owner', user_pw='user')
    with pytest.raises(HTTPException) as caught:
        pdf_manifest(encrypted)
    assert caught.value.status_code == 422


def test_rotated_page_dimensions():
    with fitz.open(stream=sample_pdf(), filetype='pdf') as pdf:
        pdf[0].set_rotation(90)
        raw = pdf.tobytes()
    assert pdf_manifest(raw)['pages'][0] == {'number': 1, 'width': 792, 'height': 612, 'rotation': 90}
    rendered = fitz.Pixmap(render_pdf_page(raw, 1, 1584))
    assert (rendered.width, rendered.height) == (1584, 1224)


def test_pdf_routes(monkeypatch):
    raw = sample_pdf()
    stored = {'paper': raw}
    doc = SimpleNamespace(id='doc-1', filename='技术论文.pdf', object_key='paper')

    class Session:
        async def get(self, model, key):
            return doc if key == doc.id else None

    app = FastAPI()
    app.include_router(documents.router, prefix='/api')
    app.dependency_overrides[get_session] = lambda: Session()
    monkeypatch.setattr(documents, 'get_stores', lambda: SimpleNamespace(minio=SimpleNamespace(get=lambda key: stored.get(key, b''))))
    with TestClient(app) as client:
        assert client.get('/api/documents/doc-1/source').json()['page_count'] == 3
        response = client.get('/api/documents/doc-1/pages/2?width=1224')
        assert response.status_code == 200
        assert response.headers['content-type'] == 'image/png'
        assert response.content.startswith(b'\x89PNG')
        layer = client.get('/api/documents/doc-1/pages/1/text').json()
        assert layer['page'] == 1
        assert any('Hybrid ADC' in span['text'] for span in layer['spans'])
        assert client.get('/api/documents/doc-1/pages/0').status_code == 404
        assert client.get('/api/documents/doc-1/pages/0/text').status_code == 404
        assert client.get('/api/documents/doc-1/pages/1?width=99999').status_code == 422
        download = client.get('/api/documents/doc-1/original')
        assert download.content == raw
        assert "filename*=UTF-8''" in download.headers['content-disposition']
        assert client.get('/api/documents/missing/source').status_code == 404
        stored.clear()
        assert client.get('/api/documents/doc-1/source').status_code == 404
        doc.filename = 'notes.md'
        assert client.get('/api/documents/doc-1/source').status_code == 415


def test_page_text_layer_is_selectable_and_aligned():
    raw = sample_pdf()
    layer = page_text_layer(raw, 1)
    joined = '\n'.join(span['text'] for span in layer['spans'])
    assert 'A Hybrid ADC-Based Receiver' in joined
    assert 'SNR = 6.02N + 1.76' in joined
    assert all(0 <= span[key] <= 1 for span in layer['spans'] for key in ('x', 'y', 'w', 'h'))
    assert all(span['w'] > 0 and span['h'] > 0 for span in layer['spans'])
    title = next(span for span in layer['spans'] if 'Hybrid ADC' in span['text'])
    # 标题在页眉下方、左栏区域内，避免叠层偏离渲染图
    assert title['y'] < 0.2
    assert title['x'] < 0.3


def test_rotated_page_text_layer_uses_visible_rect():
    with fitz.open(stream=sample_pdf(), filetype='pdf') as pdf:
        pdf[0].set_rotation(90)
        raw = pdf.tobytes()
    layer = page_text_layer(raw, 1)
    assert layer['width'] == 792
    assert layer['height'] == 612
    assert any('Hybrid ADC' in span['text'] for span in layer['spans'])
    assert all(0 <= span[key] <= 1 for span in layer['spans'] for key in ('x', 'y', 'w', 'h'))


def test_image_only_page_has_empty_text_layer():
    with fitz.open() as pdf:
        page = pdf.new_page(width=200, height=200)
        tile = fitz.Pixmap(fitz.csRGB, (0, 0, 80, 40), False)
        tile.clear_with(180)
        page.insert_image(fitz.Rect(20, 20, 180, 180), pixmap=tile)
        raw = pdf.tobytes()
    assert page_text_layer(raw, 1)['spans'] == []


def test_corrupt_page_stream_is_reported():
    # A valid PDF container can hold a damaged compressed page stream.
    with fitz.open(stream=sample_pdf(), filetype='pdf') as pdf:
        xref = pdf[0].get_contents()[0]
        pdf.update_stream(xref, b'invalid zlib stream', compress=False)
        pdf.xref_set_key(xref, 'Filter', '/FlateDecode')
        raw = pdf.tobytes()
    with pytest.raises(HTTPException) as caught:
        render_pdf_page(raw, 1)
    assert caught.value.status_code == 422


if __name__ == '__main__':
    # Export browser fixtures from the exact renderer used by the API.
    import json
    out = Path(__file__).resolve().parents[2] / 'artifacts' / 'pdf-review'
    out.mkdir(parents=True, exist_ok=True)
    raw = sample_pdf()
    (out / 'manifest.json').write_text(json.dumps(pdf_manifest(raw)), encoding='utf-8')
    for number in range(1, 4):
        (out / f'fixture-page-{number}.png').write_bytes(render_pdf_page(raw, number, 2000))
