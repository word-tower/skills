#!/usr/bin/env python3
"""Inspect, read and subset an EPUB locally. Python standard library only; no network."""
import argparse
import copy
import hashlib
import html.entities
import io
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import sys
from urllib.parse import quote, unquote, urlsplit
import xml.etree.ElementTree as ET
import zipfile

XHTML = "http://www.w3.org/1999/xhtml"
OPF = "http://www.idpf.org/2007/opf"
EPUB = "http://www.idpf.org/2007/ops"
DC = "http://purl.org/dc/elements/1.1/"
NCX = "http://www.daisy.org/z3986/2005/ncx/"
ET.register_namespace("", XHTML)
ET.register_namespace("opf", OPF)
ET.register_namespace("epub", EPUB)
ET.register_namespace("dc", DC)
ET.register_namespace("ncx", NCX)
DOC_TYPES = {"application/xhtml+xml", "text/html"}
BLOCKS = {"p", "div", "section", "article", "li", "aside", "blockquote", "br", "h1", "h2", "h3", "h4", "tr"}


class SelectionError(ValueError):
    """A local, deliberately non-sensitive validation message suitable for the Agent."""


def local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def xml(data):
    if b"<!ENTITY" in data.replace(b"\0", b"").upper():
        raise SelectionError("Custom XML entities are unsupported")
    # EPUB 2 sometimes uses XHTML named entities without an internal DTD.
    data = re.sub(rb"&([A-Za-z][A-Za-z0-9]+);", lambda m: (
        f"&#{html.entities.name2codepoint[m[1].decode()]};".encode()
        if m[1].decode() in html.entities.name2codepoint and m[1] not in {b"amp", b"lt", b"gt", b"quot", b"apos"} else m[0]), data)
    root = ET.fromstring(data)
    if any("{http://www.w3.org/XML/1998/namespace}base" in node.attrib or local(node.tag) == "base" for node in root.iter()):
        raise SelectionError("EPUB xml:base/base URI rewriting is unsupported")
    return root


def target(base, href):
    url = urlsplit(href)
    if url.scheme or url.netloc:
        return None
    path = posixpath.normpath(posixpath.join(posixpath.dirname(base), unquote(url.path))) if url.path else base
    if path.startswith(("/", "../")) or path == ".." or "\\" in path:
        raise SelectionError("Reference escapes the EPUB")
    return path, unquote(url.fragment)


def text_content(node):
    result = []
    def visit(item):
        if local(item.tag) not in {"script", "style", "nav"}:
            if local(item.tag) in BLOCKS: result.append("\n")
            if item.text: result.append(item.text)
            for child in item:
                visit(child)
                if child.tail: result.append(child.tail)
            if local(item.tag) in BLOCKS: result.append("\n")
    visit(node)
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[^\S\n]+", " ", "".join(result))).strip()


def find_id(root, value):
    return next((node for node in root.iter() if value in (
        node.get("id"), node.get("{http://www.w3.org/XML/1998/namespace}id"), node.get("name"))), None)


class Document:
    def __init__(self, data):
        self.root = xml(data)
        self.body = next((node for node in self.root.iter() if local(node.tag) == "body"), None)
        if self.body is None: raise SelectionError("EPUB document has no body")
        self.positions, self.tails, self.parents, self.ids = {}, {}, {}, {}
        self.size = 0
        def visit(node):
            self.positions[node] = self.size; self.size += 1
            for identifier in {node.get("id"), node.get("{http://www.w3.org/XML/1998/namespace}id"), node.get("name")} - {None, ""}:
                if identifier in self.ids: raise SelectionError("Duplicate anchor ID in an EPUB document")
                self.ids[identifier] = node
            for child in node:
                self.parents[child] = node; visit(child)
                self.tails[child] = self.size; self.size += 1
        visit(self.body)

    def shell(self, body):
        root = copy.deepcopy(self.root)
        parent = next(node for node in root.iter() if any(local(child.tag) == "body" for child in node))
        original = next(child for child in parent if local(child.tag) == "body")
        parent.remove(original); parent.append(body)
        for node in root.iter():
            for child in list(node):
                if local(child.tag) == "script": node.remove(child)
            for name in list(node.attrib):
                if local(name).lower().startswith("on"): del node.attrib[name]
        return root

    def slice(self, ranges):
        def inside(position): return any(start <= position < end for start, end in ranges)
        def clip(node):
            if local(node.tag) == "script": return None
            own = inside(self.positions[node])
            result = ET.Element(node.tag, dict(node.attrib))
            result.text = node.text if own else None
            for child in node:
                selected = clip(child)
                tail = child.tail if inside(self.tails[child]) else None
                if selected is not None:
                    selected.tail = tail; result.append(selected)
                elif tail:
                    if len(result): result[-1].tail = (result[-1].tail or "") + tail
                    else: result.text = (result.text or "") + tail
            return result if own or len(result) or result.text else None
        result = clip(self.body)
        return result if result is not None else ET.Element(self.body.tag, dict(self.body.attrib))


