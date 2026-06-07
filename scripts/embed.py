import os
import glob
import sys

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
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

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
