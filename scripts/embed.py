import os
import glob
import sys
import re
import html
import json

BASE_DELIM = "ESD_HTML_END"
CHUNK_SIZE = 12000

def cpp_string_literal(value):
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

def raw_string_literal(content, suffix=""):
    delim = f"{BASE_DELIM}{suffix}"
    counter = 0
    while f"){delim}\"" in content:
        counter += 1
        delim = f"{BASE_DELIM}{suffix}_{counter}"
    return f'R"{delim}({content}){delim}"'

def cpp_html_expression(content):
    if not content:
        return 'std::string()'

    chunks = [
        content[i:i + CHUNK_SIZE]
        for i in range(0, len(content), CHUNK_SIZE)
    ]
    literals = [
        raw_string_literal(chunk, f"_{idx}")
        for idx, chunk in enumerate(chunks)
    ]

    if len(literals) == 1:
        return f"std::string({literals[0]})"

    indented = ("\n" + " " * 16 + "+ ").join(literals[1:])
    return f"std::string({literals[0]})\n" + " " * 16 + "+ " + indented

def _read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def _inline_local_assets(content, html_key):
    base_dir = os.path.dirname(html_key)

    def repl_css(match):
        tag = match.group(0)
        href_m = re.search(r'href=["\']([^"\']+)["\']', tag, re.IGNORECASE)
        if not href_m:
            return tag
        href = href_m.group(1)
        if re.match(r'^(https?:|data:|//)', href, re.IGNORECASE):
            return tag
        path = os.path.normpath(os.path.join(base_dir, href))
        if not os.path.exists(path):
            return tag
        return "<style>\n" + _read_text(path) + "\n</style>"

    def repl_js(match):
        tag = match.group(0)
        src_m = re.search(r'src=["\']([^"\']+)["\']', tag, re.IGNORECASE)
        if not src_m:
            return tag
        src = src_m.group(1)
        if re.match(r'^(https?:|data:|//)', src, re.IGNORECASE):
            return tag
        path = os.path.normpath(os.path.join(base_dir, src))
        if not os.path.exists(path):
            return tag
        return "<script>\n" + _read_text(path) + "\n</script>"

    content = re.sub(
        r'<link\b(?=[^>]*rel=["\']stylesheet["\'])(?=[^>]*href=["\'][^"\']+["\'])[^>]*>',
        repl_css,
        content,
        flags=re.IGNORECASE,
    )
    content = re.sub(
        r'<script\b(?=[^>]*src=["\'][^"\']+["\'])[^>]*>\s*</script>',
        repl_js,
        content,
        flags=re.IGNORECASE,
    )
    return content

def _component_templates():
    out = []
    components_dir = os.path.join("ui", "pages", "components")
    if not os.path.isdir(components_dir):
        return ""
    for path in sorted(glob.glob(os.path.join(components_dir, "*.html"))):
        name = os.path.splitext(os.path.basename(path))[0]
        ident = "component-" + name
        out.append(
            '<script type="application/json" id="' + html.escape(ident, quote=True) + '">'
            + json.dumps(_read_text(path))
            + "</script>"
        )
    return "\n".join(out)

def _prepare_html_for_embedding(content, html_key):
    content = _inline_local_assets(content, html_key)
    if html_key.replace("\\", "/") == "ui/pages/index.html":
        templates = _component_templates()
        if templates:
            content = content.replace("</body>", templates + "\n</body>")
    return content

def embed_html(output_path):
    seen = set()
    unique_files = []
    for pattern in ["ui/**/*.html", "ui/*.html"]:
        for filepath in glob.glob(pattern, recursive=True):
            key = filepath.replace("\\", "/")
            if key not in seen:
                seen.add(key)
                unique_files.append((key, filepath))

    lines = [
        "#pragma once",
        "#include <string>",
        "#include <unordered_map>",
        "",
        "inline const std::unordered_map<std::string, std::string>& GetEmbeddedHtml() {",
        "    static const std::unordered_map<std::string, std::string> map = {",
    ]

    for key, filepath in unique_files:
        content = _prepare_html_for_embedding(_read_text(filepath), key)

        lines.append(f'        {{{cpp_string_literal(key)}, {cpp_html_expression(content)}}},')
        print(f"[embed_html] Embedded: {key}")

    lines += [
        "    };",
        "    return map;",
        "}",
    ]

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"[embed_html] Generated '{output_path}' with {len(unique_files)} HTML file(s).")

if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "engine/embedded_html.h"
    embed_html(out)