class Book:
    def __init__(self, data):
        if len(data) > 100 * 1024 * 1024: raise SelectionError("Local source EPUB exceeds 100 MiB")
        self.sha256 = hashlib.sha256(data).hexdigest()
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            items = archive.infolist()
            if len(items) > 6000 or sum(item.file_size for item in items) > 200 * 1024 * 1024:
                raise SelectionError("EPUB exceeds local expanded limits")
            names = set()
            for item in items:
                name = unquote(item.filename)
                if (name in names or name.startswith("/") or ".." in PurePosixPath(name).parts or ":" in name or "\\" in name
                        or item.flag_bits & 1 or item.file_size > 16 * 1024 * 1024
                        or item.file_size > max(1, item.compress_size) * 1000):
                    raise SelectionError("Unsafe, encrypted or oversized EPUB entry")
                names.add(name)
            self.files = {unquote(item.filename): archive.read(item) for item in items if not item.is_dir()}
        if self.files.get("mimetype", b"").strip() != b"application/epub+zip" or "META-INF/encryption.xml" in self.files:
            raise SelectionError("Expected an unencrypted EPUB")
        container = xml(self.files["META-INF/container.xml"])
        roots = [node.get("full-path") for node in container.iter() if local(node.tag) == "rootfile"]
        if len(roots) != 1: raise SelectionError("Expected one EPUB package")
        self.opf_path = unquote(roots[0]); self.opf = xml(self.files[self.opf_path])
        self.manifest = next(node for node in self.opf if local(node.tag) == "manifest")
        self.spine = next(node for node in self.opf if local(node.tag) == "spine")
        self.items, self.by_path = {}, {}
        for node in self.manifest:
            path = target(self.opf_path, node.get("href", ""))
            if path is None or not node.get("id"): raise SelectionError("Invalid package manifest")
            path = path[0]
            if node.get("id") in self.items or path in self.by_path: raise SelectionError("Duplicate manifest item")
            self.items[node.get("id")] = node; self.by_path[path] = node
        self.title = next((node.text for node in self.opf.iter() if node.tag == f"{{{DC}}}title" and node.text), "Untitled")
        self.docs = {}
        def document(path):
            if path not in self.docs: self.docs[path] = Document(self.files[path])
            return self.docs[path]
        self.document = document
        order = []
        for ref in self.spine:
            item = self.items[ref.get("idref")]
            if item.get("media-type") in DOC_TYPES and "nav" not in item.get("properties", "").split() and ref.get("linear", "yes") != "no":
                order.append(target(self.opf_path, item.get("href"))[0])
        if len(order) != len(set(order)): raise SelectionError("Repeated spine document")
        toc = self.toc()
        for path, fragment, title, labels in toc:
            if path not in order: order.append(path)
        if not order: raise SelectionError("EPUB contains no reading documents")
        self.order, self.bases, end = order, {}, 0
        for path in order:
            self.bases[path] = end; end += document(path).size
        starts = {}
        for path, fragment, title, labels in toc:
            doc = document(path)
            node = doc.ids.get(fragment) if fragment else doc.body
            if node is None: raise SelectionError("Table of contents points to a missing anchor")
            point = self.bases[path] + doc.positions[node]
            starts[point] = dict(title=title, toc_path=labels, path=path, fragment=fragment)
        if not starts:
            for path in order:
                doc = document(path)
                title = next((text_content(node) for node in doc.root.iter() if local(node.tag) == "title"), path)
                starts[self.bases[path]] = dict(title=title, toc_path=[title], path=path, fragment="")
        first = min(starts)
        if first and text_content(self.slice_roots(0, first)[order[0]]):
            starts[0] = dict(title="前置内容", toc_path=["前置内容"], path=order[0], fragment="")
        points = sorted(starts)
        if len(points) > 1000: raise SelectionError("EPUB exceeds 1000 selectable sections")
        self.chapters = []
        for index, point in enumerate(points):
            unit = {**starts[point], "start": point, "end": points[index + 1] if index + 1 < len(points) else end}
            unit["id"] = "c_" + hashlib.sha256(f"{self.sha256}:{point}".encode()).hexdigest()[:20]
            unit["reading_order"] = index + 1
            self.chapters.append(unit)

    def toc(self):
        nav = next((path for path, item in self.by_path.items() if "nav" in item.get("properties", "").split()), None)
        entries = []
        if nav:
            root = xml(self.files[nav])
            toc = next((node for node in root.iter() if local(node.tag) == "nav" and "toc" in node.get(f"{{{EPUB}}}type", "").split()), None)
            def walk(node, parents):
                for child in node:
                    if local(child.tag) == "li":
                        label = next((item for item in child if local(item.tag) in {"a", "span"}), None)
                        title = "".join(label.itertext()).strip() if label is not None else ""
                        labels = parents + ([title] if title else [])
                        if label is not None and label.get("href"):
                            dest = target(nav, label.get("href"))
                            if dest and self.by_path.get(dest[0]) is not None and self.by_path[dest[0]].get("media-type") in DOC_TYPES:
                                entries.append((*dest, title, labels))
                            else: raise SelectionError("Unsupported table-of-contents target")
                        for nested in child:
                            if local(nested.tag) == "ol": walk(nested, labels)
                    elif local(child.tag) == "ol": walk(child, parents)
            if toc is not None: walk(toc, [])
        if entries: return entries
        ncx = next((path for path, item in self.by_path.items() if item.get("media-type") == "application/x-dtbncx+xml"), None)
        if ncx:
            def walk(node, parents):
                for child in node:
                    if local(child.tag) == "navPoint":
                        title = next((item.text or "" for item in child.iter() if local(item.tag) == "text"), "Untitled")
                        content = next((item for item in child if local(item.tag) == "content"), None)
                        if content is not None:
                            dest = target(ncx, content.get("src", ""))
                            if dest is None or dest[0] not in self.by_path: raise SelectionError("Invalid NCX target")
                            entries.append((*dest, title, parents + [title]))
                        walk(child, parents + [title])
                    elif local(child.tag) == "navMap": walk(child, parents)
            walk(xml(self.files[ncx]), [])
        return entries

    def slice_roots(self, start, end):
        return {path: self.document(path).slice([(max(0, start - base), min(self.document(path).size, end - base))])
                for path, base in self.bases.items() if base < end and base + self.document(path).size > start}

    def chapter_text(self, unit):
        return "\n\n".join(text_content(root) for root in self.slice_roots(unit["start"], unit["end"]).values()).strip()

    def catalog(self):
        return {"format_version": "wordtower.epub.catalog.v1", "source_sha256": self.sha256, "title": self.title,
                "chapters": [{"chapter_id": unit["id"], "reading_order": unit["reading_order"], "title": unit["title"],
                              "toc_path": unit["toc_path"], "text_chars": len(self.chapter_text(unit))} for unit in self.chapters]}


