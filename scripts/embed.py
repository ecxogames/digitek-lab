import os
import glob
import sys

BASE_DELIM = "ESD_HTML_END"

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

        # Find a raw-string delimiter that won't appear in the content
        delim = BASE_DELIM
        counter = 0
        while f"){delim}\"" in content:
            counter += 1
            delim = f"{BASE_DELIM}_{counter}"

        lines.append(f'        {{"{key}", R"{delim}({content}){delim}"}},')
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
