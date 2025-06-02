# ebtg/tests/test_simplified_html_extractor.py
import unittest
from ebtg.simplified_html_extractor import SimplifiedHtmlExtractor
from ebtg.ebtg_exceptions import XhtmlExtractionError

class TestSimplifiedHtmlExtractor(unittest.TestCase):

    def setUp(self):
        self.extractor = SimplifiedHtmlExtractor()

    def test_extract_empty_string(self):
        content_items = self.extractor.extract_content("")
        self.assertEqual(content_items, [])

    def test_extract_text_only(self):
        xhtml = "<body><p>Hello World</p><p>Another paragraph.</p></body>"
        content_items = self.extractor.extract_content(xhtml)
        self.assertEqual(len(content_items), 2) # Each <p> content is a separate item
        self.assertEqual(content_items[0]["type"], "text")
        self.assertEqual(content_items[0]["data"], "Hello World")
        self.assertEqual(content_items[1]["data"], "Another paragraph.")

    def test_extract_image_only(self):
        xhtml = '<body><img src="image.png" alt="My Image"/></body>'
        content_items = self.extractor.extract_content(xhtml)
        self.assertEqual(len(content_items), 1)
        self.assertEqual(content_items[0]["type"], "image")
        self.assertEqual(content_items[0]["data"]["src"], "image.png")
        self.assertEqual(content_items[0]["data"]["alt"], "My Image")

    def test_extract_mixed_content(self):
        xhtml = """<body>
            <p>First text.</p>
            <img src="img1.jpg" alt="Image One"/>
            <p>Second text, with <span>nested</span> elements.</p>
            <img src="img2.jpg" alt="Image Two"/>
            <p>Third text.</p>
        </body>"""
        content_items = self.extractor.extract_content(xhtml)

        self.assertEqual(len(content_items), 5)
        self.assertEqual(content_items[0], {"type": "text", "data": "First text."})
        self.assertEqual(content_items[1], {"type": "image", "data": {"src": "img1.jpg", "alt": "Image One"}})
        self.assertEqual(content_items[2], {"type": "text", "data": "Second text, with nested elements."})
        self.assertEqual(content_items[3], {"type": "image", "data": {"src": "img2.jpg", "alt": "Image Two"}})
        self.assertEqual(content_items[4], {"type": "text", "data": "Third text."})

    def test_extract_no_body_tag(self):
        xhtml = "<p>Text without body.</p><img src='test.gif' alt='Test'/>"
        content_items = self.extractor.extract_content(xhtml)
        self.assertEqual(len(content_items), 2)
        self.assertEqual(content_items[0], {"type": "text", "data": "Text without body."})
        self.assertEqual(content_items[1], {"type": "image", "data": {"src": "test.gif", "alt": "Test"}})

    def test_extract_image_no_alt(self):
        xhtml = '<body><img src="no_alt.svg"/></body>'
        content_items = self.extractor.extract_content(xhtml)
        self.assertEqual(len(content_items), 1)
        self.assertEqual(content_items[0]["type"], "image")
        self.assertEqual(content_items[0]["data"]["src"], "no_alt.svg")
        self.assertEqual(content_items[0]["data"]["alt"], "")

    def test_extract_text_with_br_and_hr(self):
        xhtml = "<p>Line one.<br/>Line two.<hr/>Line three.</p>"
        content_items = self.extractor.extract_content(xhtml)
        # Current extractor joins text across <br> and <hr> might be seen as separators
        # Based on current logic, <br> and <hr> act as separators, flushing current_text_parts.
        self.assertEqual(len(content_items), 3) # Expecting three blocks due to <br> and <hr>
        self.assertEqual(content_items[0]["type"], "text")
        self.assertEqual(content_items[0]["data"], "Line one.")
        self.assertEqual(content_items[1]["type"], "text")
        self.assertEqual(content_items[1]["data"], "Line two.")
        self.assertEqual(content_items[2]["type"], "text")
        self.assertEqual(content_items[2]["data"], "Line three.")

    def test_text_directly_in_body(self):
        xhtml = "<body>Just some text directly in body.</body>"
        content_items = self.extractor.extract_content(xhtml)
        self.assertEqual(len(content_items), 1)
        self.assertEqual(content_items[0]["type"], "text")
        self.assertEqual(content_items[0]["data"], "Just some text directly in body.")

    def test_text_before_and_after_image_no_paragraph(self):
        xhtml = "<body>Text before <img src='img.png' alt='alt text'/> text after.</body>"
        content_items = self.extractor.extract_content(xhtml)
        self.assertEqual(len(content_items), 3)
        self.assertEqual(content_items[0], {"type": "text", "data": "Text before"})
        self.assertEqual(content_items[1], {"type": "image", "data": {"src": "img.png", "alt": "alt text"}})
        self.assertEqual(content_items[2], {"type": "text", "data": "text after."})

if __name__ == '__main__':
    unittest.main()