def validate_plan(book, plan):
    if not isinstance(plan, dict) or set(plan) - {"source_sha256", "mode", "criteria", "chapter_ids", "assessments"}:
        raise SelectionError("Invalid selection plan fields")
    if plan.get("source_sha256") != book.sha256: raise SelectionError("Source EPUB changed; inspect and select again")
    if not isinstance(plan.get("mode"), str) or plan["mode"] not in {"chapters", "topic"} or not isinstance(plan.get("criteria"), str) or not 1 <= len(plan["criteria"].strip()) <= 2000:
        raise SelectionError("Selection requires mode and user criteria")
    ids, known = plan.get("chapter_ids"), {unit["id"]: unit for unit in book.chapters}
    if not isinstance(ids, list) or not ids or any(not isinstance(value, str) or value not in known for value in ids) or len(set(ids)) != len(ids):
        raise SelectionError("Select unique chapter IDs from the current catalog")
    if plan["mode"] == "topic":
        assessments = plan.get("assessments")
        if not isinstance(assessments, list) or len(assessments) != len(known): raise SelectionError("Topic selection must assess every catalog section")
        seen, included = set(), set()
        for item in assessments:
            if not isinstance(item, dict) or set(item) != {"chapter_id", "decision", "reason", "evidence"}:
                raise SelectionError("Invalid topic assessment")
            identifier = item["chapter_id"]
            if not isinstance(identifier, str) or identifier not in known or identifier in seen: raise SelectionError("Invalid assessed chapter ID")
            seen.add(identifier)
            if not isinstance(item["decision"], str) or item["decision"] not in {"include", "exclude", "uncertain"} or not isinstance(item["reason"], str) or not 1 <= len(item["reason"].strip()) <= 2000:
                raise SelectionError("Each topic assessment needs a decision and reason")
            evidence = item["evidence"]
            if not isinstance(evidence, list) or len(evidence) > 10: raise SelectionError("Invalid topic evidence")
            if item["decision"] != "uncertain" and not evidence: raise SelectionError("A topic judgment requires original-text evidence")
            text = book.chapter_text(known[identifier])
            for proof in evidence:
                if not isinstance(proof, dict) or set(proof) != {"start_offset", "end_offset", "quote"}: raise SelectionError("Invalid topic evidence fields")
                start, end, quoted = proof["start_offset"], proof["end_offset"], proof["quote"]
                if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text)
                        or not isinstance(quoted, str) or not quoted.strip() or len(quoted) > 4000 or text[start:end] != quoted):
                    raise SelectionError("Topic evidence does not match chapter text")
            if item["decision"] == "include": included.add(identifier)
        if set(ids) != included: raise SelectionError("Selected chapters must exactly match include decisions")
    return [unit for unit in book.chapters if unit["id"] in set(ids)]


