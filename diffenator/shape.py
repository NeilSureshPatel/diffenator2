"""
Check fonts for shaping regressions using real words.
"""
import argparse
import unicodedata2 as uni
from dataclasses import dataclass
from lxml import etree
from lxml import objectify
from collections import defaultdict
import uharfbuzz as hb
import os
from diffenator.ft_hb_shape import render_text
from pkg_resources import resource_filename
import ahocorasick
from jinja2 import pass_environment


# functions to build word lists


def build_words(fp, out, keep_chars=None):
    root = objectify.parse(fp).getroot()
    bank = set()
    word_freq = defaultdict(int)
    for page in root.page:
        page_text = etree.tostring(page.revision, encoding="unicode")
        words = page_text.split()
        for word in words:
            word_freq[word] += 1
            if keep_chars and all(c in keep_chars for c in word):
                bank.add(word)

    words = remove_substring_words(bank)
    # Remove pairs which have already been seen
    res = set()
    for word in words:
        if word_freq[word] <= 2:
            continue
        res.add(word)
    with open(out, "w") as doc:
        doc.write("\n".join(res))


def remove_substring_words(words):
    res = set()
    auto = ahocorasick.Automaton()
    for word in words:
        auto.add_word(word, word)
        res.add(word)
    auto.make_automaton()

    for word in words:
        for end_ind, found in auto.iter(word):
            if word != found:
                try:
                    res.remove(found)
                except:
                    all
    return res


# Functions to test word lists


ot_to_html_lang = {
    ("", ""): "en",
    ("latn", "dflt"): "en",
    ("arab", "ARA"): "ar",
    ("dev2", "HIN"): "hi",
    ("dev2", "MAR"): "mr",
    ("dev2", "NEP"): "ne",
    ("latn", "MOL"): "mo",
    ("cyrl", "SRB"): "sr",
}


class Renderable:
    @pass_environment
    def render(self, jinja):
        classname = self.__class__.__name__
        template = jinja.get_template(f"{classname}.partial.html")
        return template.render(self.__dict__)


@dataclass
class Word:
    string: str
    hb: str

    def __eq__(self, other):
        return (self.string, hb) == (other.string, other.hb)

    def __hash__(self):
        return hash((self.string, self.hb))


@dataclass
class WordDiff(Renderable):
    string: str
    hb_a: str
    hb_b: str
    ot_features: tuple
    lang: str

    def __hash__(self):
        return hash((self.string, self.hb_a, self.hb_b, self.ot_features))


@dataclass
class Glyph(Renderable):
    string: str
    name: str
    unicode: str

    def __hash__(self):
        return hash((self.string, self.name, self.unicode))


@dataclass
class GlyphDiff(Renderable):
    string: str
    name: str
    unicode: str
    changed_pixels: float

    def __hash__(self):
        return hash((self.string, self.name, self.unicode))


@dataclass
class GlyphItems:
    missing: list
    new: list
    modified: list


def gid_pos_hash(info, pos):
    return f"gid={info.codepoint}, pos={pos.position}<br>"


def gid_hash(info, _):
    return f"gid={info.codepoint}"


def test_fonts(font_a, font_b):
    glyphs = test_font_glyphs(font_a, font_b)
    skip_glyphs = glyphs.missing + glyphs.new
    words = test_font_words(font_a, font_b, skip_glyphs)
    return {"glyphs": glyphs, "words": words}


def test_font_glyphs(font_a, font_b):
    cmap_a = set(chr(c) for c in font_a.ttFont.getBestCmap())
    cmap_b = set(chr(c) for c in font_b.ttFont.getBestCmap())
    missing_glyphs = set(Glyph(c, uni.name(c), ord(c)) for c in cmap_a - cmap_b)
    new_glyphs = set(Glyph(c, uni.name(c), ord(c)) for c in cmap_b - cmap_a)
    same_glyphs = cmap_a & cmap_b
    skip_glyphs = missing_glyphs | new_glyphs
    modified_glyphs = []
    for g in same_glyphs:
        pc = px_diff(font_a, font_b, g)
        if pc > 0.0005:
            try:
                uni_name = uni.name(g)
            except ValueError:
                uni_name = ""
            glyph = GlyphDiff(g, uni_name, ord(g), pc)
            modified_glyphs.append(glyph)
    modified_glyphs.sort(key=lambda k: k.changed_pixels, reverse=True)

    return GlyphItems(
        list(sorted(missing_glyphs, key=lambda k: k.string)),
        list(sorted(new_glyphs, key=lambda k: k.string)),
        modified_glyphs,
    )


