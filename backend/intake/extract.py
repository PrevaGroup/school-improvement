"""Text out of the files a teacher's folder actually contains.

Pure functions over bytes. No filesystem, no network, no database — so every format quirk below is
testable against a fixture rather than against somebody's Drive.

WHY .docx IS PARSED HERE RATHER THAN WITH A LIBRARY. A .docx is a zip holding one XML file, and the
extraction that matters is four lines of it. `python-docx` would be a dependency, a supply-chain
surface and a version to keep current, in exchange for code that is shorter than the import
statement justifying it.

THE PARAGRAPH BOUNDARY IS THE WHOLE JOB. Word splits a sentence across <w:r> runs wherever
formatting changes — a bolded word, a spell-check marker, a tracked-change remnant — so naive text
extraction produces "Thereasoningis about power". Joining runs with nothing and paragraphs with a
newline is what makes the output match what the student sees on screen, and the span verifier
downstream compares against exactly that.

Nothing here normalizes typography. `scoring.verify` owns that, it is versioned, and a second
implementation drifting from the first is how a span starts failing verification for reasons
nobody can find.
"""
from __future__ import annotations

import io
import re
import zipfile
import xml.etree.ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

TEXT_MIMES = {"text/plain", "text/markdown", "text/x-markdown"}
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# Extensions a teacher's folder holds that are not a submission and not an error either.
KNOWN_UNSUPPORTED = {".pdf", ".doc", ".odt", ".rtf", ".pages", ".jpg", ".jpeg", ".png", ".heic"}


class Unreadable(Exception):
    """The file exists and its text could not be recovered. Not the same as empty."""


def extract(name: str, data: bytes, mime: str | None = None) -> str:
    """Text from one file, by what it actually is rather than what it is called."""
    suffix = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""

    # The magic number first: a .docx renamed to .txt is still a zip, and a teacher's folder has
    # seen stranger things. Sniffing beats trusting the name.
    if data[:2] == b"PK":
        return docx_text(data)
    if mime in TEXT_MIMES or suffix in {".txt", ".md", ".markdown"}:
        return plain_text(data)
    if suffix in KNOWN_UNSUPPORTED:
        raise Unreadable(f"{suffix} is not a format this can read yet")
    if mime == DOCX_MIME:
        raise Unreadable("declared as .docx but the bytes are not a zip — the file is damaged")
    # Try it as text rather than refusing on an unfamiliar extension: a Google Docs export with no
    # suffix is the common case, and a wrong guess here fails loudly at decode.
    return plain_text(data)


def plain_text(data: bytes) -> str:
    """UTF-8, then the two encodings Windows-authored files actually arrive in.

    `errors="strict"` on the way through: a file that decodes to mojibake is worse than one that
    refuses, because mojibake reaches a student as their own quoted words.
    """
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise Unreadable("could not decode the bytes as text in any expected encoding")


def docx_text(data: bytes) -> str:
    """Paragraph text from an OOXML document.

    Runs join with nothing and paragraphs join with a newline, because Word splits a sentence
    across runs wherever formatting changes. `<w:tab/>` and `<w:br/>` are real characters the
    student typed and are kept; everything else in the run is markup.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml")
    except KeyError as exc:
        raise Unreadable(
            "a zip without word/document.xml — a .pages or .odt file wearing a .docx name") from exc
    except zipfile.BadZipFile as exc:
        raise Unreadable("not a readable zip archive") from exc

    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise Unreadable(f"word/document.xml did not parse: {exc}") from exc

    paragraphs = []
    for para in root.iter(f"{W}p"):
        pieces = []
        for node in para.iter():
            if node.tag == f"{W}t":
                pieces.append(node.text or "")
            elif node.tag == f"{W}tab":
                pieces.append("\t")
            elif node.tag in (f"{W}br", f"{W}cr"):
                pieces.append("\n")
        paragraphs.append("".join(pieces))

    # Trailing empty paragraphs are Word's, not the student's. Interior ones are the blank lines
    # between paragraphs and stay.
    while paragraphs and not paragraphs[-1].strip():
        paragraphs.pop()
    return "\n".join(paragraphs)


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'’-]+\b", text))


def looks_like_the_prompt(name: str, text: str) -> bool:
    """Is this the assignment rather than a submission?

    The prompt and the blank template sit in these folders routinely, and scoring one produces a
    confident level for a paper nobody wrote. Two signals, both weak alone: a name that says so,
    and a document made mostly of blanks.

    Deliberately conservative. A false positive silently drops a real student's work, which is far
    worse than a false negative — the prompt scored by mistake is visible on the review screen and
    a teacher deletes it in a second.
    """
    # Word boundaries, not substrings: "prompt" would otherwise match "prompted", and a student
    # file called "what the prompt asked" is a submission.
    #
    # "rubric" is deliberately NOT here. It caught "essay about the rubric we discussed" — a real
    # student filename — and by the rule below a false positive silently drops somebody's work.
    # The rubric document is not usually in a submission folder anyway, so the signal was buying
    # little and risking the expensive error.
    if re.search(r"\b(prompt|template|instructions|directions|handout|assignment\s*sheet)\b",
                 name, re.I):
        return True
    # A form to fill in: lots of underscore rules or bracketed placeholders, little else.
    blanks = len(re.findall(r"_{3,}|\[[^\]]{0,40}\]", text))
    return blanks >= 5 and blanks * 40 > len(text)