def note_scope(doc, node):
    cursor = node
    while cursor is not None and cursor is not doc.body:
        if set(cursor.get(f"{{{EPUB}}}type", "").split()) & {"footnote", "endnote"} or cursor.get("role") in {"doc-footnote", "doc-endnote"}:
            return cursor
        cursor = doc.parents.get(cursor)
    cursor = node
    while cursor is not None and cursor is not doc.body:
        if local(cursor.tag) in {"p", "li", "aside"}: return cursor
        cursor = doc.parents.get(cursor)
    raise SelectionError("Cannot safely isolate the referenced footnote")


def css_refs(text):
    def space(index):
        while index < len(text):
            if text[index].isspace(): index += 1
            elif text.startswith("/*", index):
                end = text.find("*/", index + 2)
                index = len(text) if end < 0 else end + 2
            else: break
        return index
    def string(index):
        delimiter, start = text[index], index + 1; index += 1
        while index < len(text):
            if text[index] == "\\": index += 2
            elif text[index] == delimiter: return text[start:index], index + 1
            else: index += 1
        raise SelectionError("Unterminated CSS string")
    index = 0
    while index < len(text):
        index = space(index)
        if index >= len(text): break
        if text[index] in "\"'":
            _, index = string(index)  # A CSS content string is not a resource declaration.
            continue
        imported = re.match(r"@import\b", text[index:], re.I)
        if imported:
            index = space(index + imported.end())
            if index < len(text) and text[index] in "\"'":
                value, index = string(index)
                if "\\" in value: raise SelectionError("Escaped CSS resource URLs are unsupported")
                yield value
            continue
        if text[index:index + 4].lower() == "url(" and (index == 0 or not (text[index - 1].isalnum() or text[index - 1] in "_-")):
            index = space(index + 4)
            if index < len(text) and text[index] in "\"'":
                value, index = string(index); index = space(index)
                if index >= len(text) or text[index] != ")": raise SelectionError("Malformed CSS resource URL")
            else:
                end = text.find(")", index)
                if end < 0: raise SelectionError("Unterminated CSS resource URL")
                value, index = text[index:end].strip(), end
            index += 1
            if "\\" in value: raise SelectionError("Escaped CSS resource URLs are unsupported")
            if value: yield value
        else: index += 1


