import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"src"))
from app_store import archive, restore, edit_document, mark_index_current, index_dirty, save_history, histories, feedback
from document_manager import extract_text, save_upload


class StoreTests(unittest.TestCase):
    def test_document_lifecycle_and_dirty_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root/"data/processed/sanitized/demo.md"
            path.parent.mkdir(parents=True)
            text = "---\nsource_id: S1\nacl: fde-core\nproduct_group: 通用\ndocument_type: 团队说明\n---\n## 说明\n原内容"
            path.write_text(text,encoding="utf-8")
            mark_index_current(root)
            self.assertFalse(index_dirty(root))
            backup = edit_document(root,path,text.replace("原内容","新内容"))
            self.assertIn("原内容", backup.read_text(encoding="utf-8"))
            self.assertTrue(index_dirty(root))
            mark_index_current(root)
            archived = archive(root,path)
            self.assertFalse(path.exists())
            self.assertTrue(index_dirty(root))
            restore(root,archived)
            self.assertFalse(index_dirty(root))
            with self.assertRaises(ValueError):
                edit_document(root,path,text.replace("fde-core","external"))

    def test_history_excludes_passage_and_updates_feedback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            key=save_history(root,"问题",[{"source_file":"demo","locator":"L1","text":"PRIVATE FULL TEXT"}])
            self.assertNotIn("PRIVATE FULL TEXT",json.dumps(histories(root)))
            feedback(root,key,"正确且证据充分","已核对")
            self.assertEqual(histories(root)[0]["note"],"已核对")
            with self.assertRaises(ValueError):
                feedback(root,"../test","x","")

    def test_docx_extraction_including_tables(self):
        buffer=io.BytesIO()
        xml='<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>说明</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>电压</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>12V</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>'
        with zipfile.ZipFile(buffer,"w") as package:
            package.writestr("word/document.xml",xml)
        self.assertIn("电压 | 12V",extract_text("demo.docx",buffer.getvalue()))

    def test_empty_pdf_rejected(self):
        from pypdf import PdfWriter
        writer=PdfWriter()
        writer.add_blank_page(100,100)
        buffer=io.BytesIO()
        writer.write(buffer)
        with self.assertRaisesRegex(ValueError,"OCR"):
            extract_text("scan.pdf",buffer.getvalue())

    def test_text_pdf_extraction(self):
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
        writer=PdfWriter()
        page=writer.add_blank_page(200,200)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        stream=DecodedStreamObject()
        stream.set_data(b'BT /F1 12 Tf 20 100 Td (Maintenance Monday) Tj ET')
        page[NameObject('/Contents')]=writer._add_object(stream)
        buffer=io.BytesIO()
        writer.write(buffer)
        self.assertIn('Maintenance Monday',extract_text('demo.pdf',buffer.getvalue()))

    def test_duplicate_upload_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            save_upload(root,"a.md",b"hello")
            with self.assertRaisesRegex(ValueError,"已上传"):
                save_upload(root,"b.md",b"hello")


if __name__ == "__main__":
    unittest.main()
