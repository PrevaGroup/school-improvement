"""Getting text out of the files a teacher's folder actually contains.

The .docx cases are built as real zips rather than mocked, because the failure this file exists to
prevent is a real one: Word splits a sentence across runs wherever formatting changes, and naive
extraction produces "Thereasoningis about power". That text then goes to the span verifier, which
compares it character for character — so a run-joining bug does not look like a run-joining bug. It
looks like the model fabricating evidence, on exactly the papers that had a bolded word in them.
"""
from __future__ import annotations

import io
import zipfile

import pytest

from intake.extract import (DOCX_MIME, Unreadable, docx_text, extract, looks_like_the_prompt,
                            plain_text, word_count)

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def docx(*paragraphs: list[str] | str, damaged: bool = False, wrong_member: bool = False) -> bytes:
    """A real .docx. Each paragraph is a string, or a list of RUNS that Word would have split."""
    body = []
    for para in paragraphs:
        runs = [para] if isinstance(para, str) else para
        body.append("<w:p>" + "".join(f"<w:r><w:t>{r}</w:t></w:r>" for r in runs) + "</w:p>")
    xml = (f'<?xml version="1.0"?><w:document xmlns:w="{W}"><w:body>'
           + "".join(body) + "</w:body></w:document>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", "NOT XML" if damaged else xml)
        if wrong_member:
            z.writestr("index.html", "<html></html>")
    data = buf.getvalue()
    if wrong_member:
        # A .pages or .odt wearing a .docx name: a zip with no word/document.xml.
        buf2 = io.BytesIO()
        with zipfile.ZipFile(buf2, "w") as z:
            z.writestr("index.html", "<html></html>")
        return buf2.getvalue()
    return data


# ------------------------------------------------------------------ the run-joining problem


def test_runs_within_a_paragraph_join_with_nothing():
    """THE bug this file exists for. Word splits "about power" across runs at a bold marker; a
    newline or a space between them corrupts every span the verifier is asked to confirm."""
    out = docx_text(docx(["The reasoning is ", "about", " power."]))
    assert out == "The reasoning is about power."


def test_paragraphs_join_with_a_newline():
    out = docx_text(docx("First paragraph.", "Second paragraph."))
    assert out == "First paragraph.\nSecond paragraph."


def test_an_interior_blank_paragraph_is_kept():
    """The blank line between paragraphs is the student's formatting and part of what they wrote."""
    assert docx_text(docx("One.", "", "Two.")) == "One.\n\nTwo."


def test_trailing_empty_paragraphs_are_dropped():
    """Word's, not the student's — every document ends with them."""
    assert docx_text(docx("One.", "", "  ", "")) == "One."


def test_a_document_with_no_paragraphs_is_empty_not_unreadable():
    """Empty and unreadable are different facts and a teacher acts differently on each."""
    assert docx_text(docx()) == ""


# ------------------------------------------------------------------ what unreadable means


def test_a_zip_without_a_word_document_is_unreadable():
    with pytest.raises(Unreadable, match="wearing a .docx name"):
        docx_text(docx("x", wrong_member=True))


def test_damaged_xml_is_unreadable():
    with pytest.raises(Unreadable, match="did not parse"):
        docx_text(docx("x", damaged=True))


def test_bytes_that_are_not_a_zip_are_unreadable_as_docx():
    with pytest.raises(Unreadable, match="not a readable zip"):
        docx_text(b"This is plain text pretending to be a document.")


@pytest.mark.parametrize("name", ["essay.pdf", "essay.doc", "scan.jpg", "notes.pages"])
def test_a_format_we_cannot_read_says_so_rather_than_guessing(name):
    """An inventory discrepancy, not an absence. A missing score and an unreadable file mean
    different things to a teacher."""
    with pytest.raises(Unreadable, match="not a format this can read"):
        extract(name, b"%PDF-1.7 whatever")


# ------------------------------------------------------------------ dispatch by content


def test_a_docx_renamed_to_txt_is_still_read_as_a_docx():
    """The magic number beats the name. A teacher's folder has seen stranger things."""
    out = extract("essay.txt", docx("Renamed but still a zip."), mime="text/plain")
    assert out == "Renamed but still a zip."


def test_a_google_docs_export_with_no_suffix_is_tried_as_text():
    assert extract("Maya Okonkwo - final draft", b"Some prose.") == "Some prose."


def test_plain_text_survives_a_utf8_bom():
    """Notepad and Excel exports carry one, and a leading U+FEFF at the front of a paper would sit
    inside the first verified span forever."""
    assert plain_text("The Court held.".encode("utf-8-sig")) == "The Court held."


def test_windows_encoded_text_decodes_rather_than_failing():
    """cp1252 is what a Windows-authored .txt actually arrives as, curly quotes and all."""
    out = plain_text("The Court’s reasoning".encode("cp1252"))
    assert "reasoning" in out and len(out.split()) == 3


def test_utf8_is_preferred_over_the_windows_fallback():
    """Order matters: cp1252 decodes almost any byte sequence into something, so trying it first
    would turn valid UTF-8 into mojibake that reaches a student as their own quoted words."""
    assert plain_text("The Court’s reasoning".encode("utf-8")) == "The Court’s reasoning"


# ------------------------------------------------------------------ the prompt in the folder


def test_a_file_named_like_the_assignment_is_not_student_work():
    """Scoring the prompt produces a confident level for a paper nobody wrote."""
    assert looks_like_the_prompt("Free Speech PROMPT.docx", "Write an op-ed about...")
    assert looks_like_the_prompt("op-ed template", "Your claim: ______")


def test_a_form_of_blanks_is_not_student_work():
    assert looks_like_the_prompt("handin", "Claim: _____\nEvidence: _____\nReason: _____\n"
                                           "Counter: _____\nRebuttal: _____")


def test_a_real_essay_is_not_mistaken_for_the_prompt():
    """Conservative on purpose. A false positive silently drops a student's work; a false negative
    puts the prompt on the review screen where a teacher deletes it in a second."""
    essay = ("Tinker asked schools to prove something. The exceptions ask students to prove "
             "something instead. The Court has drifted toward school authority.")
    assert not looks_like_the_prompt("Devon Ruiz - op-ed.docx", essay)
    # Caught this one when it was written: "rubric" was in the keyword list and this is a
    # plausible student filename. By the rule above, that is the expensive direction to be wrong.
    assert not looks_like_the_prompt("essay about the rubric we discussed", essay)
    assert not looks_like_the_prompt("what the prompted question asked", essay)


def test_word_count_counts_words_not_tokens():
    assert word_count("The Court’s reasoning — about power.") == 5