def subset(book, plan):
    selected = validate_plan(book, plan)
    roots, primary = {}, []
    for path in book.order:
        doc, base = book.document(path), book.bases[path]
        ranges = [(max(0, unit["start"] - base), min(doc.size, unit["end"] - base)) for unit in selected
                  if unit["start"] < base + doc.size and unit["end"] > base]
        if ranges:
            body = doc.slice(ranges)
            if text_content(body) or any(local(node.tag) in {"img", "svg", "math", "audio", "video", "object", "hr"} for node in body.iter()):
                roots[path] = doc.shell(body); primary.append(path)
    if not primary: raise SelectionError("Selected sections contain no importable content")
    notes, removed_links = set(), 0
    # Preserve only individually referenced notes, never an entire excluded notes/chapter document.
    changed = True
    while changed:
        changed = False
        for path, root in list(roots.items()):
            for node in list(root.iter()):
                if local(node.tag) not in {"a", "link"} or not node.get("href"): continue
                if urlsplit(node.get("href")).scheme.lower() in {"javascript", "vbscript", "file"}:
                    del node.attrib["href"]; removed_links += 1; continue
                dest = target(path, node.get("href"))
                if dest is None: continue
                other, fragment = dest
                item = book.by_path.get(other)
                if item is None or item.get("media-type") not in DOC_TYPES: continue
                if other in roots and (not fragment or find_id(roots[other], fragment) is not None): continue
                is_note = "noteref" in node.get(f"{{{EPUB}}}type", "").split() or node.get("role") == "doc-noteref"
                if is_note:
                    if not fragment: raise SelectionError("Footnote requires a fragment anchor")
                    doc = book.document(other); original = doc.ids.get(fragment)
                    if original is None: raise SelectionError("Referenced footnote is missing")
                    scope = note_scope(doc, original)
                    if len(text_content(scope)) > 20000 or len(notes) >= 1000: raise SelectionError("Referenced footnotes exceed limits")
                    if other not in roots: roots[other] = doc.shell(ET.Element(doc.body.tag, dict(doc.body.attrib)))
                    body = next(item for item in roots[other].iter() if local(item.tag) == "body")
                    copied = copy.deepcopy(scope); copied.tail = None
                    copied.set(f"{{{EPUB}}}type", "footnote"); body.append(copied)
                    notes.add((other, fragment)); changed = True
                else:
                    del node.attrib["href"]; removed_links += 1
    kept = set(roots)
    pending = list(roots)
    def add(base, ref):
        dest = target(base, ref)
        if dest is None: return
        path = dest[0]
        if path in roots: return
        item = book.by_path.get(path)
        if item is not None and item.get("media-type") in DOC_TYPES:
            raise SelectionError("A retained resource references an unselected document")
        if path not in book.files or item is None: raise SelectionError("Referenced EPUB resource is missing from its manifest")
        if path not in kept: kept.add(path); pending.append(path)
    # Cover art is rooted in the package, not necessarily referenced by a selected chapter.
    # EPUB 3 uses cover-image; EPUB 2 identifies the manifest ID through metadata.
    cover_ids = {identifier for identifier, item in book.items.items()
                 if "cover-image" in item.get("properties", "").split()}
    for metadata in book.opf:
        if local(metadata.tag) != "metadata": continue
        for node in metadata:
            if local(node.tag) == "meta" and node.get("name") == "cover":
                identifier = node.get("content")
                if not identifier: raise SelectionError("EPUB cover metadata has no image ID")
                cover_ids.add(identifier)
    cover_paths = set()
    for identifier in sorted(cover_ids):
        item = book.items.get(identifier)
        if item is None or not item.get("media-type", "").startswith("image/"):
            raise SelectionError("Declared EPUB cover is missing or is not an image")
        add(book.opf_path, item.get("href"))
        cover_paths.add(target(book.opf_path, item.get("href"))[0])
    while pending:
        path = pending.pop()
        item = book.by_path[path]
        if path in roots or item.get("media-type") in {"image/svg+xml", "application/smil+xml"}:
            root = roots[path] if path in roots else xml(book.files[path])
            for node in root.iter():
                for key, value in node.attrib.items():
                    if local(key) in {"src", "href", "poster", "data"}:
                        add(path, value)
                    if local(key) == "srcset":
                        if "data:" in value: raise SelectionError("Embedded data URLs in srcset are unsupported")
                        for part in value.split(","):
                            tokens = part.strip().split()
                            if tokens: add(path, tokens[0])
                    if local(key) == "style":
                        for ref in css_refs(value): add(path, ref)
                if local(node.tag) == "style" and node.text:
                    for ref in css_refs(node.text): add(path, ref)
        elif item.get("media-type") == "text/css":
            for ref in css_refs(book.files[path].decode("utf-8-sig")): add(path, ref)
    opf = copy.deepcopy(book.opf)
    manifest = next(node for node in opf if local(node.tag) == "manifest")
    kept_ids = set()
    for node in list(manifest):
        path = target(book.opf_path, node.get("href"))[0]
        if path not in kept: manifest.remove(node)
        else:
            kept_ids.add(node.get("id")); node.attrib.pop("media-overlay", None); node.attrib.pop("fallback", None)
    token = hashlib.sha256((book.sha256 + ":" + ":".join(unit["id"] for unit in selected)).encode()).hexdigest()[:20]
    nav_path = posixpath.join(posixpath.dirname(book.opf_path), f"wordtower-{token}.xhtml")
    ncx_path = nav_path[:-6] + ".ncx"
    if nav_path in book.files or ncx_path in book.files: raise SelectionError("Generated navigation filename collision")
    nav_id, ncx_id = "wt-" + token, "wt-ncx-" + token
    nav_attrs = {"id": nav_id, "href": posixpath.basename(nav_path), "media-type": "application/xhtml+xml"}
    if opf.get("version", "3").startswith("3"): nav_attrs["properties"] = "nav"
    ET.SubElement(manifest, f"{{{OPF}}}item", nav_attrs)
    ET.SubElement(manifest, f"{{{OPF}}}item", {"id": ncx_id, "href": posixpath.basename(ncx_path), "media-type": "application/x-dtbncx+xml"})
    spine = next(node for node in opf if local(node.tag) == "spine")
    for node in list(spine): spine.remove(node)
    spine.set("toc", ncx_id)
    for path in primary: ET.SubElement(spine, f"{{{OPF}}}itemref", {"idref": book.by_path[path].get("id")})
    for node in list(opf):
        if local(node.tag) not in {"metadata", "manifest", "spine"}: opf.remove(node)
    metadata = next(node for node in opf if local(node.tag) == "metadata")
    for node in list(metadata):
        if node.get("name") == "cover" and node.get("content") not in kept_ids: metadata.remove(node)
        elif node.get("refines", "").startswith("#") and not any(item.get("id") == node.get("refines")[1:] for item in opf.iter()): metadata.remove(node)
        elif local(node.tag) == "link" and node.get("href") and target(book.opf_path, node.get("href")) is not None:
            metadata.remove(node)
    title = next((node for node in metadata if node.tag == f"{{{DC}}}title"), None)
    if title is not None: title.text = book.title + "（选章）"
    unique = next((node for node in metadata if node.get("id") == opf.get("unique-identifier")), None)
    if unique is not None: unique.text = "urn:wordtower:selection:" + token
    nav = ET.Element(f"{{{XHTML}}}html"); head = ET.SubElement(nav, f"{{{XHTML}}}head")
    ET.SubElement(head, f"{{{XHTML}}}title").text = book.title + "（选章）"
    listing = ET.SubElement(ET.SubElement(ET.SubElement(nav, f"{{{XHTML}}}body"), f"{{{XHTML}}}nav", {f"{{{EPUB}}}type": "toc"}), f"{{{XHTML}}}ol")
    ncx = ET.Element(f"{{{NCX}}}ncx", {"version": "2005-1"}); ncx_head = ET.SubElement(ncx, f"{{{NCX}}}head")
    ET.SubElement(ncx_head, f"{{{NCX}}}meta", {"name": "dtb:uid", "content": "urn:wordtower:selection:" + token})
    ET.SubElement(ET.SubElement(ncx, f"{{{NCX}}}docTitle"), f"{{{NCX}}}text").text = book.title
    nav_map = ET.SubElement(ncx, f"{{{NCX}}}navMap")
    for index, unit in enumerate(selected, 1):
        href = quote(posixpath.relpath(unit["path"], posixpath.dirname(nav_path)), safe="/._-")
        if unit["fragment"]: href += "#" + quote(unit["fragment"], safe="")
        ET.SubElement(ET.SubElement(listing, f"{{{XHTML}}}li"), f"{{{XHTML}}}a", {"href": href}).text = unit["title"]
        point = ET.SubElement(nav_map, f"{{{NCX}}}navPoint", {"id": f"chapter-{index}", "playOrder": str(index)})
        ET.SubElement(ET.SubElement(point, f"{{{NCX}}}navLabel"), f"{{{NCX}}}text").text = unit["title"]
        ET.SubElement(point, f"{{{NCX}}}content", {"src": href})
    output = {path: ET.tostring(roots[path], encoding="utf-8", xml_declaration=True) if path in roots else book.files[path]
              for path in kept}
    for path, root in ((book.opf_path, opf), (nav_path, nav), (ncx_path, ncx)):
        output[path] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    output["META-INF/container.xml"] = book.files["META-INF/container.xml"]
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", b"application/epub+zip", compress_type=zipfile.ZIP_STORED)
        for path in sorted(output): archive.writestr(path, output[path])
    data = stream.getvalue()
    if len(data) > 20 * 1024 * 1024: raise SelectionError("Selected EPUB still exceeds the upload limit of 20 MiB")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) > 3000 or sum(item.file_size for item in entries) > 100 * 1024 * 1024 or any(item.file_size > 10 * 1024 * 1024 or item.file_size > max(1, item.compress_size) * 1000 for item in entries):
            raise SelectionError("Selected EPUB exceeds server archive limits")
    report = {"format_version": "wordtower.epub.selection.v1", "source_sha256": book.sha256,
              "output_sha256": hashlib.sha256(data).hexdigest(), "mode": plan["mode"], "criteria": plan["criteria"],
              "selected": [{"chapter_id": unit["id"], "title": unit["title"], "toc_path": unit["toc_path"]} for unit in selected],
              "excluded": [unit["id"] for unit in book.chapters if unit not in selected],
              "assessments": plan.get("assessments", []), "referenced_notes": len(notes), "removed_cross_chapter_links": removed_links,
              "preserved_cover_images": sorted(cover_paths)}
    return data, report