def test_font_words(font_a, font_b, skip_glyphs=set()):
    from youseedee import ucd_data
    from collections import defaultdict

    scripts = defaultdict(int)
    cmap_a = font_a.ttFont.getBestCmap()
    for k in cmap_a:
        data = ucd_data(k)
        try:
            scripts[data["Script"]] += 1
        except:
            continue

    res = {}
    for script, count in scripts.items():
        if count < 10:
            continue
        wordlist = resource_filename("diffenator", f"data/wordlists/{script}.txt")
        if not os.path.exists(wordlist):
            print(f"No wordlist for {script}")
            continue
        res[script] = test_words(wordlist, font_a, font_b, skip_glyphs=skip_glyphs)
    return res


def test_words(word_file, font_a, font_b, skip_glyphs=set(), hash_func=gid_pos_hash):
    res = set()
    with open(word_file) as doc:
        words = doc.read().split("\n")
        print(f"testing {len(words)} words")
        word_total = len(words)
        for i, line in enumerate(words):
            items = line.split(",")
            try:
                word, script, lang, features = items[0], items[1], items[2], items[3:]
            except IndexError:
                word, script, lang, features = items[0], "latn", "dflt", []
            features = {k: True for k in features}
            if any(c.string in word for c in skip_glyphs):
                continue

            buf_a = hb.Buffer()
            buf_a.script = script
            buf_a.language = lang
            buf_a.add_str(word)
            buf_a.guess_segment_properties()
            hb.shape(font_a.hbFont, buf_a, features=features)

            infos_a = buf_a.glyph_infos
            pos_a = buf_a.glyph_positions
            hb_a = "".join(hash_func(i, j) for i, j in zip(infos_a, pos_a))
            word_a = Word(word, hb_a)

            buf_b = hb.Buffer()
            buf_b.script = script
            buf_b.language = lang
            buf_b.add_str(word)
            buf_b.guess_segment_properties()
            hb.shape(font_b.hbFont, buf_b, features=features)

            infos_b = buf_b.glyph_infos
            pos_b = buf_b.glyph_positions
            hb_b = "".join(hash_func(i, j) for i, j in zip(infos_b, pos_b))
            word_b = Word(word, hb_b)

            if word_a != word_b:
                pc = px_diff(font_a, font_b, word, script=script, lang=lang, features=features)
                if pc >= 0.002:
                    res.add(
                        (
                            pc,
                            WordDiff(
                                word,
                                word_a.hb,
                                word_b.hb,
                                tuple(features.keys()),
                                ot_to_html_lang.get((script, lang)),
                            ),
                        )
                    )
    return [w[1] for w in sorted(res, key=lambda k: k[0], reverse=True)]


def px_diff(font_a, font_b, string, script=None, lang=None, features=None):
    pc = 0.0
    try:
        img_a = render_text(
            font_a,
            string,
            fontSize=12,
            margin=0,
            features=features,
            script=script,
            lang=lang,
        )
        img_b = render_text(
            font_b,
            string,
            fontSize=12,
            margin=0,
            features=features,
            script=script,
            lang=lang,
        )
        width = min([img_a.width, img_b.width])
        height = min([img_a.height, img_b.height])
        diff_pixels = 0
        for x in range(width):
            for y in range(height):
                px_a = img_a.getpixel((x, y))
                px_b = img_b.getpixel((x, y))
                if px_a != px_b:
                    diff_pixels += abs(px_a[0] - px_b[0])
                    diff_pixels += abs(px_a[1] - px_b[1])
                    diff_pixels += abs(px_a[2] - px_b[2])
                    diff_pixels += abs(px_a[3] - px_b[3])
        pc = diff_pixels / (width * height * 256 * 3 * 3 * 3)
    except:
        all
    return pc


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(required=True, dest="cmd")

    build = subparsers.add_parser("build")
    build.add_argument("xml_fp")
    build.add_argument("out")
    build.add_argument("--glyphs", "-g", default=None)

    args = parser.parse_args()

    if args.cmd == "build":
        glyphs = None if not args.glyphs else set(args.glyphs)
        build_words(args.xml_fp, args.out, glyphs)
    else:
        raise ValueError(f"{args.cmd} unsupported command")


if __name__ == "__main__":
    main()
