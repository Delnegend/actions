#!/usr/bin/env python3
"""Auto-generate README.md, LICENSE-MIT, and LICENSE-APACHE from README.yml.

Usage:
    python3 README.py [PATH_OR_DIR]
    python3 README.py --check [PATH_OR_DIR]

Zero external dependencies: uses PyYAML if installed, otherwise falls back
to an internal lightweight YAML parser for README.yml structures.
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import sys
from pathlib import Path
from typing import Any

# Allowed top-level fields matching the canonical JSON schema.
ALLOWED_FIELDS = {
    "$schema",
    "name",
    "repo",
    "tagline",
    "badges",
    "quick_start",
    "highlights",
    "documentation",
    "license",
}

# All fields in the layout are required.
REQUIRED_FIELDS = [
    "name",
    "repo",
    "tagline",
    "badges",
    "quick_start",
    "highlights",
    "documentation",
    "license",
]

# Required keys in documentation object
REQUIRED_DOC_KEYS = ["architecture", "development", "deployment"]

SUPPORTED_LICENSES = {"MIT", "APACHE-2.0"}

APACHE_2_TEMPLATE = """                                 Apache License
                           Version 2.0, January 2004
                        http://www.apache.org/licenses/

   TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION

   1. Definitions.

      "License" shall mean the terms and conditions for use, reproduction,
      and distribution as defined by Sections 1 through 9 of this document.

      "Licensor" shall mean the copyright owner or entity authorized by
      the copyright owner that is granting the License.

      "Legal Entity" shall mean the union of the acting entity and all
      other entities that control, are controlled by, or are under common
      control with that entity. For the purposes of this definition,
      "control" means (i) the power, direct or indirect, to cause the
      direction or management of such entity, whether by contract or
      otherwise, or (ii) ownership of fifty percent (50%) or more of the
      outstanding shares, or (iii) beneficial ownership of such entity.

      "You" (or "Your") shall mean an individual or Legal Entity
      exercising permissions granted by this License.

      "Source" form shall mean the preferred form for making modifications,
      including but not limited to software source code, documentation
      source, and configuration files.

      "Object" form shall mean any form resulting from mechanical
      transformation or translation of a Source form, including but
      not limited to compiled object code, generated documentation,
      and conversions to other media types.

      "Work" shall mean the work of authorship, whether in Source or
      Object form, made available under the License, as indicated by a
      copyright notice that is included in or attached to the work
      (an example is provided in the Appendix below).

      "Derivative Works" shall mean any work, whether in Source or Object
      form, that is based on (or derived from) the Work and for which the
      editorial revisions, annotations, elaborations, or other modifications
      represent, as a whole, an original work of authorship. For the purposes
      of this License, Derivative Works shall not include works that remain
      separable from, or merely link (or bind by name) to the interfaces of,
      the Work and Derivative Works thereof.

      "Contribution" shall mean any work of authorship, including
      the original version of the Work and any modifications or additions
      to that Work or Derivative Works thereof, that is intentionally
      submitted to Licensor for inclusion in the Work by the copyright owner
      or by an individual or Legal Entity authorized to submit on behalf of
      the copyright owner. For the purposes of this definition, "submitted"
      means any form of electronic, verbal, or written communication sent
      to the Licensor or its representatives, including but not limited to
      communication on electronic mailing lists, source code control systems,
      and issue tracking systems that are managed by, or on behalf of, the
      Licensor for the purpose of discussing and improving the Work, but
      excluding communication that is conspicuously marked or otherwise
      designated in writing by the copyright owner as "Not a Contribution."

      "Contributor" shall mean Licensor and any individual or Legal Entity
      on behalf of whom a Contribution has been received by Licensor and
      subsequently incorporated within the Work.

   2. Grant of Copyright License. Subject to the terms and conditions of
      this License, each Contributor hereby grants to You a perpetual,
      worldwide, non-exclusive, no-charge, royalty-free, irrevocable
      copyright license to reproduce, prepare Derivative Works of,
      publicly display, publicly perform, sublicense, and distribute the
      Work and such Derivative Works in Source or Object form.

   3. Grant of Patent License. Subject to the terms and conditions of
      this License, each Contributor hereby grants to You a perpetual,
      worldwide, non-exclusive, no-charge, royalty-free, irrevocable
      (except as stated in this section) patent license to make, have made,
      use, offer to sell, sell, import, and otherwise transfer the Work,
      where such license applies only to those patent claims licensable
      by such Contributor that are necessarily infringed by their
      Contribution(s) alone or by combination of their Contribution(s)
      with the Work to which such Contribution(s) was submitted. If You
      institute patent litigation against any entity (including a
      cross-claim or counterclaim in a lawsuit) alleging that the Work
      or a Contribution incorporated within the Work constitutes direct
      or contributory patent infringement, then any patent licenses
      granted to You under this License for that Work shall terminate
      as of the date such litigation is filed.

   4. Redistribution. You may reproduce and distribute copies of the
      Work or Derivative Works thereof in any medium, with or without
      modifications, and in Source or Object form, provided that You
      meet the following conditions:

      (a) You must give any other recipients of the Work or
          Derivative Works a copy of this License; and

      (b) You must cause any modified files to carry prominent notices
          stating that You changed the files; and

      (c) You must retain, in the Source form of any Derivative Works
          that You distribute, all copyright, patent, trademark, and
          attribution notices from the Source form of the Work,
          excluding those notices that do not pertain to any part of
          the Derivative Works; and

      (d) If the Work includes a "NOTICE" text file as part of its
          distribution, then any Derivative Works that You distribute must
          include a readable copy of the attribution notices contained
          within such NOTICE file, excluding those notices that do not
          pertain to any part of the Derivative Works, in at least one
          of the following places: within a NOTICE text file distributed
          as part of the Derivative Works; within the Source form or
          documentation, if provided along with the Derivative Works; or,
          within a display generated by the Derivative Works, if and
          wherever such third-party notices normally appear. The contents
          of the NOTICE file are for informational purposes only and
          do not modify the License. You may add Your own attribution
          notices within Derivative Works that You distribute, alongside
          or as an addendum to the NOTICE text from the Work, provided
          that such additional attribution notices cannot be construed
          as modifying the License.

      You may add Your own copyright statement to Your modifications and
      may provide additional or different license terms and conditions
      for use, reproduction, or distribution of Your modifications, or
      for any such Derivative Works as a whole, provided Your use,
      reproduction, and distribution of the Work otherwise complies with
      the conditions stated in this License.

   5. Submission of Contributions. Unless You explicitly state otherwise,
      any Contribution intentionally submitted for inclusion in the Work
      by You to the Licensor shall be under the terms and conditions of
      this License, without any additional terms or conditions.
      Notwithstanding the above, nothing herein shall supersede or modify
      the terms of any separate license agreement you may have executed
      with Licensor regarding such Contributions.

   6. Trademarks. This License does not grant permission to use the trade
      names, trademarks, service marks, or product names of the Licensor,
      except as required for reasonable and customary use in describing the
      origin of the Work and reproducing the content of the NOTICE file.

   7. Disclaimer of Warranty. Unless required by applicable law or
      agreed to in writing, Licensor provides the Work (and each
      Contributor provides its Contributions) on an "AS IS" BASIS,
      WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
      implied, including, without limitation, any warranties or conditions
      of TITLE, NON-INFRINGEMENT, MERCHANTABILITY, or FITNESS FOR A
      PARTICULAR PURPOSE. You are solely responsible for determining the
      appropriateness of using or redistributing the Work and assume any
      risks associated with Your exercise of permissions under this License.

   8. Limitation of Liability. In no event and under no legal theory,
      whether in tort (including negligence), contract, or otherwise,
      unless required by applicable law (such as deliberate and grossly
      negligent acts) or agreed to in writing, shall any Contributor be
      liable to You for damages, including any direct, indirect, special,
      incidental, or consequential damages of any character arising as a
      result of this License or out of the use or inability to use the
      Work (including but not limited to damages for loss of goodwill,
      work stoppage, computer failure or malfunction, or any and all
      other commercial damages or losses), even if such Contributor
      has been advised of the possibility of such damages.

   9. Accepting Warranty or Additional Liability. While redistributing
      the Work or Derivative Works thereof, You may choose to offer,
      and charge a fee for, acceptance of support, warranty, indemnity,
      or other liability obligations and/or rights consistent with this
      License. However, in accepting such obligations, You may act only
      on Your own behalf and on Your sole responsibility, not on behalf
      of any other Contributor, and only if You agree to indemnify,
      defend, and hold each Contributor harmless for any liability
      incurred by, or claims asserted against, such Contributor by reason
      of your accepting any such warranty or additional liability.

   END OF TERMS AND CONDITIONS

   APPENDIX: How to apply the Apache License to your work.

      To apply the Apache License to your work, attach the following
      boilerplate notice, with the fields enclosed by brackets "[]"
      replaced with your own identifying information. (Don't include
      the brackets!)  The text should be enclosed in the appropriate
      comment syntax for the file format. We also recommend that a
      file or class name and description of purpose be included on the
      same "printed page" as the copyright notice for easier
      identification within third-party archives.

   Copyright {year} {holder}

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
"""

MIT_TEMPLATE = """MIT License