def private_write(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as output: output.write(data)
    except BaseException:
        Path(path).unlink(missing_ok=True); raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect"); inspect.add_argument("epub", type=Path); inspect.add_argument("--output", type=Path, required=True)
    read = commands.add_parser("read"); read.add_argument("epub", type=Path); read.add_argument("--chapter-id", required=True)
    read.add_argument("--offset", type=int, default=0); read.add_argument("--max-chars", type=int, default=8000)
    build = commands.add_parser("build"); build.add_argument("epub", type=Path); build.add_argument("--selection", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.epub.stat().st_size > 100 * 1024 * 1024: raise SelectionError("Local source EPUB exceeds 100 MiB")
    book = Book(args.epub.read_bytes())
    if args.command == "inspect":
        private_write(args.output, json.dumps(book.catalog(), ensure_ascii=False, indent=2).encode())
        print(json.dumps({"catalog": str(args.output.resolve()), "chapters": len(book.chapters), "source_sha256": book.sha256}))
    elif args.command == "read":
        unit = next((unit for unit in book.chapters if unit["id"] == args.chapter_id), None)
        if unit is None: raise SelectionError("Unknown chapter ID")
        text = book.chapter_text(unit)
        if not 0 <= args.offset <= len(text) or not 1 <= args.max_chars <= 20000: raise SelectionError("Invalid chapter text range")
        end = min(len(text), args.offset + args.max_chars)
        print(json.dumps({"chapter_id": unit["id"], "source_sha256": book.sha256, "title": unit["title"],
            "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "start_offset": args.offset, "end_offset": end,
            "total_chars": len(text), "has_more": end < len(text), "text": text[args.offset:end]}, ensure_ascii=False))
    else:
        if args.selection.stat().st_size > 2 * 1024 * 1024: raise SelectionError("Selection plan too large")
        plan = json.loads(args.selection.read_text(encoding="utf-8-sig"))
        data, report = subset(book, plan)
        sidecar = args.output.with_suffix(args.output.suffix + ".selection.json")
        if args.output.exists() or sidecar.exists(): raise SelectionError("Choose new output paths; original files are never overwritten")
        private_write(sidecar, json.dumps(report, ensure_ascii=False, indent=2).encode())
        try: private_write(args.output, data)
        except BaseException: sidecar.unlink(missing_ok=True); raise
        print(json.dumps({"epub": str(args.output.resolve()), "report": str(sidecar.resolve()),
                          "chapters": len(report["selected"]), "output_sha256": report["output_sha256"]}, ensure_ascii=False))


if __name__ == "__main__":
    try: main()
    except (ValueError, KeyError, StopIteration, ET.ParseError, zipfile.BadZipFile, OSError) as error:
        reason = str(error) if isinstance(error, SelectionError) else "Unsupported or malformed EPUB/selection input, or output path unavailable"
        print("EPUB selection failed: " + reason + ". No import was submitted.", file=sys.stderr)
        raise SystemExit(1)