Copyright (c) {year} {holder}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


def _parse_scalar(val: str) -> Any:
    val = val.strip()
    if not val:
        return ""
    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
        s = val[1:-1]
        return s.replace('\\"', '"').replace("\\'", "'").replace("\\n", "\n")
    low = val.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "~", "none"):
        return None
    try:
        if "." in val:
            return float(val)
        return int(val)
    except ValueError:
        pass
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        if not inner:
            return []
        parts: list[str] = []
        cur: list[str] = []
        in_q: str | None = None
        for ch in inner:
            if ch in ('"', "'"):
                if in_q == ch:
                    in_q = None
                elif not in_q:
                    in_q = ch
            elif ch == "," and not in_q:
                parts.append("".join(cur).strip())
                cur = []
                continue
            cur.append(ch)
        if cur:
            parts.append("".join(cur).strip())
        return [_parse_scalar(p) for p in parts]
    return val


def parse_yaml_content(text: str) -> dict[str, Any]:
    """Parse YAML text using PyYAML if present, otherwise using built-in parser."""
    try:
        import yaml  # type: ignore

        res = yaml.safe_load(text)
        if isinstance(res, dict):
            return res
        return {}
    except ImportError:
        pass

    raw_lines = text.splitlines()
    parsed_lines: list[tuple[int, int, str]] = []
    for idx, line in enumerate(raw_lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        parsed_lines.append((idx, indent, stripped))

    def get_multiline_scalar(raw_start_idx: int, parent_indent: int) -> tuple[str, int]:
        scalar_lines: list[str] = []
        target_indent: int | None = None
        curr_idx = raw_start_idx + 1
        while curr_idx < len(raw_lines):
            r_line = raw_lines[curr_idx]
            stripped = r_line.strip()
            if not stripped:
                scalar_lines.append("")
                curr_idx += 1
                continue
            line_indent = len(r_line) - len(r_line.lstrip(" "))
            if target_indent is None:
                if line_indent <= parent_indent:
                    break
                target_indent = line_indent
            if line_indent < target_indent:
                break
            scalar_lines.append(r_line[target_indent:])
            curr_idx += 1
        return "\n".join(scalar_lines).strip("\n"), curr_idx

    def parse_block(p_idx: int, current_indent: int) -> tuple[Any, int]:
        if p_idx >= len(parsed_lines):
            return None, p_idx

        _, _, first_content = parsed_lines[p_idx]
        is_list = first_content.startswith("- ") or first_content == "-"

        if is_list:
            items: list[Any] = []
            while p_idx < len(parsed_lines):
                raw_i, indent, content = parsed_lines[p_idx]
                if indent < current_indent:
                    break
                if not (content.startswith("- ") or content == "-"):
                    break

                item_text = content[2:].strip() if content.startswith("- ") else ""
                p_idx += 1

                if item_text in ("|", "|-", ">", ">-"):
                    scalar, raw_end = get_multiline_scalar(raw_i, indent)
                    items.append(scalar)
                    while p_idx < len(parsed_lines) and parsed_lines[p_idx][0] < raw_end:
                        p_idx += 1
                else:
                    m = re.match(r"^([a-zA-Z0-9_\-\$]+)\s*:(?:\s+(.*)|$)", item_text)
                    if m:
                        k = m.group(1)
                        v = (m.group(2) or "").strip()
                        sub_dict: dict[str, Any] = {}
                        sub_indent = indent + 2
                        if v in ("|", "|-", ">", ">-"):
                            scalar, raw_end = get_multiline_scalar(raw_i, indent)
                            sub_dict[k] = scalar
                            while p_idx < len(parsed_lines) and parsed_lines[p_idx][0] < raw_end:
                                p_idx += 1
                        elif v:
                            sub_dict[k] = _parse_scalar(v)
                        else:
                            val, p_idx = parse_block(p_idx, sub_indent)
                            sub_dict[k] = val

                        while p_idx < len(parsed_lines):
                            next_raw, next_indent, next_content = parsed_lines[p_idx]
                            if next_indent < sub_indent:
                                break
                            if next_content.startswith("- ") or next_content == "-":
                                break
                            km = re.match(r"^([a-zA-Z0-9_\-\$]+)\s*:(?:\s+(.*)|$)", next_content)
                            if km:
                                nk = km.group(1)
                                nv = (km.group(2) or "").strip()
                                p_idx += 1
                                if nv in ("|", "|-", ">", ">-"):
                                    scalar, raw_end = get_multiline_scalar(next_raw, next_indent)
                                    sub_dict[nk] = scalar
                                    while p_idx < len(parsed_lines) and parsed_lines[p_idx][0] < raw_end:
                                        p_idx += 1
                                elif nv:
                                    sub_dict[nk] = _parse_scalar(nv)
                                else:
                                    nval, p_idx = parse_block(p_idx, next_indent + 2)
                                    sub_dict[nk] = nval
                            else:
                                p_idx += 1
                        items.append(sub_dict)
                    elif item_text:
                        items.append(_parse_scalar(item_text))
                    else:
                        sub_val, p_idx = parse_block(p_idx, indent + 2)
                        items.append(sub_val)
            return items, p_idx

        mapping: dict[str, Any] = {}
        while p_idx < len(parsed_lines):
            raw_i, indent, content = parsed_lines[p_idx]
            if indent < current_indent:
                break
            m = re.match(r"^([a-zA-Z0-9_\-\$]+)\s*:(?:\s+(.*)|$)", content)
            if not m:
                p_idx += 1
                continue
            k = m.group(1)
            v = (m.group(2) or "").strip()

            if "#" in v and not ((v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'"))):
                v = v.split("#", 1)[0].strip()

            p_idx += 1
            if v in ("|", "|-", ">", ">-"):
                scalar, raw_end = get_multiline_scalar(raw_i, indent)
                mapping[k] = scalar
                while p_idx < len(parsed_lines) and parsed_lines[p_idx][0] < raw_end:
                    p_idx += 1
            elif v:
                mapping[k] = _parse_scalar(v)
            else:
                if p_idx < len(parsed_lines):
                    _, next_indent, _ = parsed_lines[p_idx]
                    if next_indent > indent:
                        val, p_idx = parse_block(p_idx, next_indent)
                        mapping[k] = val
                    else:
                        mapping[k] = None
                else:
                    mapping[k] = None
        return mapping, p_idx

    res, _ = parse_block(0, 0)
    return res if isinstance(res, dict) else {}


def get_license_types(cfg: dict[str, Any]) -> list[str] | None:
    """Validate and return normalized license types list, or None if unlicensed."""
    lic_cfg = cfg.get("license")
    if not isinstance(lic_cfg, dict):
        raise ValueError("Missing required object: 'license'")
    if "year" in lic_cfg:
        raise ValueError("Field 'license.year' is removed; current year is always used automatically.")
    if "type" not in lic_cfg:
        raise ValueError("Missing required field 'license.type' (expected list of licenses or false).")

    raw_types = lic_cfg["type"]
    if raw_types is False:
        return None

    if not isinstance(raw_types, list) or not raw_types:
        raise ValueError(
            "Field 'license.type' must be false (for unlicensed) or a non-empty list of: ['MIT'], ['APACHE-2.0']."
        )

    types: list[str] = []
    for t in raw_types:
        norm = str(t).strip().upper()
        if norm not in SUPPORTED_LICENSES:
            raise ValueError(
                f"Unsupported license '{t}'. Currently only 'MIT' and 'APACHE-2.0' are supported."
            )
        if norm not in types:
            types.append(norm)
    return types


def validate_config(cfg: dict[str, Any]) -> None:
    """Ensure all required layout fields are present and no custom sections exist."""
    disallowed = set(cfg.keys()) - ALLOWED_FIELDS
    if disallowed:
        unknown = ", ".join(sorted(disallowed))
        valid = ", ".join(sorted(ALLOWED_FIELDS))
        raise ValueError(
            f"Custom sections are not permitted. Unknown keys found: {unknown}.\n"
            f"Allowed common sections: {valid}"
        )

    # All layout fields are required
    missing = [f for f in REQUIRED_FIELDS if f not in cfg]
    if missing:
        raise ValueError(f"Missing required layout fields: {', '.join(missing)}")

    # Validate badges
    badges = cfg.get("badges")
    if not isinstance(badges, dict):
        raise ValueError("Field 'badges' must be an object.")
    for b in ("ci", "release", "license"):
        if b not in badges:
            raise ValueError(f"Missing required badge field: 'badges.{b}'")

    # Validate highlights
    highlights = cfg.get("highlights")
    if not isinstance(highlights, list) or not highlights:
        raise ValueError("Field 'highlights' must be a non-empty list of strings.")

    # Validate documentation
    docs = cfg.get("documentation")
    if not isinstance(docs, dict):
        raise ValueError("Field 'documentation' must be an object.")
    missing_docs = [k for k in REQUIRED_DOC_KEYS if k not in docs]
    if missing_docs:
        raise ValueError(
            f"Missing required documentation entries: {', '.join(missing_docs)}. "
            f"Expected: architecture, development, deployment"
        )
    extra_docs = set(docs.keys()) - set(REQUIRED_DOC_KEYS)
    if extra_docs:
        raise ValueError(
            f"Unknown documentation entries: {', '.join(sorted(extra_docs))}. "
            f"Allowed documentation entries: {', '.join(REQUIRED_DOC_KEYS)}"
        )

    # Validate license
    get_license_types(cfg)


def build_readme(cfg: dict[str, Any]) -> str:
    validate_config(cfg)

    name = cfg["name"]
    repo = cfg["repo"]
    tagline = cfg["tagline"]
    badges_cfg = cfg["badges"]
    license_cfg = cfg["license"]

    lic_types = get_license_types(cfg)
    is_unlicensed = lic_types is None

    # Badges
    badges: list[str] = []

    # CI badge
    ci_opt = badges_cfg["ci"]
    if ci_opt:
        branch = "main"
        workflow = "ci.yml"
        if isinstance(ci_opt, dict):
            branch = ci_opt.get("branch", branch)
            workflow = ci_opt.get("workflow", workflow)
        badges.append(
            f"[![CI](https://img.shields.io/github/actions/workflow/status/{repo}/{workflow}?branch={branch}&style=flat-square)](https://github.com/{repo}/actions)"
        )

    # Release badge
    if badges_cfg["release"]:
        badges.append(
            f"[![Release](https://img.shields.io/github/v/release/{repo}?style=flat-square)](https://github.com/{repo}/releases)"
        )

    # License badge (omit if unlicensed)
    if badges_cfg["license"] and not is_unlicensed and lic_types:
        if "MIT" in lic_types and "APACHE-2.0" in lic_types:
            badges.append(
                "[![License](https://img.shields.io/badge/license-MIT%20%7C%20Apache--2.0-blue?style=flat-square)](LICENSE-MIT)"
            )
        elif lic_types == ["APACHE-2.0"]:
            badges.append(
                "[![License](https://img.shields.io/badge/license-Apache--2.0-blue?style=flat-square)](LICENSE-APACHE)"
            )
        else:
            filename = license_cfg.get("filename", "LICENSE-MIT")
            badges.append(
                f"[![License](https://img.shields.io/badge/license-MIT-blue?style=flat-square)]({filename})"
            )

    # Custom badges
    for custom in badges_cfg.get("custom", []):
        if isinstance(custom, dict) and "image" in custom and "url" in custom:
            lbl = custom.get("label", "badge")
            badges.append(f"[![{lbl}]({custom['image']})]({custom['url']})")

    out: list[str] = [
        '<div align="center">',
        "",
        f"# {name}",
        "",
        f"**{tagline}**",
        "",
        "\n".join(badges),
        "",
        "</div>",
        "",
        "---",
        "",
    ]

    # Quick Start
    out.append("## Quick Start\n")
    out.append(str(cfg["quick_start"]).strip() + "\n")

    # Highlights
    out.append("## Highlights\n")
    for h in cfg["highlights"]:
        out.append(f"- {h}")
    out.append("")

    # Documentation
    out.append("## Documentation\n")
    docs = cfg["documentation"]
    doc_defaults = {
        "architecture": ("Architecture", "docs/architecture.md"),
        "development": ("Development", "docs/development.md"),
        "deployment": ("Deployment", "docs/deployment.md"),
    }
    for key in REQUIRED_DOC_KEYS:
        val = docs[key]
        default_title, default_path = doc_defaults[key]
        if isinstance(val, dict):
            title = val.get("title", default_title)
            path = val.get("path", default_path)
            desc = val.get("description", "")
        else:
            title = default_title
            path = default_path
            desc = str(val).strip()

        if desc:
            out.append(f"- **[{title}]({path})**: {desc}")
        else:
            out.append(f"- **[{title}]({path})**")
    out.append("")

    # License
    out.append("## License\n")
    if license_cfg.get("text"):
        out.append(str(license_cfg["text"]).strip())
    elif is_unlicensed:
        lic_text = "UNLICENSED: internal lab tool."
        if license_cfg.get("note"):
            lic_text += f" {str(license_cfg['note']).strip()}"
        out.append(lic_text)
    elif lic_types:
        if "MIT" in lic_types and "APACHE-2.0" in lic_types:
            lic_text = "Dual-licensed under [MIT](LICENSE-MIT) or [Apache-2.0](LICENSE-APACHE), at your option."
        elif lic_types == ["APACHE-2.0"]:
            lic_text = "[Apache-2.0](LICENSE-APACHE)"
        else:
            filename = license_cfg.get("filename", "LICENSE-MIT")
            lic_text = f"[MIT]({filename})"

        if license_cfg.get("note"):
            lic_text += f" {str(license_cfg['note']).strip()}"
        out.append(lic_text)

    out.append("")
    return "\n".join(out)


def build_license_mit(cfg: dict[str, Any]) -> str:
    license_cfg = cfg.get("license", {})
    current_year = datetime.datetime.now(datetime.timezone.utc).year
    holder = license_cfg.get("holder", "Delnegend")

    if isinstance(holder, list):
        copyright_line = "\n".join(
            f"Copyright (c) {current_year} {h}" if not str(h).startswith("Copyright") else str(h)
            for h in holder
        )
        return (
            "MIT License\n\n"
            + copyright_line
            + "\n\n"
            + MIT_TEMPLATE.split("\n\n", 2)[2]
        )

    return MIT_TEMPLATE.format(year=current_year, holder=holder)


def build_license_apache(cfg: dict[str, Any]) -> str:
    license_cfg = cfg.get("license", {})
    current_year = datetime.datetime.now(datetime.timezone.utc).year
    holder = str(license_cfg.get("holder", "Delnegend"))

    return APACHE_2_TEMPLATE.format(year=current_year, holder=holder)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Auto-generate README.md and LICENSE files from README.yml"
    )
    parser.add_argument(
        "config",
        nargs="?",
        default="README.yml",
        help="Path to README.yml or directory containing it (default: ./README.yml)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        default=None,
        help="Target output directory (default: directory containing README.yml)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check whether generated files match on disk without modifying",
    )
    parser.add_argument(
        "--no-license",
        action="store_true",
        help="Skip generating LICENSE files",
    )

    args = parser.parse_args()

    config_path = Path(args.config)
    if config_path.is_dir():
        candidate = config_path / "README.yml"
        if not candidate.is_file():
            candidate = config_path / "README.yaml"
        config_path = candidate

    if not config_path.is_file():
        print(f"Error: configuration file '{config_path}' not found.", file=sys.stderr)
        return 1

    content = config_path.read_text(encoding="utf-8")
    try:
        cfg = parse_yaml_content(content)
        validate_config(cfg)
    except ValueError as e:
        print(f"Error in {config_path}: {e}", file=sys.stderr)
        return 1

    out_dir = Path(args.output_dir) if args.output_dir else config_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    files_to_generate: dict[str, str] = {}
    files_to_generate["README.md"] = build_readme(cfg)

    lic_cfg = cfg.get("license", {})
    lic_types = get_license_types(cfg)

    if not args.no_license and lic_types is not None:
        if "MIT" in lic_types and "APACHE-2.0" in lic_types:
            files_to_generate["LICENSE-MIT"] = build_license_mit(cfg)
            files_to_generate["LICENSE-APACHE"] = build_license_apache(cfg)
        elif lic_types == ["APACHE-2.0"]:
            filename = lic_cfg.get("filename", "LICENSE-APACHE")
            files_to_generate[filename] = build_license_apache(cfg)
        elif lic_types == ["MIT"]:
            filename = lic_cfg.get("filename", "LICENSE-MIT")
            files_to_generate[filename] = build_license_mit(cfg)

    if args.check:
        mismatched: list[str] = []
        for name, expected in files_to_generate.items():
            target = out_dir / name
            if not target.is_file():
                mismatched.append(f"{name} (missing)")
                continue
            actual = target.read_text(encoding="utf-8")
            if actual != expected:
                mismatched.append(f"{name} (content changed)")

        if mismatched:
            print("Drift detected! The following files differ from README.yml:", file=sys.stderr)
            for m in mismatched:
                print(f"  - {m}", file=sys.stderr)
            return 1
        print("All generated files match README.yml.")
        return 0

    for name, gen_content in files_to_generate.items():
        target = out_dir / name
        target.write_text(gen_content, encoding="utf-8")
        print(f"Generated {target}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
